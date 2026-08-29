"""
tests/e2e/test_failure_recovery_e2e.py — End-to-end failure recovery & replanning.
"""
import asyncio
import pytest
from modules.bus.redis_bus import RedisBus
from ai.contracts import AgentTask, AgentResult


class TestFailureRecoveryE2E:
    @pytest.mark.asyncio
    async def test_agent_failure_and_recovery_loop(self):
        """Simulated step failure invokes Recovery Agent to produce a viable alternative."""
        bus = RedisBus()
        attempts = 0

        async def fragile_browser_agent(task: AgentTask) -> AgentResult:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return AgentResult(
                    task_id=task.task_id,
                    success=False,
                    error="Timeout waiting for selector '#download-button'",
                    error_category="selector_timeout"
                )
            return AgentResult(
                task_id=task.task_id,
                success=True,
                result={"content": "Downloaded data successfully via fallback selector"}
            )

        async def recovery_agent(task: AgentTask) -> AgentResult:
            failed_error = task.payload.get("error", "")
            return AgentResult(
                task_id=task.task_id,
                success=True,
                result={"action": "retry_with_fallback_selector", "strategy": "xpath"}
            )

        bus.register("browser_agent", fragile_browser_agent)
        bus.register("recovery_agent", recovery_agent)

        # Step 1: Initial Attempt fails
        task1 = AgentTask(task_id="t_flow_1", target_agent="browser_agent", task_type="scrape_page")
        res1 = await bus.dispatch(task1)
        assert res1.success is False

        # Step 2: Recovery analysis
        rec_task = AgentTask(
            task_id="t_rec_1",
            target_agent="recovery_agent",
            task_type="recover_failure",
            payload={"error": res1.error}
        )
        rec_res = await bus.dispatch(rec_task)
        assert rec_res.success is True
        assert rec_res.result["action"] == "retry_with_fallback_selector"

        # Step 3: Retrying with strategy succeeds
        retry_task = AgentTask(task_id="t_flow_2", target_agent="browser_agent", task_type="scrape_page")
        retry_res = await bus.dispatch(retry_task)
        assert retry_res.success is True
        assert "Downloaded data successfully" in retry_res.result["content"]
