"""
tests/unit/test_whatsapp_management_skill.py — Comprehensive test suite for the 20-Pillar Autonomous JARVIS WhatsApp Agent & Skill.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from modules.skills.whatsapp_management_skill import WhatsAppManagementSkill
from modules.skills.registry import SkillRegistry
from ai.agents.whatsapp.agent import WhatsAppAgent
from ai.agents.whatsapp.tools import WhatsAppToolRegistry
from modules.social.contact_graph import ContactGraphManager
from ai.agents.types import AgentTask, AgentResult


class TestWhatsApp20PillarAutonomousAgent:
    @pytest.mark.asyncio
    async def test_skill_registry_discovers_whatsapp_skill(self):
        """Pillar 20: Verify dynamic discovery and load of WhatsAppManagementSkill."""
        registry = SkillRegistry()
        skills = registry.load_skills()
        skill_names = [s.__class__.__name__ for s in skills]
        assert "WhatsAppManagementSkill" in skill_names

    @pytest.mark.asyncio
    async def test_permission_and_risk_matrix(self):
        """Pillar 1: Verify L0-L4 permission evaluation across Autonomy Modes."""
        agent = WhatsAppAgent()

        # SAFE mode: L0 permitted, L1-L3 require approval, L4 blocked
        agent.set_autonomy_mode("SAFE")
        assert agent.evaluate_permission("search_messages", "L0")["permitted"] is True
        assert agent.evaluate_permission("pin_chat", "L1")["requires_approval"] is True
        assert agent.evaluate_permission("send_message", "L2")["requires_approval"] is True
        assert agent.evaluate_permission("delete_account", "L4")["permitted"] is False

        # AUTONOMOUS mode: L0 & L1 permitted, L2 & L3 require approval
        agent.set_autonomy_mode("AUTONOMOUS")
        assert agent.evaluate_permission("archive_chat", "L1")["permitted"] is True
        assert agent.evaluate_permission("send_message", "L2")["requires_approval"] is True

        # EXECUTIVE mode: L0, L1, L2 permitted, L3 requires confirmation
        agent.set_autonomy_mode("EXECUTIVE")
        assert agent.evaluate_permission("send_message", "L2")["permitted"] is True
        assert agent.evaluate_permission("transfer_payment", "L3")["requires_approval"] is True
        assert agent.evaluate_permission("delete_chat", "L4")["permitted"] is False

    @pytest.mark.asyncio
    async def test_contact_disambiguation_never_guess_policy(self):
        """Pillar 4 & 9: Verify 'Never Guess' policy when multiple contacts match."""
        cg = ContactGraphManager()
        # Seed two contacts with similar names
        cg.save_contact(full_name="Rahul Verma", email="rahul.v@example.com", whatsapp_phone="+919811111111")
        cg.save_contact(full_name="Rahul Sharma", email="rahul.s@example.com", whatsapp_phone="+919822222222")

        # Resolving ambiguous 'Rahul' must STOP and require disambiguation
        res = cg.resolve_contact_with_disambiguation("Rahul")
        assert res["status"] == "disambiguation_required"
        assert len(res["candidates"]) >= 2
        assert "Multiple" in res["message"] or "Found multiple" in res["message"]

        # Exact phone lookup must resolve directly
        res_phone = cg.resolve_contact_with_disambiguation("+919811111111")
        assert res_phone["status"] == "exact"
        assert res_phone["contact"]["full_name"] == "Rahul Verma"

    @pytest.mark.asyncio
    async def test_outbound_safety_gate_secret_leak_interception(self):
        """Pillar 8: Verify 7-tier Outbound Safety Gate rejects secrets and empty recipients."""
        agent = WhatsAppAgent()

        # Missing recipient
        res1 = agent.validate_outbound_safety_gate(recipient="", text="Hello")
        assert res1["safe"] is False
        assert "Recipient" in res1["reason"]

        # Secret / API key leak attempt
        res2 = agent.validate_outbound_safety_gate(
            recipient="+919876543210",
            text="Here is your key: sk-live-1234567890abcdef1234567890"
        )
        assert res2["safe"] is False
        assert "credentials" in res2["reason"].lower() or "secret" in res2["reason"].lower()

        # Safe outbound message
        res3 = agent.validate_outbound_safety_gate(
            recipient="+919876543210",
            text="Hey Rahul, the meeting is scheduled for tomorrow at 10 AM 👍"
        )
        assert res3["safe"] is True

    @pytest.mark.asyncio
    async def test_idempotency_state_machine_transitions(self):
        """Pillar 15: Verify action state transitions through state machine."""
        action_id = "ACT-TEST-001"

        t1 = await WhatsAppToolRegistry.tool_transition_action_state({
            "action_id": action_id,
            "state": "PLANNED",
            "recipient": "+919876543210",
            "message_hash": "abc123hash"
        })
        assert t1["success"] is True

        # Transition to APPROVED
        t2 = await WhatsAppToolRegistry.tool_transition_action_state({
            "action_id": action_id,
            "state": "APPROVED",
            "recipient": "+919876543210"
        })
        assert t2["state"] == "APPROVED"

        # Check state record
        rec = await WhatsAppToolRegistry.tool_get_action_state({"action_id": action_id})
        assert rec["found"] is True
        assert rec["record"]["state"] == "APPROVED"

    @pytest.mark.asyncio
    async def test_multi_dimensional_message_intelligence(self):
        """Pillar 5: Verify multi-dimensional intelligence (Priority, Intent, Action)."""
        agent = WhatsAppAgent()

        # Critical / Support
        c1 = agent.classify_message_intelligence("server down ho gaya urgent hai please check")
        assert c1["priority"] in ("Critical", "High")
        assert c1["intent"] in ("Support", "Complaint", "Task", "Question")
        assert c1["needs_reply"] is True

        # Sales / Pricing
        c2 = agent.classify_message_intelligence("What is the price of the headphones?")
        assert c2["intent"] == "Sales"
        assert c2["priority"] in ("Medium", "Low")

        # FYI / Acknowledgment
        c3 = agent.classify_message_intelligence("ok thanks noted 👍")
        assert c3["priority"] == "FYI"
        assert c3["required_action"] == "No Action"

    @pytest.mark.asyncio
    async def test_executive_morning_briefing_2_format(self):
        """Pillar 19: Verify 9-category Executive Briefing 2.0 structure."""
        agent = WhatsAppAgent()
        briefing = await agent.generate_morning_briefing()
        assert "WhatsApp Executive Briefing" in briefing
        assert "URGENT" in briefing
        assert "NEEDS RESPONSE" in briefing
        assert "TODAY" in briefing
        assert "DRAFTS READY" in briefing

    @pytest.mark.asyncio
    async def test_audit_log_traceability(self):
        """Pillar 17: Verify audit log persistence and retrieval."""
        res = await WhatsAppToolRegistry.tool_record_audit_log({
            "action_id": "AUD-TEST-99",
            "user_request": "Send proposal to Alex",
            "intent": "send_attachment",
            "contact": "Client Alex",
            "autonomy_mode": "ASSISTED",
            "risk_level": "L2",
            "hitl_status": "approved",
            "approver": "Akshay",
            "outcome": "Sent proposal.pdf"
        })
        assert res["success"] is True

        list_res = await WhatsAppToolRegistry.tool_list_audit_logs({"limit": 5})
        assert list_res["success"] is True
        assert len(list_res["logs"]) > 0
        assert any(l["action_id"] == "AUD-TEST-99" for l in list_res["logs"])

    @pytest.mark.asyncio
    async def test_skill_autonomy_mode_and_audit_tools(self):
        """Pillar 18: Verify WhatsAppManagementSkill autonomy mode & audit tools."""
        mock_wa_agent = WhatsAppAgent()
        mock_container = MagicMock()
        mock_container.get_or_none.return_value = mock_wa_agent

        with patch("container.ServiceContainer.instance", return_value=mock_container):
            skill = WhatsAppManagementSkill()

            # Set mode
            set_res = await skill.set_whatsapp_autonomy_mode("EXECUTIVE")
            assert "EXECUTIVE" in set_res
            assert mock_wa_agent.autonomy_mode == "EXECUTIVE"

            # Get audit trail
            audit_res = await skill.get_whatsapp_audit_trail(limit=5)
            assert "WhatsApp Audit Trail" in audit_res
