import asyncio
import logging
import uuid
import heapq
from typing import Dict, List, Any, Optional, Callable, Awaitable
from datetime import datetime
from enum import Enum

from events.event_bus import EventBus, TaskEvent
from modules.task.state_manager import CancellationToken

logger = logging.getLogger("JARVIS.PriorityTaskScheduler")

class TaskPriority(int, Enum):
    VOICE_INTERRUPT = 100
    CRITICAL = 95
    EMERGENCY = 95
    HIGH = 90
    USER_INTERACTIVE = 90
    CODING = 60
    NORMAL = 50
    DEFAULT = 50
    RESEARCH = 50
    LOW = 20
    TRAINING = 20

class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class TaskRecord:
    def __init__(
        self,
        task_id: str,
        name: str,
        agent: str,
        priority: int = TaskPriority.NORMAL,
        coro_func: Optional[Callable[["TaskRecord"], Awaitable[Any]]] = None,
        payload: Dict[str, Any] = None,
        dependencies: List[str] = None,
        eta_seconds: Optional[int] = None
    ):
        self.id = task_id
        self.name = name
        self.agent = agent
        self.priority = priority
        self.coro_func = coro_func
        self.payload = payload or {}
        self.dependencies = dependencies or []
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.logs: List[str] = []
        self.result: Any = None
        self.error: Optional[str] = None
        self.cancel_token = CancellationToken()
        self.pause_event = asyncio.Event()
        self.pause_event.set()  # Default to not paused
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.eta_seconds = eta_seconds

    def add_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)
        logger.info(f"Task #{self.id} ({self.name}): {message}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "agent": self.agent,
            "priority": self.priority,
            "status": self.status.value,
            "progress": self.progress,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "eta_seconds": self.eta_seconds,
            "dependencies": self.dependencies,
            "logs": self.logs[-20:],  # return latest 20 log entries
            "error": self.error
        }

    # Comparator for Heap Priority Queue (higher priority value comes first)
    def __lt__(self, other: "TaskRecord") -> bool:
        return self.priority > other.priority

