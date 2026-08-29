"""
redis_bus.py — Production-grade durable Redis Streams message bus with fallback.
"""
import json
import asyncio
import logging
import time
from typing import Callable, Awaitable, Dict, Optional, Set
from modules.bus.base_bus import AbstractBus
from ai.contracts import AgentTask, AgentResult, Envelope, MessageKind

logger = logging.getLogger("JARVIS.RedisBus")

class RedisBus(AbstractBus):
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        max_concurrency_per_agent: int = 4,
        max_queue_depth: int = 100,
        visibility_timeout_sec: float = 30.0,
        max_retries: int = 3,
    ):
        self.redis_url = redis_url
        self.max_concurrency_per_agent = max_concurrency_per_agent
        self.max_queue_depth = max_queue_depth
        self.visibility_timeout_sec = visibility_timeout_sec
        self.max_retries = max_retries
        
        self._handlers: Dict[str, Callable[[AgentTask], Awaitable[AgentResult]]] = {}
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._cancelled_correlations: Set[str] = set()
        self._consumer_tasks: Dict[str, asyncio.Task] = {}
        self._redis = None
        self._connected = False

    async def initialize(self):
        """Asynchronously connect to Redis and initialize consumer groups."""
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            await self._redis.ping()
            self._connected = True
            logger.info(f"RedisBus connected to {self.redis_url}")
        except Exception as e:
            logger.warning(f"RedisBus unable to connect to {self.redis_url} ({e}). Falling back to in-memory routing.")
            self._connected = False

    def register(self, agent_id: str, handler: Callable[[AgentTask], Awaitable[AgentResult]]) -> None:
        self._handlers[agent_id] = handler
        self._semaphores[agent_id] = asyncio.Semaphore(self.max_concurrency_per_agent)
        
        # Start Redis consumer loop if connected
        if self._connected and agent_id not in self._consumer_tasks:
            task = asyncio.create_task(self._consumer_loop(agent_id))
            self._consumer_tasks[agent_id] = task

    async def dispatch(self, task: AgentTask, timeout: Optional[float] = None) -> AgentResult:
        if task.correlation_id in self._cancelled_correlations:
            return AgentResult(
                task_id=task.task_id,
                success=False,
                result=None,
                error=f"Task cancelled due to correlation_id {task.correlation_id}",
                error_category="cancelled"
            )

        # Ensure correlation_id exists
        if not task.correlation_id:
            task.correlation_id = task.task_id

        # ── 1. Redis Durable Stream Dispatch ────────────────────────────────
        if self._connected and self._redis:
            try:
                queue_depth = await self.get_queue_depth(task.target_agent)
                if queue_depth > self.max_queue_depth:
                    return AgentResult(
                        task_id=task.task_id,
                        success=False,
                        result=None,
                        error=f"Backpressure limit reached for agent {task.target_agent} (queue depth {queue_depth})",
                        error_category="backpressure"
                    )

                envelope = Envelope(
                    kind=MessageKind.TASK_REQUEST,
                    correlation_id=task.correlation_id,
                    payload=task.to_dict(),
                    sender=task.origin_agent,
                    target=task.target_agent,
                    idempotency_key=task.idempotency_key
                )

                stream_key = f"jarvis:tasks:{task.target_agent}"
                result_stream_key = f"jarvis:results:{task.correlation_id}"

                await self._redis.xadd(stream_key, {"envelope": json.dumps(envelope.to_dict())})

                # Wait for result on result stream
                start_time = time.time()
                timeout_val = timeout or task.timeout_seconds or 60.0
                last_id = "$"

                while time.time() - start_time < timeout_val:
                    if task.correlation_id in self._cancelled_correlations:
                        return AgentResult(
                            task_id=task.task_id,
                            success=False,
                            result=None,
                            error="Cancelled during execution",
                            error_category="cancelled"
                        )

                    entries = await self._redis.xread({result_stream_key: last_id}, count=10, block=1000)
                    if entries:
                        for _, messages in entries:
                            for msg_id, data in messages:
                                last_id = msg_id
                                res_dict = json.loads(data.get("result", "{}"))
                                if res_dict.get("task_id") == task.task_id:
                                    return AgentResult.from_dict(res_dict)

                return AgentResult(
                    task_id=task.task_id,
                    success=False,
                    result=None,
                    error=f"RedisBus dispatch timeout ({timeout_val}s) waiting for agent {task.target_agent}",
                    error_category="timeout"
                )
            except Exception as e:
                logger.error(f"RedisBus dispatch error ({e}), falling back to in-memory execution")

        # ── 2. In-Memory Fallback Dispatch ────────────────────────────────────
        handler = self._handlers.get(task.target_agent)
        if not handler:
            return AgentResult(
                task_id=task.task_id,
                success=False,
                result=None,
                error=f"No agent registered for '{task.target_agent}'",
                error_category="unregistered_agent"
            )

        sem = self._semaphores.get(task.target_agent, asyncio.Semaphore(self.max_concurrency_per_agent))
        async with sem:
            start_t = time.time()
            try:
                timeout_val = timeout or task.timeout_seconds or 60.0
                result = await asyncio.wait_for(handler(task), timeout=timeout_val)
                result.duration_ms = (time.time() - start_t) * 1000.0
                return result
            except asyncio.TimeoutError:
                return AgentResult(
                    task_id=task.task_id,
                    success=False,
                    result=None,
                    error=f"Task timeout after {timeout_val}s",
                    duration_ms=(time.time() - start_t) * 1000.0,
                    error_category="timeout"
                )
            except Exception as e:
                return AgentResult(
                    task_id=task.task_id,
                    success=False,
                    result=None,
                    error=str(e),
                    duration_ms=(time.time() - start_t) * 1000.0,
                    error_category="execution_error"
                )

    async def _consumer_loop(self, agent_id: str):
        stream_key = f"jarvis:tasks:{agent_id}"
        group_name = f"{agent_id}-group"
        consumer_name = f"{agent_id}-worker"

        try:
            await self._redis.xgroup_create(stream_key, group_name, id="0", mkstream=True)
        except Exception:
            pass  # Group already exists

        while True:
            try:
                entries = await self._redis.xreadgroup(group_name, consumer_name, {stream_key: ">"}, count=1, block=2000)
                if not entries:
                    await asyncio.sleep(0.1)
                    continue

                for _, messages in entries:
                    for msg_id, data in messages:
                        raw_envelope = data.get("envelope")
                        if not raw_envelope:
                            await self._redis.xack(stream_key, group_name, msg_id)
                            continue

                        env_dict = json.loads(raw_envelope)
                        task_dict = env_dict.get("payload", {})
                        task = AgentTask.from_dict(task_dict)

                        handler = self._handlers.get(agent_id)
                        if handler:
                            sem = self._semaphores.get(agent_id, asyncio.Semaphore(self.max_concurrency_per_agent))
                            async with sem:
                                res = await handler(task)
                        else:
                            res = AgentResult(
                                task_id=task.task_id,
                                success=False,
                                result=None,
                                error=f"Consumer handler missing for {agent_id}"
                            )

                        result_stream_key = f"jarvis:results:{task.correlation_id}"
                        await self._redis.xadd(result_stream_key, {"result": json.dumps(res.to_dict())})
                        await self._redis.xack(stream_key, group_name, msg_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Consumer loop error for agent {agent_id}: {e}")
                await asyncio.sleep(1.0)

    async def cancel(self, correlation_id: str) -> None:
        self._cancelled_correlations.add(correlation_id)
        if self._connected and self._redis:
            try:
                await self._redis.sadd("jarvis:cancelled_correlations", correlation_id)
            except Exception as e:
                logger.warning(f"Error publishing cancellation to Redis: {e}")

    async def get_queue_depth(self, agent_id: str) -> int:
        if self._connected and self._redis:
            try:
                stream_key = f"jarvis:tasks:{agent_id}"
                return await self._redis.xlen(stream_key)
            except Exception:
                return 0
        return 0
