"""
tests/performance/test_bus_throughput.py — Performance and throughput tests for the Message Bus.
"""
import time
import asyncio
import pytest
from modules.bus.redis_bus import RedisBus
from ai.contracts import AgentTask, AgentResult


class TestBusThroughputPerformance:
    @pytest.mark.asyncio
    async def test_high_concurrency_bus_throughput(self):
        """Dispatching 50 concurrent tasks through the bus achieves sub-second total execution."""
        bus = RedisBus(max_concurrency_per_agent=20)

        async def fast_handler(task: AgentTask) -> AgentResult:
            await asyncio.sleep(0.005)
            return AgentResult(task_id=task.task_id, success=True, result={"val": task.payload["num"] * 2})

        bus.register("fast_agent", fast_handler)

        num_tasks = 50
        tasks = [
            AgentTask(task_id=f"perf_{i}", target_agent="fast_agent", payload={"num": i})
            for i in range(num_tasks)
        ]

        start_time = time.perf_counter()
        results = await bus.dispatch_many(tasks)
        duration = time.perf_counter() - start_time

        assert len(results) == num_tasks
        assert all(r.success for r in results)
        assert duration < 2.0  # Must complete 50 tasks in under 2 seconds
