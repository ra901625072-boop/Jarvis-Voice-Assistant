from abc import ABC, abstractmethod
from typing import Callable, Awaitable, List, Optional
import asyncio
from ai.agents.types import AgentTask, AgentResult

class AbstractBus(ABC):
    @abstractmethod
    def register(self, agent_id: str, handler: Callable[[AgentTask], Awaitable[AgentResult]]) -> None:
        """Register a handler for a specific agent."""
        pass

    @abstractmethod
    async def dispatch(self, task: AgentTask, timeout: Optional[float] = None) -> AgentResult:
        """Dispatch a task to the appropriate agent handler."""
        pass

    async def dispatch_many(self, tasks: List[AgentTask], timeout: Optional[float] = None) -> List[AgentResult]:
        """Dispatch N independent tasks to N agents concurrently, gather all results."""
        return list(await asyncio.gather(
            *[self.dispatch(t, timeout=timeout) for t in tasks],
            return_exceptions=True
        ))

    async def cancel(self, correlation_id: str) -> None:
        """Cancel all pending or executing tasks associated with correlation_id."""
        pass

    async def get_queue_depth(self, agent_id: str) -> int:
        """Get the current queue depth for an agent."""
        return 0

