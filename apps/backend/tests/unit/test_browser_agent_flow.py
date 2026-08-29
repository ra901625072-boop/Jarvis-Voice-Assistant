"""
tests/unit/test_browser_agent_flow.py — Unit Tests for Autonomous BrowserAgent and StateMachine closed-loop execution.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from modules.browser.controller import BrowserController
from modules.browser.actions.vocabulary import BrowserActionType
from ai.agents.browser.state_machine import BrowserStateMachine
from ai.agents.browser.agent import BrowserAgent
from ai.contracts import AgentTask


class TestBrowserAgentFlow:
    @pytest.mark.anyio
    async def test_state_machine_successful_flow(self):
        mock_controller = MagicMock()
        mock_controller._ensure_driver = AsyncMock()
        
        mock_page = AsyncMock()
        mock_page.url = "https://www.nasa.gov"
        mock_page.title = AsyncMock(return_value="NASA - Science and Exploration")
        mock_page.is_closed = MagicMock(return_value=False)
        mock_controller.get_or_create_content_page = AsyncMock(return_value=mock_page)

        # Mock perception
        mock_obs = MagicMock()
        mock_obs.url = "https://www.nasa.gov"
        mock_obs.title = "NASA - Science and Exploration"
        mock_obs.interactive_elements = []
        mock_obs.a11y_tree = []
        mock_obs.to_prompt_context = MagicMock(return_value="=== BROWSER STATE ===")
        mock_controller.perception_engine.observe = AsyncMock(return_value=mock_obs)
        mock_controller.tab_manager.get_tab = MagicMock(return_value=None)

        # Mock action executor
        mock_exec_res = MagicMock()
        mock_exec_res.success = True
        mock_exec_res.message = "Goal satisfied"
        mock_controller.action_executor.execute = AsyncMock(return_value=mock_exec_res)

        # Mock LLM sequence: Step 1 = click research, Step 2 = completed
        responses = [
            json.dumps({"action": "click", "target": "role=link[name='Missions']", "reason": "Navigate to missions"}),
            json.dumps({"action": "completed", "reason": "Found required mission details"}),
        ]
        
        async def mock_llm_gen(prompt, mime_type=None):
            return responses.pop(0) if responses else json.dumps({"action": "completed", "reason": "Done"})

        state_machine = BrowserStateMachine(
            controller=mock_controller,
            llm_generator=mock_llm_gen,
        )

        result = await state_machine.run(
            objective="Find NASA missions",
            initial_url="https://www.nasa.gov",
            max_steps=5,
            task_id="task_research_01",
        )

        assert result.success is True
        assert result.total_steps == 2
        assert len(result.history) >= 2
        assert result.history[-1].action == "completed"

    @pytest.mark.anyio
    async def test_browser_agent_message_bus_handler(self):
        mock_bus = MagicMock()
        mock_bus.register = MagicMock()

        agent = BrowserAgent(bus=mock_bus)
        assert mock_bus.register.called

        # Mock automate_web_flow execution
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.total_steps = 1
        mock_result.final_url = "https://example.com"
        mock_result.final_title = "Example"
        mock_result.history = []

        with patch.object(agent.state_machine, "run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = mock_result
            
            task = AgentTask(
                task_id="t_123",
                task_type="automate_web_flow",
                payload={"url": "https://example.com", "instructions": "Read documentation"}
            )
            res = await agent.handle(task)
            
            assert res.success is True
            assert res.result["actions_run"] == 1
            mock_run.assert_awaited_once()