class PriorityTaskScheduler:
    """
    Concurrent Multi-Agent Priority Task Scheduler for JARVIS Operating System.
    Manages concurrent execution threads/tasks, priority preemption, progress updates,
    and cancellation tokens across specialist worker agents.
    """
    _instance: Optional["PriorityTaskScheduler"] = None

    def __init__(self, max_concurrent_tasks: int = 5):
        self.max_concurrent_tasks = max_concurrent_tasks
        self._tasks: Dict[str, TaskRecord] = {}
        self._running_async_tasks: Dict[str, asyncio.Task] = {}
        self._queue: List[TaskRecord] = []
        self._lock = asyncio.Lock()
        self._worker_loop_task: Optional[asyncio.Task] = None
        self._is_running = False

    @classmethod
    def get_instance(cls) -> "PriorityTaskScheduler":
        if cls._instance is None:
            cls._instance = PriorityTaskScheduler()
        return cls._instance

    async def start(self) -> None:
        async with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._worker_loop_task = asyncio.create_task(self._scheduler_loop())
            logger.info("PriorityTaskScheduler engine started.")

    async def stop(self) -> None:
        self._is_running = False
        if self._worker_loop_task:
            self._worker_loop_task.cancel()
        # Cancel all running tasks
        for task_id in list(self._running_async_tasks.keys()):
            await self.cancel_task(task_id)

    async def submit_task(
        self,
        name: str,
        agent: str,
        coro_func: Callable[[TaskRecord], Awaitable[Any]],
        priority: int = TaskPriority.CODING,
        payload: Dict[str, Any] = None,
        dependencies: List[str] = None,
        eta_seconds: Optional[int] = None,
        task_id: Optional[str] = None
    ) -> TaskRecord:
        """Submit a new task to the scheduler queue."""
        t_id = task_id or str(uuid.uuid4())[:8]
        record = TaskRecord(
            task_id=t_id,
            name=name,
            agent=agent,
            priority=priority,
            coro_func=coro_func,
            payload=payload,
            dependencies=dependencies,
            eta_seconds=eta_seconds
        )

        async with self._lock:
            self._tasks[t_id] = record
            heapq.heappush(self._queue, record)
            record.add_log(f"Enqueued in PriorityTaskScheduler with priority {priority}")

        await EventBus.get_instance().publish(TaskEvent(
            task_id=t_id,
            task_name=name,
            agent_id=agent,
            status=TaskStatus.PENDING.value,
            progress=0,
            payload=record.to_dict()
        ))

        # Ensure scheduler worker is running
        if not self._is_running:
            await self.start()

        return record

    async def _scheduler_loop(self) -> None:
        """Main async background loop pulling prioritized tasks off the queue."""
        while self._is_running:
            try:
                await asyncio.sleep(0.1)

                async with self._lock:
                    # Clean up completed tasks from active dict
                    finished_ids = [t_id for t_id, task in self._running_async_tasks.items() if task.done()]
                    for t_id in finished_ids:
                        del self._running_async_tasks[t_id]

                    if len(self._running_async_tasks) >= self.max_concurrent_tasks:
                        continue

                    if not self._queue:
                        continue

                    # Peek at top priority task
                    task_record = heapq.heappop(self._queue)

                    # Skip if task was cancelled while pending in queue
                    if task_record.status == TaskStatus.CANCELLED or task_record.cancel_token.is_cancelled:
                        task_record.status = TaskStatus.CANCELLED
                        continue

                    # Check dependencies
                    unresolved_deps = [
                        dep_id for dep_id in task_record.dependencies
                        if dep_id in self._tasks and self._tasks[dep_id].status != TaskStatus.COMPLETED
                    ]
                    if unresolved_deps:
                        # Re-enqueue task until dependencies finish
                        heapq.heappush(self._queue, task_record)
                        continue

                    # Launch worker task
                    task_coro = self._run_task_wrapper(task_record)
                    async_task = asyncio.create_task(task_coro)
                    self._running_async_tasks[task_record.id] = async_task

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error in scheduler loop: {e}")

    async def _run_task_wrapper(self, task: TaskRecord) -> None:
        """Wrapper to execute a task, manage state transitions, logs, and progress events."""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        task.add_log("Started execution")

        await EventBus.get_instance().publish(TaskEvent(
            task_id=task.id,
            task_name=task.name,
            agent_id=task.agent,
            status=TaskStatus.RUNNING.value,
            progress=task.progress,
            payload=task.to_dict()
        ))

        try:
            # Check pause state before starting
            await task.pause_event.wait()

            if task.cancel_token.is_cancelled:
                raise asyncio.CancelledError("Task cancelled prior to execution")

            result = await task.coro_func(task)

            if task.cancel_token.is_cancelled:
                task.status = TaskStatus.CANCELLED
                task.add_log("Task cancelled during execution")
            else:
                task.status = TaskStatus.COMPLETED
                task.progress = 100
                task.result = result
                task.completed_at = datetime.now()
                task.add_log("Completed successfully")

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            task.add_log("Task execution cancelled")
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()
            task.add_log(f"Task failed with error: {e}")
            logger.exception(f"Task #{task.id} failed: {e}")

        await EventBus.get_instance().publish(TaskEvent(
            task_id=task.id,
            task_name=task.name,
            agent_id=task.agent,
            status=task.status.value,
            progress=task.progress,
            payload=task.to_dict()
        ))

    async def update_progress(self, task_id: str, progress: int, message: Optional[str] = None) -> None:
        """Update progress percentage and publish TaskEvent."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task.progress = max(0, min(100, progress))
        if message:
            task.add_log(message)

        await EventBus.get_instance().publish(TaskEvent(
            task_id=task.id,
            task_name=task.name,
            agent_id=task.agent,
            status=task.status.value,
            progress=task.progress,
            payload=task.to_dict()
        ))

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running or pending task cleanly using CancellationToken."""
        task = self._tasks.get(task_id)
        if not task:
            return False

        task.cancel_token.cancel()
        task.status = TaskStatus.CANCELLED
        task.add_log("Cancel requested by user/orchestrator")

        if task_id in self._running_async_tasks:
            self._running_async_tasks[task_id].cancel()

        await EventBus.get_instance().publish(TaskEvent(
            task_id=task.id,
            task_name=task.name,
            agent_id=task.agent,
            status=TaskStatus.CANCELLED.value,
            progress=task.progress,
            payload=task.to_dict()
        ))
        return True

    async def pause_task(self, task_id: str) -> bool:
        """Pause execution of a running or pending task."""
        task = self._tasks.get(task_id)
        if not task or task.status not in (TaskStatus.RUNNING, TaskStatus.PENDING):
            return False
        task.pause_event.clear()
        task.status = TaskStatus.PAUSED
        task.add_log("Task execution paused")
        await EventBus.get_instance().publish(TaskEvent(
            task_id=task.id,
            task_name=task.name,
            agent_id=task.agent,
            status=TaskStatus.PAUSED.value,
            progress=task.progress,
            payload=task.to_dict()
        ))
        return True

    async def resume_task(self, task_id: str) -> bool:
        """Resume execution of a paused task."""
        task = self._tasks.get(task_id)
        if not task or task.status != TaskStatus.PAUSED:
            return False
        task.status = TaskStatus.RUNNING
        task.pause_event.set()
        task.add_log("Task execution resumed")
        await EventBus.get_instance().publish(TaskEvent(
            task_id=task.id,
            task_name=task.name,
            agent_id=task.agent,
            status=TaskStatus.RUNNING.value,
            progress=task.progress,
            payload=task.to_dict()
        ))
        return True

    async def record_external_task(
        self,
        name: str,
        agent: str = "execution_agent",
        status: str = "running",
        payload: Dict[str, Any] = None
    ) -> TaskRecord:
        t_id = str(uuid.uuid4())[:8]
        record = TaskRecord(
            task_id=t_id,
            name=name,
            agent=agent,
            priority=TaskPriority.NORMAL,
            payload=payload or {}
        )
        try:
            record.status = TaskStatus(status)
        except Exception:
            record.status = TaskStatus.RUNNING
        record.add_log(f"Recorded task '{name}' for agent '{agent}'")
        async with self._lock:
            self._tasks[t_id] = record

        await EventBus.get_instance().publish(TaskEvent(
            task_id=t_id,
            task_name=name,
            agent_id=agent,
            status=record.status.value,
            progress=record.progress,
            payload=record.to_dict()
        ))
        return record

    async def update_external_task(self, task_id: str, status: str, result: str = "", progress: int = 100) -> None:
        async with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                return
            try:
                record.status = TaskStatus(status)
            except Exception:
                pass
            record.progress = progress
            if result:
                record.add_log(f"Result: {result[:120]}")

        await EventBus.get_instance().publish(TaskEvent(
            task_id=task_id,
            task_name=record.name,
            agent_id=record.agent,
            status=record.status.value,
            progress=record.progress,
            payload=record.to_dict()
        ))

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        all_records = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in all_records[:limit]]
