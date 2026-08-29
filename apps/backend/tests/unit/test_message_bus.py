"""
tests/unit/test_message_bus.py — Unit tests for message bus routing & fallback.
"""
import asyncio
import pytest
from modules.bus.redis_bus import RedisBus
from ai.contracts import AgentTask, AgentResult


class TestMessageBusUnit:
    @pytest.mark.asyncio
    async def test_register_and_dispatch_task(self):
        """Registering a handler and dispatching a task returns the computed result."""
        bus = RedisBus()  # In-memory mode (not connected to Redis)
        
        async def mock_coding_handler(task: AgentTask) -> AgentResult:
            return AgentResult(
                task_id=task.task_id,
                success=True,
                result={"code": "def hello(): pass"},
                metadata={"agent_id": "coding_agent"}
            )

        bus.register("coding_agent", mock_coding_handler)
        
        task = AgentTask(
            task_id="t1",
            target_agent="coding_agent",
            task_type="refactor_code",
            payload={"file": "main.py"}
        )
        
        result = await bus.dispatch(task)
        assert result.success is True
        assert result.result == {"code": "def hello(): pass"}
        assert result.metadata.get("agent_id") == "coding_agent"

    @pytest.mark.asyncio
    async def test_dispatch_unregistered_agent(self):
        """Dispatching to an unregistered agent returns an unregistered_agent error."""
        bus = RedisBus()
        task = AgentTask(
            task_id="t2",
            target_agent="non_existent_agent",
            task_type="do_something"
        )
        result = await bus.dispatch(task)
        assert result.success is False
        assert result.error_category == "unregistered_agent"

    @pytest.mark.asyncio
    async def test_dispatch_many_concurrent(self):
        """dispatch_many runs multiple tasks concurrently and collects all results."""
        bus = RedisBus()

        async def mock_handler(task: AgentTask) -> AgentResult:
            await asyncio.sleep(0.01)
            return AgentResult(
                task_id=task.task_id,
                success=True,
                result={"doubled": task.payload.get("val", 0) * 2}
            )

        bus.register("math_agent", mock_handler)

        tasks = [
            AgentTask(task_id=f"m_{i}", target_agent="math_agent", payload={"val": i})
            for i in range(5)
        ]

        results = await bus.dispatch_many(tasks)
        assert len(results) == 5
        for i, res in enumerate(results):
            assert res.success is True
            assert res.result == {"doubled": i * 2}

    @pytest.mark.asyncio
    async def test_cancellation_propagation(self):
        """Cancelled correlation IDs immediately reject subsequent dispatches."""
        bus = RedisBus()
        
        async def slow_handler(task: AgentTask) -> AgentResult:
            return AgentResult(task_id=task.task_id, success=True)

        bus.register("slow_agent", slow_handler)
        
        await bus.cancel("corr_123")

        task = AgentTask(
            task_id="t_cancelled",
            target_agent="slow_agent",
            correlation_id="corr_123"
        )
        
        result = await bus.dispatch(task)
        assert result.success is False
        assert result.error_category == "cancelled"
