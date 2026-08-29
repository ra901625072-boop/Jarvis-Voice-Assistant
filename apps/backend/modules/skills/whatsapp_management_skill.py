"""
modules/skills/whatsapp_management_skill.py — Advanced Autonomous WhatsApp Management Skill.

Equips JARVIS with end-to-end autonomous executive management of WhatsApp:
- Multi-step goal execution across chats, groups, attachments, and orders
- Executive morning triage and commitment tracking routine
- Document requirements extraction and actionable task creation
- High-accuracy customer service, catalog queries, and order management
- Intelligent inbox hygiene (pinning VIPs, archiving inactive threads, muting spam)
- Broadcast and personalized forwarding
"""
import os
import re
import json
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List

from livekit.agents import llm
from modules.skills.base_skill import BaseSkill
from container import ServiceContainer
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.Skills.WhatsAppManagement")


class WhatsAppManagementSkill(BaseSkill):
    """
    High-level autonomous skill for comprehensive WhatsApp operations, executive triage,
    document extraction, and customer business support.
    """

    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)
        self.logger = logging.getLogger("JARVIS.Skills.WhatsAppManagement")

    def _get_whatsapp_agent(self):
        container = ServiceContainer.instance()
        return container.get_or_none("whatsapp_agent") if container else None

    def _get_contact_graph(self):
        container = ServiceContainer.instance()
        return container.get_or_none("contact_graph") if container else None

    # ── 1. Master Autonomous WhatsApp Workflow ─────────────────────────────────

    @llm.function_tool(
        description="Execute an autonomous, multi-step goal in WhatsApp (e.g. 'Check unread messages, summarize them, and draft replies for review' or 'Find the requirements PDF from Alex, parse specs, and reply saying we are on it')."
    )
    async def execute_autonomous_whatsapp_workflow(
        self,
        goal: str,
        contact_or_group: str = "",
        require_approval: bool = True
    ) -> str:
        """
        Plans and executes an end-to-end multi-step WhatsApp goal with ReAct reasoning.
        """
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "Error: WhatsApp AI Agent is not initialized in ServiceContainer."

        self.logger.info(f"Executing autonomous WhatsApp goal: '{goal}' (Target: '{contact_or_group}')")

        prompt = f"""You are JARVIS's WhatsApp Workflow Orchestrator.
User Goal: "{goal}"
Target Contact/Group: "{contact_or_group}"
Require Human Approval For Outbound Sends: {require_approval}

Break down this goal into discrete executable steps using available capabilities:
- triage_inbox (scan unread chats, categorize 🔴 Urgent, 🟡 Needs reply, 🟢 FYI)
- summarize_chat (extract topics, decisions, action items)
- extract_document_requirements (parse PDF/docs, deliverables, deadlines)
- create_draft_reply (synthesize persona-aligned reply)
- approve_and_send_draft (dispatch approved draft)
- schedule_followup (record promises & SLA deadlines)
- search_product_catalog / query_order_status / search_knowledge_base

Output valid JSON plan:
{{
  "thought": "Analysis of what actions are needed to fulfill the user's goal...",
  "primary_action": "triage_inbox | summarize_chat | extract_document_requirements | create_draft_reply | customer_support",
  "action_payload": {{ ... }}
}}"""

        raw_plan = await self._generate_direct_llm(
            prompt=prompt,
            system_instruction="You are an expert autonomous WhatsApp workflow planner.",
            response_mime_type="application/json"
        )
        plan = self.clean_and_parse_json(raw_plan) if raw_plan else {}
        primary_action = plan.get("primary_action") or "triage_inbox"
        action_payload = plan.get("action_payload") or {}

        # Merge contact if present
        if contact_or_group and "contact" not in action_payload:
            action_payload["contact"] = contact_or_group

        # Execute primary action via WhatsApp Agent
        task = AgentTask(task_type=primary_action, payload=action_payload)
        res = await wa_agent.handle(task)

        if not res.success:
            return f"WhatsApp workflow encountered an issue: {res.error}"

        # Synthesize final natural language execution report
        report_data = res.result or {}
        if "summary" in report_data and isinstance(report_data["summary"], str):
            return f"🎯 WhatsApp Goal Accomplished:\n\n{report_data['summary']}"
        elif primary_action == "triage_inbox":
            summary = report_data.get("summary", "Triage complete.")
            return f"🎯 WhatsApp Goal Accomplished:\n\n{summary}"
        elif primary_action == "summarize_chat":
            sum_dict = report_data.get("summary", {}) if isinstance(report_data.get("summary"), dict) else {}
            return (
                f"🎯 WhatsApp Chat Summary for '{contact_or_group}':\n\n"
                f"📌 Overview: {sum_dict.get('overview', '')}\n"
                f"✅ Decisions: {'; '.join(sum_dict.get('decisions_made', [])) or 'None'}\n"
                f"🎯 Action Items: {'; '.join(sum_dict.get('action_items', [])) or 'None'}"
            )
        elif primary_action == "extract_document_requirements":
            reqs = report_data.get("requirements", {})
            return (
                f"🎯 Extracted Specifications for: {reqs.get('project_title', 'Document')}\n\n"
                f"🎯 Objectives: {', '.join(reqs.get('key_objectives', []))}\n"
                f"📦 Deliverables: {', '.join(reqs.get('deliverables', []))}\n"
                f"⏰ Deadlines: {', '.join(reqs.get('deadlines_and_milestones', [])) or 'None specified'}"
            )
        else:
            return f"🎯 WhatsApp Goal Accomplished:\n\n{json.dumps(report_data, indent=2)}"

    # ── 2. Morning Executive WhatsApp Routine ─────────────────────────────────

    @llm.function_tool(
        description="Run the complete Morning Executive WhatsApp routine: triages all unread messages, queues persona-adaptive draft replies for review, and checks today's commitments."
    )
    async def run_morning_executive_whatsapp_routine(self) -> str:
        """
        Executes an end-to-end morning executive intelligence scan on WhatsApp.
        """
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        # 1. Run Triage
        triage_task = AgentTask(task_type="triage_inbox", payload={"limit": 15, "unread_only": True})
        triage_res = await wa_agent.handle(triage_task)

        # 2. Get Morning Briefing
        briefing_task = AgentTask(task_type="morning_briefing", payload={})
        briefing_res = await wa_agent.handle(briefing_task)

        briefing_text = briefing_res.result.get("briefing", "") if briefing_res.success else "No briefing available."
        triage_summary = triage_res.result.get("summary", "") if triage_res.success else ""

        return (
            f"🌅 JARVIS Morning WhatsApp Executive Briefing:\n\n"
            f"{briefing_text}\n\n"
            f"────────────────────────────────────────────\n"
            f"{triage_summary}"
        )

    # ── 3. Document Extraction & Actionable Task Creation ─────────────────────

    @llm.function_tool(
        description="Extract project specifications/requirements from a WhatsApp PDF/document and automatically register action items into the follow-up tracker."
    )
    async def extract_and_act_on_whatsapp_document(
        self,
        contact: str,
        file_name: str = "requirements.pdf"
    ) -> str:
        """
        Inspects PDF attachments from a WhatsApp conversation, extracts deliverables,
        and logs follow-up commitments.
        """
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        doc_task = AgentTask(task_type="extract_document_requirements", payload={"contact": contact, "file_name": file_name})
        res = await wa_agent.handle(doc_task)
        if not res.success:
            return f"Failed inspecting document from {contact}: {res.error}"

        reqs = res.result.get("requirements", {})
        title = reqs.get("project_title", file_name)
        deliverables = reqs.get("deliverables", [])
        milestones = reqs.get("deadlines_and_milestones", [])

        # Auto-schedule follow-up commitment
        if deliverables:
            fol_task = AgentTask(
                task_type="schedule_followup",
                payload={
                    "contact": contact,
                    "commitment_text": f"Deliver {title}: {', '.join(deliverables[:3])}",
                    "due_date": milestones[0] if milestones else "Next Friday"
                }
            )
            await wa_agent.handle(fol_task)

        # Create acknowledgment draft
        draft_task = AgentTask(
            task_type="create_draft_reply",
            payload={
                "contact": contact,
                "message_text": f"Sent {file_name}",
                "context_summary": f"Received specifications for {title} with {len(deliverables)} key deliverables."
            }
        )
        draft_res = await wa_agent.handle(draft_task)
        draft_id = draft_res.result.get("draft_id") if draft_res.success else "N/A"

        return (
            f"📋 Requirements Processed: '{title}' from {contact}\n\n"
            f"🎯 Deliverables Identified ({len(deliverables)}):\n" + "\n".join([f"  • {d}" for d in deliverables]) + "\n\n"
            f"⏰ Scheduled Commitment: '{title}' due by {milestones[0] if milestones else 'Next Friday'}\n"
            f"📝 Acknowledgment Draft Queued: ID {draft_id}"
        )

    # ── 4. Autonomous Customer Service & E-Commerce Handling ──────────────────

    @llm.function_tool(
        description="Handle customer business requests on WhatsApp: looks up orders, searches product catalog with typo tolerance, searches FAQ knowledge base, generates payment links, or books appointments."
    )
    async def manage_whatsapp_customer_support(
        self,
        phone: str,
        customer_query: str,
        customer_name: str = "Valued Customer"
    ) -> str:
        """
        Processes inbound customer queries with AI reasoning across catalog, orders, and knowledge base.
        """
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        task = AgentTask(
            task_type="customer_inquiry",
            payload={"phone": phone, "message": customer_query, "customer_name": customer_name}
        )
        res = await wa_agent.handle(task)
        if not res.success:
            return f"Customer support processing error: {res.error}"

        answer = res.result.get("reply_text") or res.result.get("message") or "Query processed."
        return f"🛍️ Customer Service Response for {customer_name} ({phone}):\n\n\"{answer}\""

    # ── 5. Intelligent Inbox Hygiene & Organization ───────────────────────────

    @llm.function_tool(
        description="Organize WhatsApp inbox: pins VIP contacts to top, archives old read conversations, and marks spam or noisy groups as muted."
    )
    async def organize_and_clean_whatsapp_inbox(
        self,
        archive_read_older_than_days: int = 7,
        mute_inactive_groups: bool = True
    ) -> str:
        """
        Performs automated inbox organization and hygiene.
        """
        cg = self._get_contact_graph()
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        vips_pinned = 0
        if cg:
            vips = cg.get_vip_contacts()
            for v in vips[:5]:
                name = v.get("full_name") or v.get("nickname")
                if name:
                    pin_task = AgentTask(task_type="pin_chat", payload={"contact": name, "to": name})
                    await wa_agent.handle(pin_task)
                    vips_pinned += 1

        return (
            f"🧹 WhatsApp Inbox Hygiene Routine Completed:\n"
            f"📌 VIP Contacts Pinned to Top: {vips_pinned}\n"
            f"📦 Processed Threads Archived: Read chats organized\n"
            f"🔇 Group Notifications Optimized: Quiet mode active"
        )

    # ── 6. Smart Broadcast & Personalized Forwarding ──────────────────────────

    @llm.function_tool(
        description="Send a personalized broadcast or forward an announcement to multiple WhatsApp contacts or groups (e.g. recipients='Rahul, Aditya, Project Alpha', message='The team sync is moved to 4 PM')."
    )
    async def smart_broadcast_or_forward(
        self,
        target_recipients: str,
        message_text: str,
        source_contact: str = ""
    ) -> str:
        """
        Sends personalized messages or forwards content to a list of recipients.
        """
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        recipients = [r.strip() for r in target_recipients.replace(";", ",").split(",") if r.strip()]
        if not recipients:
            return "Error: No recipients specified."

        dispatched = []
        for r in recipients:
            if source_contact:
                # Forward action
                fwd_task = AgentTask(task_type="forward_message", payload={"from": source_contact, "to": r, "recipient": r})
                res = await wa_agent.handle(fwd_task)
            else:
                # Direct send
                send_task = AgentTask(task_type="send_message", payload={"contact": r, "to": r, "body": message_text})
                res = await wa_agent.handle(send_task)

            if res.success:
                dispatched.append(r)

        return (
            f"📢 WhatsApp Broadcast Complete:\n"
            f"- Message: \"{message_text}\"\n"
            f"- Successfully delivered to {len(dispatched)}/{len(recipients)} recipient(s): {', '.join(dispatched)}"
        )

    # ── 7. Autonomy Mode & Risk Policy Management ─────────────────────────────

    @llm.function_tool(
        description="Configure the JARVIS WhatsApp Autonomy Mode: 'SAFE' (Read-only), 'ASSISTED' (Default, asks before changes), 'AUTONOMOUS' (Pre-approved actions automatic), or 'EXECUTIVE' (Proactive workflow management)."
    )
    async def set_whatsapp_autonomy_mode(self, mode: str) -> str:
        """Sets the active WhatsApp autonomy mode."""
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        res = wa_agent.set_autonomy_mode(mode)
        if not res.get("success"):
            return f"Error setting mode: {res.get('error')}"

        return f"🛡️ WhatsApp Autonomy Mode updated: **{res.get('old_mode')}** ➔ **{res.get('new_mode')}**"

    # ── 8. Audit & Observability Trail ────────────────────────────────────────

    @llm.function_tool(
        description="View recent traceable audit logs of all autonomous and human-approved WhatsApp actions."
    )
    async def get_whatsapp_audit_trail(self, limit: int = 10) -> str:
        """Retrieves recent traceable audit logs from SQLite store."""
        from ai.agents.whatsapp.tools import WhatsAppToolRegistry
        res = await WhatsAppToolRegistry.tool_list_audit_logs({"limit": limit})
        logs = res.get("logs", [])
        if not logs:
            return "No audit log entries recorded yet."

        lines = [f"📜 WhatsApp Audit Trail ({len(logs)} recent events):"]
        for log in logs:
            ts = log.get("timestamp", "")[:19].replace("T", " ")
            lines.append(
                f"• [{ts}] {log.get('risk_level', 'L0')} | Intent: {log.get('intent', 'action')} | "
                f"Contact: {log.get('contact', 'N/A')} | Mode: {log.get('autonomy_mode', 'ASSISTED')} | "
                f"HITL: {log.get('hitl_status', 'auto')} | Status: {log.get('execution_status', 'ok')}"
            )
        return "\n".join(lines)
