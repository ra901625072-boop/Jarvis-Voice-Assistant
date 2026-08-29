"""
agent.py — Production-Grade Autonomous Gmail AI Agent (Autonomous Email Assistant).

Features:
- Autonomous Sense-Plan-Act ReAct Loop for continuous inbox triage
- Multi-dimensional Thread Synthesis (Chronological reconstruction, intent extraction)
- Threat Sentinel & Prompt Injection Sanitizer
- Context-aware Draft Synthesizer matching User Persona & ContactGraph Memory
- Meeting / Calendar Intent Extractor
- Follow-up / SLA Commitment Monitor
- 3-Tier Safety & HITL Approval Engine (Auto-execute Tier 0/1, Gate Tier 2 sending/deletions)
- Morning Executive Voice Briefing generator
"""
import os
import json
import time
import uuid
import logging
import asyncio
from typing import Dict, Any, List, Optional

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult
from ai.agents.gmail.tools import GmailToolRegistry, init_gmail_db

logger = logging.getLogger("JARVIS.GmailAgent")


class GmailAgent(BaseAgent):
    """
    Autonomous Gmail AI Agent acting as an Executive Email Assistant.
    """

    def __init__(
        self,
        bus=None,
        gmail_adapter=None,
        contact_graph=None,
        persona_style_engine=None,
        memory_manager=None,
        approval_engine=None,
        scheduler=None,
        auto_triage_enabled: bool = True
    ):
        super().__init__(agent_id="gmail_agent")
        self.bus = bus
        self.adapter = gmail_adapter
        self.contact_graph = contact_graph
        self.style_engine = persona_style_engine
        self.memory = memory_manager
        self.approval = approval_engine
        self.scheduler = scheduler
        self.auto_triage_enabled = auto_triage_enabled

        init_gmail_db()

        if self.bus:
            self.bus.register(self.agent_id, self.handle)
        logger.info("GmailAgent (Autonomous Email Assistant) initialized and registered on AgentBus.")

    async def handle(self, task: AgentTask) -> AgentResult:
        """Processes incoming AgentBus tasks."""
        task_type = task.task_type
        payload = task.payload or {}

        try:
            if task_type in ("triage_inbox", "triage_emails", "inbox_triage"):
                limit = int(payload.get("limit", 10))
                unread_only = payload.get("unread_only", True)
                auto_archive = payload.get("auto_archive_newsletters", False)
                input_emails = payload.get("emails")
                res = await self.triage_inbox(
                    limit=limit,
                    unread_only=unread_only,
                    auto_archive_newsletters=auto_archive,
                    input_emails=input_emails
                )
                return self._create_result(task, success=res.get("success", True), result=res)

            elif task_type in ("generate_draft", "draft_reply", "create_contextual_draft"):
                res = await self.create_draft_reply(
                    thread_id=payload.get("thread_id", ""),
                    recipient=payload.get("recipient") or payload.get("to", ""),
                    subject=payload.get("subject", ""),
                    body_context=payload.get("body") or payload.get("body_text", ""),
                    tone=payload.get("tone", "professional_warm"),
                    key_points=payload.get("key_points", [])
                )
                return self._create_result(task, success=res.get("success", True), result=res)

            elif task_type in ("review_drafts", "list_pending_drafts", "list_drafts"):
                status = payload.get("status", "pending")
                limit = int(payload.get("limit", 10))
                res = await GmailToolRegistry.list_pending_drafts(status=status, limit=limit)
                return self._create_result(task, success=True, result=res)

            elif task_type in ("approve_and_send_draft", "send_draft"):
                draft_id = payload.get("draft_id", "")
                approved_by = payload.get("approved_by", "user")
                bypass_approval = payload.get("bypass_approval", False)
                res = await self.approve_and_send(draft_id, approved_by=approved_by, bypass_approval=bypass_approval)
                return self._create_result(task, success=res.get("success", True), result=res)

            elif task_type in ("schedule_followup", "track_promise", "add_followup"):
                res = await GmailToolRegistry.schedule_followup_reminder(
                    thread_id=payload.get("thread_id", ""),
                    recipient=payload.get("recipient", ""),
                    promise_text=payload.get("promise_text") or payload.get("promise", ""),
                    due_date=payload.get("due_date", "In 3 days"),
                    direction=payload.get("direction", "outgoing_promise")
                )
                return self._create_result(task, success=True, result=res)

            elif task_type in ("get_analytics", "get_inbox_analytics", "get_agent_metrics"):
                res = await GmailToolRegistry.query_inbox_analytics()
                return self._create_result(task, success=True, result=res)

            elif task_type in ("morning_briefing", "generate_morning_briefing"):
                briefing = await self.generate_morning_briefing()
                return self._create_result(task, success=True, result={"briefing": briefing})

            elif task_type == "toggle_auto_triage":
                enabled = payload.get("enabled", True)
                self.auto_triage_enabled = bool(enabled)
                return self._create_result(task, success=True, result={"auto_triage_enabled": self.auto_triage_enabled})

            elif task_type == "security_scan":
                res = await GmailToolRegistry.security_scan_email(payload)
                return self._create_result(task, success=True, result=res)

            else:
                return self._create_result(
                    task,
                    success=False,
                    error=f"GmailAgent does not support task type '{task_type}'"
                )

        except Exception as e:
            logger.exception(f"GmailAgent error handling '{task_type}': {e}")
            return self._create_result(task, success=False, error=str(e))

    async def triage_inbox(
        self,
        limit: int = 10,
        unread_only: bool = True,
        auto_archive_newsletters: bool = False,
        input_emails: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Runs autonomous triage across inbox emails:
        1. Ingestion & Security Sentinel Scan
        2. Categorization & Urgency Scoring
        3. Calendar Meeting Extraction
        4. Auto-Drafting of replies for review
        5. Rule-based Archival of marketing/newsletters
        """
        emails = input_emails
        if emails is None and self.adapter:
            action = "get_unread_emails" if unread_only else "read_inbox"
            adapter_res = await self.adapter.execute(action, {"limit": limit})
            if adapter_res.get("success"):
                emails = adapter_res.get("messages", [])
            else:
                logger.warning(f"Gmail adapter returned non-success during triage: {adapter_res.get('error')}")
                emails = []

        if emails is None:
            emails = []

        processed_threads = []
        drafts_generated = []
        meetings_extracted = []
        archived_count = 0
        quarantined_count = 0

        for em in emails:
            triage_res = await GmailToolRegistry.classify_and_triage_thread(em)
            thread_id = triage_res.get("thread_id")
            category = triage_res.get("category")
            action_state = triage_res.get("action_state")
            is_quarantined = triage_res.get("is_quarantined")

            processed_threads.append(triage_res)

            if is_quarantined:
                quarantined_count += 1
                continue

            if action_state in ("calendar_and_reply", "meeting_invite") or "meeting" in em.get("subject", "").lower():
                body_text = em.get("body_text") or em.get("body") or em.get("snippet", "")
                cal_res = await GmailToolRegistry.extract_calendar_event(
                    thread_id=thread_id,
                    text=body_text,
                    sender=em.get("from") or em.get("sender", ""),
                    subject=em.get("subject", "")
                )
                meetings_extracted.append(cal_res)

            if action_state in ("reply_needed", "priority_reply_needed", "calendar_and_reply"):
                recipient = em.get("from") or em.get("sender", "")
                body_text = em.get("body_text") or em.get("body") or em.get("snippet", "")
                
                tone = "professional_warm"
                if self.contact_graph and recipient:
                    c_info = self.contact_graph.resolve_contact(recipient)
                    if c_info and c_info.get("relationship") == "vip":
                        tone = "executive_concise"

                draft_res = await GmailToolRegistry.generate_contextual_draft(
                    thread_id=thread_id,
                    recipient=recipient,
                    subject=em.get("subject", ""),
                    context_body=body_text,
                    tone=tone
                )
                drafts_generated.append(draft_res)

            if auto_archive_newsletters and category == "Newsletter_Marketing" and self.adapter:
                msg_id = em.get("id") or em.get("message_id")
                if msg_id:
                    await self.adapter.execute("archive_email", {"message_id": msg_id})
                    archived_count += 1

        analytics = await GmailToolRegistry.query_inbox_analytics()

        return {
            "success": True,
            "scanned_count": len(emails),
            "processed_threads": processed_threads,
            "drafts_generated": drafts_generated,
            "meetings_extracted": meetings_extracted,
            "archived_count": archived_count,
            "quarantined_count": quarantined_count,
            "analytics": analytics
        }

    async def create_draft_reply(
        self,
        thread_id: str,
        recipient: str,
        subject: str,
        body_context: str,
        tone: str = "professional_warm",
        key_points: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Direct programmatic generation of a draft reply."""
        if self.contact_graph and recipient:
            c = self.contact_graph.resolve_contact(recipient)
            if c:
                recipient = c.get("email") or recipient

        return await GmailToolRegistry.generate_contextual_draft(
            thread_id=thread_id or str(uuid.uuid4()),
            recipient=recipient,
            subject=subject,
            context_body=body_context,
            tone=tone,
            key_points=key_points
        )

    async def approve_and_send(
        self,
        draft_id: str,
        approved_by: str = "user",
        bypass_approval: bool = False
    ) -> Dict[str, Any]:
        """
        Approves a draft in the queue and dispatches it via GmailAdapter (Tier 2 Action).
        """
        app_res = await GmailToolRegistry.approve_and_send_draft(draft_id, approved_by=approved_by)
        if not app_res.get("success"):
            return app_res

        draft = app_res.get("draft", {})
        recipient = draft.get("recipient", "")
        subject = draft.get("subject", "")
        body = draft.get("body", "")

        auto_approve = (
            os.environ.get("JARVIS_AUTO_APPROVE_SOCIAL", "false").lower() == "true"
            or os.environ.get("JARVIS_AUTO_APPROVE", "false").lower() == "true"
            or bypass_approval
        )

        if not auto_approve and self.approval:
            authorized = await self.approval.authorize(
                tool_name="gmail_agent",
                method_name="send_email",
                params={"draft_id": draft_id, "to": recipient, "subject": subject, "body": body},
                task_id=f"send_draft_{draft_id}",
                agent_id="gmail_agent"
            )
            if not authorized:
                return {
                    "success": False,
                    "error": f"Dispatch for draft '{draft_id}' was rejected or timed out awaiting human approval."
                }

        dispatch_success = True
        dispatch_error = None
        if self.adapter:
            exec_res = await self.adapter.execute("send_email", {
                "to": recipient,
                "subject": subject,
                "body": body
            })
            dispatch_success = exec_res.get("success", False)
            dispatch_error = exec_res.get("error")

        return {
            "success": dispatch_success,
            "draft_id": draft_id,
            "recipient": recipient,
            "subject": subject,
            "dispatched": dispatch_success,
            "error": dispatch_error
        }

    async def generate_morning_briefing(self) -> str:
        """
        Generates executive voice and text briefing summarizing inbox health, VIP emails, and drafts.
        """
        analytics = await GmailToolRegistry.query_inbox_analytics()
        pending = await GmailToolRegistry.list_pending_drafts(limit=5)
        drafts = pending.get("drafts", [])

        lines = [
            f"Good morning! Your inbox scan is complete.",
            f"Total indexed threads: {analytics.get('total_threads_indexed', 0)}.",
            f"Urgent / VIP items: {analytics.get('urgent_threads_count', 0)}.",
            f"Extracted meetings: {analytics.get('extracted_meetings_count', 0)}."
        ]

        if drafts:
            lines.append(f"You have {len(drafts)} draft reply ready for review:")
            for d in drafts:
                lines.append(f"- To: {d.get('recipient')} | Subject: '{d.get('subject')}'")
        else:
            lines.append("No pending draft replies in queue.")

        return "\n".join(lines)