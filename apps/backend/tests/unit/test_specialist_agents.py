"""
tests/unit/test_specialist_agents.py — Unit test suite for JARVIS specialist agents.
"""
import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from modules.bus.redis_bus import RedisBus
from ai.contracts import AgentTask, AgentResult

from ai.agents.language.agent import LanguageAgent
from ai.agents.research.agent import DeepResearchAgent
from ai.agents.learning.agent import LearningAgent
from ai.agents.memory.agent import MemoryAgent
from ai.agents.ui_ux.agent import UIUXDesignerAgent
from ai.agents.integration.agent import IntegrationAgent
from ai.agents.interaction.agent import InteractionAgent, GroundedActionSchema
from ai.agents.vision.agent import VisionAgent, VisionTaskTypes
from modules.skills.file_discovery_agent import FileDiscoveryAgent
from modules.social.watcher_service import SocialWatcherService
from ai.agents.voice.voice_listener import VoiceListenerPipeline
from ai.agents.social_media.agent import SocialMediaAgent


class TestLanguageAgent:
    @pytest.mark.asyncio
    async def test_language_detection_and_translation(self, memory_manager):
        bus = RedisBus()
        agent = LanguageAgent(bus, memory=memory_manager)

        # Health check
        hc_res = await agent.handle(AgentTask(task_type="health_check"))
        assert hc_res.success is True

        # Detect English
        detect_task = AgentTask(
            task_type="detect_language",
            target_agent="language_agent",
            payload={"text": "Hello, how are you today?"}
        )
        det_res = await agent.handle(detect_task)
        assert det_res.success is True
        assert det_res.result["code"] == "en"

        # Translate
        with patch.object(agent.translation_service, "translate") as mock_trans:
            mock_trans_res = MagicMock()
            mock_trans_res.to_dict.return_value = {"translated_text": "नमस्ते"}
            mock_trans.return_value = mock_trans_res
            trans_task = AgentTask(
                task_type="translate_text",
                target_agent="language_agent",
                payload={"text": "Hello", "target_lang": "hi"}
            )
            trans_res = await agent.handle(trans_task)
            assert trans_res.success is True
            assert trans_res.result["translated_text"] == "नमस्ते"


class TestDeepResearchAgent:
    @pytest.mark.asyncio
    async def test_research_lifecycle_and_intent(self):
        bus = RedisBus()
        mock_mem_agent = MagicMock()
        mock_mem_agent.memory = None
        agent = DeepResearchAgent(mock_mem_agent, bus)

        # Health check
        hc_res = await agent.handle(AgentTask(task_type="health_check"))
        assert hc_res.success is True

        # Intent Analysis
        intent_res = await agent.analyze_intent("Tell me about quantum computing architecture")
        assert intent_res["query"] == "Tell me about quantum computing architecture"
        assert intent_res["need_internet"] is True

        # Research Planner
        search_plan = await agent.plan_research("Tell me about quantum computing", "general")
        assert len(search_plan) >= 2


class TestLearningAgent:
    @pytest.mark.asyncio
    async def test_learning_agent_tasks(self, memory_manager):
        bus = RedisBus()
        agent = LearningAgent(bus, memory=memory_manager)

        # Health check
        hc_res = await agent.handle(AgentTask(task_type="health_check"))
        assert hc_res.success is True

        # Analyze outcome
        outcome_task = AgentTask(
            task_type="analyze_outcome",
            target_agent="learning_agent",
            payload={
                "agent_id": "coding_agent",
                "task_type": "write_code",
                "task_id": "t123",
                "success": True,
                "duration_ms": 120.0
            }
        )
        res = await agent.handle(outcome_task)
        assert res.success is True

        # Render dashboard
        dash_task = AgentTask(
            task_type="render_learning_dashboard",
            target_agent="learning_agent",
            payload={}
        )
        dash_res = await agent.handle(dash_task)
        assert dash_res.success is True


class TestMemoryAgent:
    @pytest.mark.asyncio
    async def test_memory_retrieval_and_storage(self, memory_manager):
        bus = RedisBus()
        agent = MemoryAgent(memory_manager, bus)

        # Health check
        hc_res = await agent.handle(AgentTask(task_type="health_check"))
        assert hc_res.success is True

        # Retrieve context
        task = AgentTask(
            task_type="retrieve_context",
            target_agent="memory_agent",
            payload={"goal": "deploy app"}
        )
        res = await agent.handle(task)
        assert res.success is True
        assert "context" in res.result


