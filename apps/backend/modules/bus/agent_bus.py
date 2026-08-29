import asyncio
import logging
from typing import Callable, Dict, Optional, Awaitable
from ai.agents.types import AgentTask, AgentResult
from config.settings import AGENT_TIMEOUTS

logger = logging.getLogger("JARVIS.AgentBus")

from .base_bus import AbstractBus

class AgentBus(AbstractBus):
    """
    In-process asyncio-based message router.
    Each agent registers a handler. Bus routes by target_agent field.
    """
    def __init__(self):
        super().__init__()
        self._handlers: Dict[str, Callable[[AgentTask], Awaitable[AgentResult]]] = {}

    def register(self, agent_id: str, handler: Callable[[AgentTask], Awaitable[AgentResult]]) -> None:
        if agent_id in self._handlers:
            logger.warning(f"AgentBus: overwriting handler for agent '{agent_id}'")
        self._handlers[agent_id] = handler
        logger.debug(f"AgentBus: registered handler for agent '{agent_id}'")

    async def dispatch(self, task: AgentTask, timeout: Optional[float] = None) -> AgentResult:
        # Cycle Guard
        chain = getattr(task, "dispatch_chain", [])
        allowed_cycle_tasks = {"route_subtask", "generate_context", "evaluate_plan", "health_check", "record_execution_report", "recover_failure"}
        if task.target_agent in chain and task.task_type not in allowed_cycle_tasks:
            error_msg = f"Cycle detected in agent dispatch: {' -> '.join(chain)} -> {task.target_agent}"
            logger.error(error_msg)
            return AgentResult(
                task_id=task.task_id,
                success=False,
                result=None,
                error=error_msg
            )

        if task.target_agent not in self._handlers:
            error_msg = f"No handler registered for target agent '{task.target_agent}'"
            logger.error(error_msg)
            return AgentResult(
                task_id=task.task_id,
                success=False,
                result=None,
                error=error_msg
            )
        
        handler = self._handlers[task.target_agent]
        
        # Determine timeout: explicitly passed > task.timeout_seconds > global default > fallback (30.0s)
        if timeout is not None:
            effective_timeout = timeout
        elif getattr(task, 'timeout_seconds', None) is not None:
            effective_timeout = task.timeout_seconds
        else:
            effective_timeout = AGENT_TIMEOUTS.get(task.target_agent, 30.0)
        
        
        from modules.observability.trace import TraceSpan
        from container import ServiceContainer

        span = TraceSpan(
            trace_id=getattr(task, "trace_id", task.task_id),
            agent_id=task.target_agent,
            task_type=task.task_type,
        )

        try:
            result = await asyncio.wait_for(handler(task), timeout=effective_timeout)
            span.finish(success=result.success, error=result.error)
            span.confidence = getattr(result, "confidence", 0.0)
            span.tokens_used = getattr(result, "tokens_used", 0)
            span.cost_usd = getattr(result, "cost_usd", 0.0)
        except asyncio.TimeoutError:
            error_msg = f"Task timed out after {effective_timeout} seconds"
            logger.error(f"AgentBus: {error_msg} for task {task.task_id}")
            span.finish(success=False, error="timeout")
            result = AgentResult(
                task_id=task.task_id,
                success=False,
                result=None,
                error=error_msg
            )
        except Exception as e:
            error_msg = f"Task execution failed: {str(e)}"
            logger.exception(f"AgentBus: {error_msg} for task {task.task_id}")
            span.finish(success=False, error=str(e))
            result = AgentResult(
                task_id=task.task_id,
                success=False,
                result=None,
                error=error_msg
            )

        trace_store = ServiceContainer.instance().get_or_none("trace_store") if ServiceContainer.instance() else None
        if trace_store:
            trace_store.enqueue_save(span)
            
        return result
