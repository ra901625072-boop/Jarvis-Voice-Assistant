"""
tests/integration/test_agent_bus_flow.py — Integration tests for Multi-Agent routing via Message Bus.
"""
import asyncio
import pytest
from modules.bus.redis_bus import RedisBus
from ai.contracts import AgentTask, AgentResult


class TestAgentBusFlowIntegration:
    @pytest.mark.asyncio
    async def test_supervisor_to_specialist_pipeline(self):
        """Supervisor delegates planning and execution to specialist agents sequentially."""
        bus = RedisBus()

        async def mock_planner(task: AgentTask) -> AgentResult:
            steps = ["analyze_code", "write_patch", "run_tests"]
            return AgentResult(
                task_id=task.task_id,
                success=True,
                result={"plan": steps},
                metadata={"agent": "planning_agent"}
            )

        async def mock_executor(task: AgentTask) -> AgentResult:
            plan = task.payload.get("plan", [])
            executed_steps = [f"executed: {s}" for s in plan]
            return AgentResult(
                task_id=task.task_id,
                success=True,
                result={"executed": executed_steps},
                metadata={"agent": "execution_agent"}
            )

        bus.register("planning_agent", mock_planner)
        bus.register("execution_agent", mock_executor)

        # Step 1: Create Plan
        plan_task = AgentTask(
            task_id="t_plan_1",
            target_agent="planning_agent",
            task_type="create_plan",
            payload={"goal": "refactor authentication"}
        )
        plan_res = await bus.dispatch(plan_task)
        assert plan_res.success is True
        assert "write_patch" in plan_res.result["plan"]

        # Step 2: Execute Plan
        exec_task = AgentTask(
            task_id="t_exec_1",
            target_agent="execution_agent",
            task_type="execute_plan",
            payload={"plan": plan_res.result["plan"]}
        )
        exec_res = await bus.dispatch(exec_task)
        assert exec_res.success is True
        assert len(exec_res.result["executed"]) == 3
