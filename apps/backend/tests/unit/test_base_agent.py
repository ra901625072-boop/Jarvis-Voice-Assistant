"""
tests/unit/test_base_agent.py — Unit tests for BaseAgent core logic.
"""
import pytest
from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult


class DummySpecialist(BaseAgent):
    """Test concrete implementation of BaseAgent."""
    def __init__(self):
        super().__init__(agent_id="dummy_agent")

    async def handle(self, task: AgentTask) -> AgentResult:
        if task.task_type == "echo":
            return self._create_result(task, success=True, result=task.payload)
        elif task.task_type == "fail":
            return self._create_result(task, success=False, error="Intentional failure")
        return self._create_result(task, success=False, error=f"Unknown task type {task.task_type}")


class TestBaseAgentUnit:
    @pytest.mark.asyncio
    async def test_health_check_auto_handled(self):
        """All BaseAgent subclasses automatically handle health_check tasks."""
        agent = DummySpecialist()
        task = AgentTask(task_id="t_hc", target_agent="dummy_agent", task_type="health_check")
        res = await agent.handle(task)
        assert res.success is True
        assert res.result == "ok"
        assert res.task_id == "t_hc"

    @pytest.mark.asyncio
    async def test_handle_task_success(self):
        """Custom task handling returns properly formatted AgentResult."""
        agent = DummySpecialist()
        task = AgentTask(
            task_id="t_echo",
            target_agent="dummy_agent",
            task_type="echo",
            payload={"msg": "hello"}
        )
        res = await agent.handle(task)
        assert res.success is True
        assert res.result == {"msg": "hello"}

    @pytest.mark.asyncio
    async def test_handle_task_failure(self):
        """Error handling attaches error strings and success=False."""
        agent = DummySpecialist()
        task = AgentTask(
            task_id="t_fail",
            target_agent="dummy_agent",
            task_type="fail"
        )
        res = await agent.handle(task)
        assert res.success is False
        assert res.error == "Intentional failure"