class TestUIUXDesignerAgent:
    @pytest.mark.asyncio
    async def test_ui_ux_contrast_and_tokens(self, memory_manager):
        bus = RedisBus()
        agent = UIUXDesignerAgent(bus, memory=memory_manager)

        # Health check
        hc_res = await agent.handle(AgentTask(task_type="health_check"))
        assert hc_res.success is True

        # Calculate contrast
        contrast_task = AgentTask(
            task_type="calculate_contrast",
            target_agent="ui_ux_agent",
            payload={"foreground": "#000000", "background": "#FFFFFF"}
        )
        res = await agent.handle(contrast_task)
        assert res.success is True
        assert "21.00:1" in str(res.result["metrics"]["contrast_ratio"])

        # Export tokens
        tokens_task = AgentTask(
            task_type="export_tokens",
            target_agent="ui_ux_agent",
            payload={"format": "css", "tokens": {"primary": "#3B82F6"}}
        )
        tok_res = await agent.handle(tokens_task)
        assert tok_res.success is True


class TestIntegrationAgent:
    @pytest.mark.asyncio
    async def test_integration_agent_tasks(self):
        bus = RedisBus()
        agent = IntegrationAgent(bus)

        # Health check
        hc_res = await agent.handle(AgentTask(task_type="health_check"))
        assert hc_res.success is True

        # SSRF blocked test
        api_task = AgentTask(
            task_type="call_api",
            target_agent="integration_agent",
            payload={"service": "cloud", "endpoint": "http://169.254.169.254/latest/meta-data/"}
        )
        with patch.object(agent, "generate_response", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = json.dumps({
                "method": "GET",
                "url": "http://169.254.169.254/latest/meta-data/",
                "headers": {}
            })
            res = await agent.handle(api_task)
            # SSRF should block cloud metadata endpoint
            assert res.success is False
            assert "SSRF" in res.error or "blocked" in res.error.lower()


class TestInteractionAgent:
    @pytest.mark.asyncio
    async def test_grounded_action_schema(self):
        # Click action
        c = GroundedActionSchema.validate_and_normalize({"action": "click", "args": {"x": 100, "y": 200}})
        assert c["action"] == "click"
        assert c["args"]["x"] == 100

        # Scroll action
        s = GroundedActionSchema.validate_and_normalize({"action": "scroll", "args": {"amount": -300}})
        assert s["action"] == "scroll"
        assert s["args"]["amount"] == -300

        # Done action
        d = GroundedActionSchema.validate_and_normalize({"action": "done", "args": {"success": True, "summary": "Finished"}})
        assert d["action"] == "done"
        assert d["args"]["success"] is True

        # Invalid action
        with pytest.raises(ValueError):
            GroundedActionSchema.validate_and_normalize({"action": "invalid_action", "args": {}})


class TestVisionAgent:
    @pytest.mark.asyncio
    async def test_vision_bbox_and_center_conversion(self):
        bus = RedisBus()
        mock_vm = MagicMock()
        agent = VisionAgent(mock_vm, bus)

        # Health check
        hc_res = await agent.handle(AgentTask(task_type="health_check"))
        assert hc_res.success is True

        # Bbox conversion: ymin, xmin, ymax, xmax (0-1000) inside 1920x1080 window
        bbox = [100, 200, 300, 400]
        window_rect = [0, 0, 1000, 1000]
        abs_bbox = agent._to_abs_bbox(bbox, window_rect)
        assert abs_bbox == [200, 100, 200, 200]

        # Center conversion
        center = [500, 500]
        abs_center = agent._to_abs_center(center, window_rect)
        assert abs_center == [500, 500]


class TestFileDiscoveryAgent:
    def test_file_discovery_init_and_methods(self, tmp_path):
        mock_fm = MagicMock()
        mock_fm.learning_engine = None
        mock_se = MagicMock()
        agent = FileDiscoveryAgent(mock_fm, None, mock_se)
        assert agent is not None


class TestSocialWatcher:
    @pytest.mark.asyncio
    async def test_social_watcher_status(self):
        mock_sm = MagicMock()
        mock_cg = MagicMock()
        watcher = SocialWatcherService(social_media_agent=mock_sm, contact_graph=mock_cg)
        assert watcher is not None


class TestVoiceListenerPipeline:
    @pytest.mark.asyncio
    async def test_voice_listener_queueing(self):
        pipeline = VoiceListenerPipeline.get_instance()
        assert pipeline is not None
        await pipeline.push_transcript("jarvis open browser", is_final=True)
        # Should successfully accept transcript into input queue
        assert not pipeline._input_queue.empty()
        item = await pipeline._input_queue.get()
        assert item == "jarvis open browser"


class TestSocialMediaAgent:
    @pytest.mark.asyncio
    async def test_social_media_routing(self):
        bus = RedisBus()
        agent = SocialMediaAgent(bus=bus)

        # Health check
        hc_res = await agent.handle(AgentTask(task_type="health_check"))
        assert hc_res.success is True

        # Check specialist mapping table
        assert agent.SPECIALIST_TASK_MAP.get("process_inbound_message") == "whatsapp_agent"
        assert agent.SPECIALIST_TASK_MAP.get("triage_inbox") == "gmail_agent"
        assert agent.SPECIALIST_TASK_MAP.get("research_trends") == "instagram_agent"
