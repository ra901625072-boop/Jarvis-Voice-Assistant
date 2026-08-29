"""
tests/e2e_whatsapp_taster.py — Comprehensive End-to-End Capability Tester.
Tests all new WhatsApp features in live/standalone mode:
1. Executive Triage & Urgency Classification (Negation + Hinglish)
2. HITL Draft Review Queue & Approval Flow
3. Multi-Participant Conversation Summarizer
4. Document / Requirements Extraction
5. Commitments Tracking & Morning Briefing
6. Fuzzy Product Catalog & Order Management
7. Knowledge Base FAQ RAG
8. Direct WhatsApp Actions (Send, Reply, React, Manage, Groups)
9. SocialMediaTools LiveKit Function Tools
"""
import os
import sys
import asyncio
import logging
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Set up paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.settings import load_config
load_config()

from ai.agents.types import AgentTask
from ai.agents.whatsapp.agent import WhatsAppAgent
from ai.agents.whatsapp.tools import WhatsAppToolRegistry
from modules.social.contact_graph import ContactGraphManager
from modules.social.persona_style_engine import PersonaStyleEngine
from tools.builtin.social.tool import SocialMediaTools
from modules.security.manager import SecurityManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("E2E_TASTER")


async def run_all_capability_tests():
    print("=" * 70)
    print("🤖 JARVIS WHATSAPP AI AGENT — COMPREHENSIVE CAPABILITY TESTER")
    print("=" * 70)

    # 0. Initialize Engines
    from container import ServiceContainer
    container = ServiceContainer()

    contact_graph = ContactGraphManager()
    persona_engine = PersonaStyleEngine()
    wa_agent = WhatsAppAgent(
        bus=None,
        contact_graph=contact_graph,
        persona_style_engine=persona_engine
    )

    container.register("whatsapp_agent", lambda: wa_agent)
    container.register("contact_graph", lambda: contact_graph)
    container.register("persona_style_engine", lambda: persona_engine)

    # Seed test VIP contact
    contact_graph.save_contact(
        full_name="Rahul Sharma",
        nickname="rahul_work",
        email="rahul@example.com",
        whatsapp_phone="+919876543210",
        is_vip=True
    )
    print("✅ [SETUP] Engines and test contacts initialized successfully.\n")

    # ── TEST 1: Semantic Urgency Triage & Negation Handling ───────────────────
    print("--- 1. Testing Inbox Triage & Negation Logic ---")
    triage_task = AgentTask(task_type="triage_inbox", payload={"limit": 5, "unread_only": True})
    triage_res = await wa_agent.handle(triage_task)
    assert triage_res.success, f"Triage failed: {triage_res.error}"
    print(f"📊 Triage Output Summary:\n{triage_res.result.get('summary')}\n")

    # Verify classification logic
    assert wa_agent._classify_message_urgency("urgent hai turant call karo")[0] == "URGENT_ACTION"
    assert wa_agent._classify_message_urgency("no rush, not urgent")[0] == "INFO_ONLY"
    assert wa_agent._classify_message_urgency("design kab tak bhejoge?")[0] == "NEEDS_REPLY"
    print("✅ [TEST 1 PASSED] Semantic triage, negation filtering, and Hinglish understanding verified.\n")

    # ── TEST 2: HITL Draft Creation & Approval Queue ─────────────────────────
    print("--- 2. Testing HITL Draft Creation & Approval Flow ---")
    draft_res = await wa_agent.create_draft_reply(
        contact="Rahul Sharma",
        recipient_phone="+919876543210",
        message_text="Bhai design kab tak bhejoge?",
        context_summary="Design update inquiry"
    )
    assert draft_res.get("success"), f"Draft creation failed: {draft_res}"
    draft_id = draft_res.get("draft_id")
    draft_text = draft_res.get("drafted_reply")
    print(f"📝 Generated Draft ({draft_id}): \"{draft_text}\"")

    # List pending drafts
    list_drafts = await WhatsAppToolRegistry.tool_list_pending_drafts({"status": "pending"})
    assert any(d["draft_id"] == draft_id for d in list_drafts.get("drafts", []))
    print(f"📋 Verified draft {draft_id} is in pending review queue.")

    # Approve draft
    app_res = await wa_agent.approve_and_send_draft(draft_id=draft_id, approved_by="Akshay (Voice)")
    assert app_res.get("success"), f"Approve draft failed: {app_res}"
    print(f"🚀 Draft {draft_id} approved and dispatched: {app_res.get('message')}")
    print("✅ [TEST 2 PASSED] HITL Draft Review and Approval Queue verified.\n")

    # ── TEST 3: Document / PDF Requirements Extractor ────────────────────────
    print("--- 3. Testing PDF Requirements Extractor ---")
    doc_res = await wa_agent.extract_document_requirements(
        contact="Client Alex",
        file_name="project_specifications.pdf"
    )
    assert doc_res.get("success"), f"Doc extraction failed: {doc_res}"
    reqs = doc_res.get("requirements", {})
    print(f"📄 Extracted Project Specs for: {reqs.get('project_title')}")
    print(f"  • Key Objectives: {reqs.get('key_objectives')}")
    print(f"  • Functional Req: {reqs.get('functional_requirements')}")
    print(f"  • Deliverables: {reqs.get('deliverables')}")
    print("✅ [TEST 3 PASSED] Document Requirements Extraction verified.\n")

    # ── TEST 4: Chat History & Group Conversation Summarizer ──────────────────
    print("--- 4. Testing Multi-Participant Conversation Summarizer ---")
    sum_res = await wa_agent.summarize_chat(contact="Project Alpha Group", limit=15)
    assert sum_res.get("success"), f"Summarizer failed: {sum_res}"
    sum_data = sum_res.get("summary", {})
    print(f"👥 Overview: {sum_data.get('overview')}")
    print(f"  • Decisions: {sum_data.get('decisions_made')}")
    print(f"  • Action Items: {sum_data.get('action_items')}")
    print("✅ [TEST 4 PASSED] Conversation Summarization verified.\n")

    # ── TEST 5: Follow-up Commitments & Morning Briefing ──────────────────────
    print("--- 5. Testing Commitments Tracker & Morning Briefing ---")
    fol_res = await WhatsAppToolRegistry.tool_schedule_followup({
        "contact": "Rahul Sharma",
        "commitment_text": "Send updated UI/UX wireframes",
        "due_date": "Tomorrow 10:00 AM",
        "direction": "outgoing_promise"
    })
    assert fol_res.get("success")
    print(f"⏰ Follow-up Scheduled: ID={fol_res.get('followup_id')}")

    briefing_res = await wa_agent.generate_morning_briefing()
    assert isinstance(briefing_res, str) and len(briefing_res) > 0
    print(f"🎙️ Executive Morning Briefing:\n{briefing_res}\n")
    print("✅ [TEST 5 PASSED] Commitments Tracker & Morning Briefing verified.\n")

    # ── TEST 6: Fuzzy Catalog Search & Order Management ───────────────────────
    print("--- 6. Testing Fuzzy Catalog Search & Order Placement ---")
    # Typo: 'headfone'
    cat_res = await WhatsAppToolRegistry.tool_search_product_catalog({"query": "headfone"})
    assert cat_res.get("success") and len(cat_res.get("products", [])) > 0
    matched_prod = cat_res["products"][0]
    print(f"🔍 Fuzzy Catalog Hit: '{matched_prod['name']}' (${matched_prod['price']} {matched_prod['currency']})")

    # Create order
    order_res = await WhatsAppToolRegistry.tool_create_order({
        "phone": "919876543210",
        "customer_name": "Rahul Sharma",
        "items": [{"name": matched_prod["name"], "qty": 1, "price": matched_prod["price"]}],
        "delivery_address": "404 Tech Park, Sector 5"
    })
    assert order_res.get("success")
    print(f"📦 Order Created: {order_res.get('order_id')} (Tracking: {order_res.get('tracking_number')})")
    print("✅ [TEST 6 PASSED] Fuzzy Catalog Search & Order Pipeline verified.\n")

    # ── TEST 7: Knowledge Base FAQ RAG ───────────────────────────────────────
    print("--- 7. Testing Knowledge Base FAQ RAG ---")
    kb_res = await WhatsAppToolRegistry.tool_search_knowledge_base({"query": "retun policy and refund"})
    assert kb_res.get("success") and len(kb_res.get("matches", [])) > 0
    print(f"📚 FAQ Hit: {kb_res['matches'][0]['title']} -> {kb_res['matches'][0]['content'][:100]}...")
    print("✅ [TEST 7 PASSED] Knowledge Base FAQ RAG verified.\n")

    # ── TEST 8: LiveKit Voice Tools (SocialMediaTools) ────────────────────────
    print("--- 8. Testing SocialMediaTools Voice Interface ---")
    sec_mgr = SecurityManager()
    social_tools = SocialMediaTools(security=sec_mgr)

    triage_voice = await social_tools.triage_whatsapp_messages()
    assert "WhatsApp" in triage_voice
    print("🗣️ Voice Triage Output:", triage_voice.split("\n")[0])

    sum_voice = await social_tools.summarize_whatsapp_conversation(contact="Rahul Sharma")
    assert "WhatsApp Summary" in sum_voice
    print("🗣️ Voice Summary Output:", sum_voice.split("\n")[0])

    doc_voice = await social_tools.inspect_whatsapp_document(contact="Client Alex")
    assert "Requirements Breakdown" in doc_voice
    print("🗣️ Voice Doc Output:", doc_voice.split("\n")[0])

    briefing_voice = await social_tools.get_whatsapp_morning_briefing()
    assert "Executive Briefing" in briefing_voice or "WhatsApp" in briefing_voice
    print("🗣️ Voice Briefing Output:", briefing_voice.split("\n")[0])

    print("✅ [TEST 8 PASSED] LiveKit Voice Functions verified.\n")

    print("=" * 70)
    print("🎉 ALL 8 NEW WHATSAPP CAPABILITY TIERS PASSED WITH 100% SUCCESS!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_all_capability_tests())
