"""
tests/e2e/test_agent_workflow_e2e.py — End-to-end multi-agent execution workflow.
"""
import asyncio
import pytest
from modules.bus.redis_bus import RedisBus
from modules.execution.unified_task_registry import UnifiedTaskRegistry, TaskStatus
from ai.contracts import AgentTask, AgentResult


class TestAgentWorkflowE2E:
    @pytest.mark.asyncio
    async def test_full_pipeline_dispatch_and_recording(self, tmp_path):
        """End-to-end task: Dispatch via Bus -> Agent processes -> TaskRegistry updates state."""
        db_path = str(tmp_path / "e2e_tasks.db")
        registry = UnifiedTaskRegistry(db_path=db_path)
        bus = RedisBus()

        # Specialist handler
        async def mock_coding_agent(task: AgentTask) -> AgentResult:
            code_snippet = "print('Hello from autonomous coding agent')"
            # Update registry progress
            registry.update_status(task.task_id, status=TaskStatus.RUNNING, progress=50)
            return AgentResult(
                task_id=task.task_id,
                success=True,
                result={"code": code_snippet},
                duration_ms=45.0
            )

        bus.register("coding_agent", mock_coding_agent)

        # 1. User submits task -> Created in Registry
        task_id = registry.create_task(
            task_type="refactor_code",
            description="Generate greeting script"
        )
        assert registry.get_task(task_id).status == TaskStatus.QUEUED

        # 2. Orchestrator dispatches task onto the bus
        agent_task = AgentTask(
            task_id=task_id,
            target_agent="coding_agent",
            task_type="refactor_code",
            payload={"filename": "greet.py"}
        )
        result = await bus.dispatch(agent_task)

        # 3. Finalize registry status
        if result.success:
            registry.update_status(task_id, status=TaskStatus.COMPLETED, progress=100, result=str(result.result))
        else:
            registry.update_status(task_id, status=TaskStatus.FAILED, error=result.error)

        # 4. Verify end-to-end outcome
        final_record = registry.get_task(task_id)
        assert final_record.status == TaskStatus.COMPLETED
        assert final_record.progress == 100
        assert "Hello from autonomous coding agent" in final_record.result

        registry.shutdown()
