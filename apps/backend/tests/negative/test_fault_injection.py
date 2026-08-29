"""
tests/negative/test_fault_injection.py — Fault injection & resilience tests.
"""
import asyncio
import pytest
from modules.bus.redis_bus import RedisBus
from ai.contracts import AgentTask, AgentResult


class TestFaultInjectionNegative:
    @pytest.mark.asyncio
    async def test_agent_unhandled_exception_isolated(self):
        """Unhandled exceptions inside an agent handler return structured error result without crashing bus."""
        bus = RedisBus()

        async def crashing_agent(task: AgentTask) -> AgentResult:
            raise RuntimeError("Fatal hardware simulation crash!")

        bus.register("crashing_agent", crashing_agent)

        task = AgentTask(task_id="t_crash", target_agent="crashing_agent", task_type="do_work")
        res = await bus.dispatch(task)
        
        assert res.success is False
        assert "Fatal hardware simulation crash" in str(res.error)

    @pytest.mark.asyncio
    async def test_agent_timeout_enforcement(self):
        """Tasks exceeding timeout are terminated and return timeout category error."""
        bus = RedisBus()

        async def sleeping_agent(task: AgentTask) -> AgentResult:
            await asyncio.sleep(5.0)
            return AgentResult(task_id=task.task_id, success=True)

        bus.register("slow_agent", sleeping_agent)

        task = AgentTask(
            task_id="t_slow",
            target_agent="slow_agent",
            task_type="long_task",
            timeout_seconds=0.1
        )
        res = await bus.dispatch(task, timeout=0.1)
        
        assert res.success is False
        assert res.error_category == "timeout"
