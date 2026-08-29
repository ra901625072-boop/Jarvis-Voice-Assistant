"""
tests/unit/test_base_skill_bus.py — Unit tests for BaseSkill container lookup and Groq 404 fallback.
"""
import pytest
from unittest.mock import MagicMock, patch
from modules.skills.base_skill import BaseSkill
from ai.agents.base_agent import BaseAgent
from container import ServiceContainer


class ConcreteSkill(BaseSkill):
    pass


class TestBaseSkillAndAgentFixes:
    def test_get_agent_bus_imports_container(self):
        """Verify _get_agent_bus retrieves AgentBus from ServiceContainer without NameError."""
        container = ServiceContainer()
        ServiceContainer._instance = container
        mock_bus = MagicMock()
        container._services["agent_bus"] = mock_bus
        container._factories["agent_bus"] = lambda: mock_bus

        skill = ConcreteSkill()
        bus = skill._get_agent_bus()
        assert bus == mock_bus

    @pytest.mark.asyncio
    async def test_groq_404_tries_fallback_model(self):
        """Verify 404 response on one Groq model tries next model and does not block provider for 10 min."""
        class DummyAgent(BaseAgent):
            async def handle(self, task):
                return self._create_result(task, success=True)

        agent = DummyAgent("test_agent")

        # Mock httpx response 404 for first call and 200 for second call
        res_404 = MagicMock()
        res_404.status_code = 404
        res_404.text = "Model not found"

        res_200 = MagicMock()
        res_200.status_code = 200
        res_200.json.return_value = {"choices": [{"message": {"content": "response"}}]}

        with patch.dict("os.environ", {"GROQ_API_KEY": "fake_key"}):
            with patch("httpx.AsyncClient.post", side_effect=[res_404, res_200]):
                res = await agent._generate_direct_llm("hello")
                assert res == "response"
                # Provider should not be marked failed
                assert BaseAgent._failed_provider_until.get("groq", 0.0) < 1.0
