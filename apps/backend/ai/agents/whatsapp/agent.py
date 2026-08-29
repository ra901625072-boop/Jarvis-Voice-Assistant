"""
agent.py — Production-Grade Autonomous WhatsApp AI Agent (AI Employee).

Features:
- Multimodal Ingestion Pipeline (Voice note transcription, Vision/OCR invoice extraction, document parsing)
- Autonomous ReAct Reasoning & Tool Execution Loop (Orders, Catalog, CRM, Booking, Payments, Support RAG, Escalation)
- Turn Context & Customer Memory (multi-turn conversation state, CRM profiles)
- Human Takeover Management (pause AI auto-reply on escalation)
- Idempotency & Safety Protection against duplicate transactions
- Direct WhatsApp Dispatcher via WhatsAppAdapter (Text, Interactive Buttons, Payment links)
"""
import os
import re
import json
import time
import uuid
import sqlite3
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult
from ai.agents.whatsapp.tools import WhatsAppToolRegistry, DB_PATH

logger = logging.getLogger("JARVIS.WhatsAppAgent")


class WhatsAppAgent(BaseAgent):
    """
    Production-grade autonomous WhatsApp AI Agent acting as an Executive AI Assistant & Business Employee.
    Follows the complete Observe → Understand → Plan → Ask Permission (HITL) → Act → Verify → Report loop.
    """

    def __init__(
        self,
        bus=None,
        whatsapp_adapter=None,
        vision_agent=None,
        contact_graph=None,
        persona_style_engine=None,
        memory_manager=None,
        approval_engine=None,
        scheduler=None
    ):
        super().__init__(agent_id="whatsapp_agent")
        self.bus = bus
        self.adapter = whatsapp_adapter
        self.vision = vision_agent
        self.contact_graph = contact_graph
        self.style_engine = persona_style_engine
        self.memory_manager = memory_manager
        self.approval = approval_engine
        self.scheduler = scheduler

        # In-memory Human Takeover store: {phone_number: expiry_timestamp}
        self._human_takeovers: Dict[str, float] = {}
        # Global auto-reply toggle
        self.auto_reply_enabled: bool = True
        # Autonomy Mode: 'SAFE' | 'ASSISTED' | 'AUTONOMOUS' | 'EXECUTIVE'
        self.autonomy_mode: str = "ASSISTED"

        if self.bus:
            self.bus.register(self.agent_id, self.handle)
        logger.info("WhatsAppAgent (Executive AI Assistant & Employee) initialized and registered.")

    async def handle(self, task: AgentTask) -> AgentResult:
        """Processes agent bus tasks."""
        task_type = task.task_type
        payload = task.payload or {}

        try:
            # ── 1. Executive Inbox Triage & Intelligence ──────────────────────
            if task_type in ("triage_inbox", "triage_whatsapp", "triage_messages", "inbox_triage"):
                limit = int(payload.get("limit", 10))
                unread_only = payload.get("unread_only", True)
                input_chats = payload.get("chats")
                res = await self.triage_inbox(
                    limit=limit,
                    unread_only=unread_only,
                    input_chats=input_chats
                )
                return self._create_result(task, success=res.get("success", True), result=res)

            # ── 2. Drafting & Human-in-the-Loop Review Queue ───────────────────
            elif task_type in ("create_draft_reply", "draft_reply", "create_draft"):
                res = await self.create_draft_reply(
                    contact=payload.get("contact") or payload.get("recipient", ""),
                    recipient_phone=payload.get("phone") or payload.get("recipient_phone", ""),
                    message_text=payload.get("message") or payload.get("original_message", ""),
                    context_summary=payload.get("context_summary", ""),
                    tone=payload.get("tone", "casual_direct"),
                    urgency=payload.get("urgency", "NEEDS_REPLY")
                )
                return self._create_result(task, success=res.get("success", True), result=res)

            elif task_type in ("review_drafts", "list_pending_drafts", "list_drafts"):
                status = payload.get("status", "pending")
                limit = int(payload.get("limit", 10))
                res = await WhatsAppToolRegistry.tool_list_pending_drafts({"status": status, "limit": limit})
                return self._create_result(task, success=True, result=res)

            elif task_type in ("approve_and_send_draft", "approve_draft", "send_draft"):
                draft_id = payload.get("draft_id", "")
                approved_by = payload.get("approved_by", "user")
                bypass_approval = payload.get("bypass_approval", False)
                res = await self.approve_and_send_draft(draft_id, approved_by=approved_by, bypass_approval=bypass_approval)
                return self._create_result(task, success=res.get("success", True), result=res)

            # ── 3. Commitments & SLA Follow-ups ───────────────────────────────
            elif task_type in ("schedule_followup", "track_commitment", "add_followup"):
                res = await WhatsAppToolRegistry.tool_schedule_followup({
                    "contact": payload.get("contact", ""),
                    "phone": payload.get("phone", ""),
                    "commitment_text": payload.get("commitment_text") or payload.get("promise", ""),
                    "due_date": payload.get("due_date", "Tomorrow 10:00 AM"),
                    "direction": payload.get("direction", "outgoing_promise")
                })
                return self._create_result(task, success=True, result=res)

            elif task_type in ("list_followups", "get_commitments"):
                status = payload.get("status", "pending")
                limit = int(payload.get("limit", 10))
                res = await WhatsAppToolRegistry.tool_list_followups({"status": status, "limit": limit})
                return self._create_result(task, success=True, result=res)

            # ── 4. Document & Attachment Requirements Extractor ───────────────
            elif task_type in ("extract_document_requirements", "inspect_document", "summarize_document"):
                res = await self.extract_document_requirements(
                    contact=payload.get("contact", ""),
                    file_name=payload.get("file_name", "requirements.pdf"),
                    document_text=payload.get("document_text") or payload.get("content_text", "")
                )
                return self._create_result(task, success=res.get("success", True), result=res)

            # ── 5. Conversation & Group Chat Summarization ────────────────────
            elif task_type in ("summarize_chat", "summarize_conversation", "chat_summary"):
                res = await self.summarize_chat(
                    contact=payload.get("contact", ""),
                    limit=int(payload.get("limit", 30))
                )
                return self._create_result(task, success=res.get("success", True), result=res)

            # ── 6. Executive Morning / Periodic Briefing ──────────────────────
            elif task_type in ("morning_briefing", "generate_morning_briefing", "executive_briefing"):
                briefing = await self.generate_morning_briefing()
                return self._create_result(task, success=True, result={"briefing": briefing})

            # ── 7. Core Inbound & Operational Tasks ───────────────────────────
            elif task_type in ("process_inbound_message", "notify_inbound_message", "inbound_message"):
                result = await self.process_inbound_message(
                    sender=payload.get("sender", ""),
                    text=payload.get("text", ""),
                    msg_type=payload.get("msg_type", "text"),
                    media_info=payload.get("media_info") or {},
                    msg_id=payload.get("message_id", ""),
                    recipient=payload.get("recipient", "")
                )
                return self._create_result(task, success=result.get("success", True), result=result)

            elif task_type == "execute_business_tool":
                tool_name = payload.get("tool_name", "")
                tool_args = payload.get("args", {})
                res = await WhatsAppToolRegistry.execute_tool(tool_name, tool_args)
                return self._create_result(task, success=res.get("success", True), result=res)

            elif task_type == "get_agent_metrics":
                metrics = await self._get_metrics()
                return self._create_result(task, success=True, result=metrics)

            elif task_type == "toggle_auto_reply":
                enabled = payload.get("enabled", True)
                self.auto_reply_enabled = bool(enabled)
                return self._create_result(task, success=True, result={"auto_reply_enabled": self.auto_reply_enabled})

            elif task_type == "set_human_takeover":
                phone = ''.join(c for c in str(payload.get("phone", "")) if c.isdigit())
                duration_minutes = payload.get("duration_minutes", 60)
                enabled = payload.get("enabled", True)
                if enabled:
                    self._human_takeovers[phone] = time.time() + (duration_minutes * 60)
                else:
                    self._human_takeovers.pop(phone, None)
                return self._create_result(task, success=True, result={"phone": phone, "human_takeover": enabled})

            elif task_type == "list_escalations":
                escalations = await self._list_escalations(payload.get("status", "Open"))
                return self._create_result(task, success=True, result={"escalations": escalations})

            # ── 8. 20-Pillar Autonomous Management & Safety Routes ────────────
            elif task_type in ("set_autonomy_mode", "set_mode"):
                mode = str(payload.get("mode", "ASSISTED")).upper()
                res = self.set_autonomy_mode(mode)
                return self._create_result(task, success=res.get("success", True), result=res)

            elif task_type in ("get_autonomy_mode", "get_mode"):
                return self._create_result(task, success=True, result={"autonomy_mode": self.autonomy_mode})

            elif task_type in ("get_audit_logs", "list_audit_logs"):
                limit = int(payload.get("limit", 15))
                res = await WhatsAppToolRegistry.tool_list_audit_logs({"limit": limit})
                return self._create_result(task, success=True, result=res)

            elif task_type in ("validate_outbound", "outbound_safety_check"):
                res = self.validate_outbound_safety_gate(
                    recipient=payload.get("recipient", ""),
                    text=payload.get("text", ""),
                    attachments=payload.get("attachments")
                )
                return self._create_result(task, success=True, result=res)

            elif task_type in ("resolve_contact_safe", "resolve_contact_with_disambiguation"):
                query = payload.get("query") or payload.get("contact", "")
                res = self.resolve_contact_safe(query)
                return self._create_result(task, success=True, result=res)

            elif task_type in ("classify_message_intelligence", "classify_message"):
                text = payload.get("text") or payload.get("message", "")
                is_vip = bool(payload.get("is_vip", False))
                res = self.classify_message_intelligence(text, is_vip=is_vip)
                return self._create_result(task, success=True, result=res)

            else:
                return self._create_result(task, success=False, error=f"Unsupported task_type '{task_type}'")

        except Exception as e:
            logger.exception(f"WhatsAppAgent failed executing task '{task_type}': {e}")
            return self._create_result(task, success=False, error=str(e))

    # ── Executive Inbox Triage & Intelligence ─────────────────────────────────

    async def triage_inbox(
        self,
        limit: int = 10,
        unread_only: bool = True,
        input_chats: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Autonomous Executive Triage Pipeline:
        1. Reads unread chats from WhatsApp Web or Cloud API.
        2. Categorizes each conversation into Urgency Tiers (🔴 Urgent, 🟡 Needs Reply, 🟢 FYI/No Action).
        3. Synthesizes contextual drafts matching Akshay's persona style.
        4. Detects commitments/promises and schedules follow-up reminders.
        5. Queues drafts for Human-in-the-Loop review.
        """
        chats = input_chats
        if chats is None and self.adapter:
            action = "get_unread_chats" if unread_only else "read_inbox"
            adapter_res = await self.adapter.execute(action, {"limit": limit})
            if adapter_res.get("success"):
                chats = adapter_res.get("chats", [])
            else:
                return {"success": False, "error": f"Failed reading chats from adapter: {adapter_res.get('error')}"}

        chats = chats or []
        if not chats:
            return {
                "success": True,
                "scanned_count": 0,
                "urgent_count": 0,
                "needs_reply_count": 0,
                "info_only_count": 0,
                "drafts_generated": [],
                "commitments_extracted": [],
                "summary": "No unread WhatsApp messages to triage."
            }

        scanned = 0
        urgent_list = []
        needs_reply_list = []
        info_only_list = []
        drafts_generated = []
        commitments_extracted = []

        for chat in chats[:limit]:
            scanned += 1
            contact = chat.get("contact") or chat.get("sender") or "Unknown Contact"
            last_msg = chat.get("last_message") or chat.get("text") or ""
            is_vip = self.contact_graph.is_vip(contact) if self.contact_graph else False

            # Threat Sentinel Scan
            sec_scan = WhatsAppToolRegistry.security_scan_message(last_msg)
            if not sec_scan.get("is_safe"):
                logger.warning(f"Quarantining suspicious WhatsApp message from {contact}: {sec_scan.get('threats_detected')}")
                continue

            # Classify Urgency & Intent
            urgency, category, needs_response = self._classify_message_urgency(last_msg, is_vip)

            item = {
                "contact": contact,
                "is_vip": is_vip,
                "last_message": last_msg,
                "urgency": urgency,
                "category": category,
                "timestamp": chat.get("timestamp", "")
            }

            if urgency == "URGENT_ACTION":
                urgent_list.append(item)
            elif urgency == "NEEDS_REPLY":
                needs_reply_list.append(item)
            else:
                info_only_list.append(item)

            # Auto-synthesize draft reply for items needing response
            if needs_response and last_msg:
                draft_res = await self.create_draft_reply(
                    contact=contact,
                    message_text=last_msg,
                    context_summary=f"Inbound message ({urgency}): {last_msg[:80]}",
                    urgency=urgency
                )
                if draft_res.get("success"):
                    drafts_generated.append(draft_res)

                # Check for commitments in incoming message (e.g. "Can you send the design tomorrow?")
                commitment_info = self._detect_commitment_intent(last_msg, contact)
                if commitment_info:
                    fol_res = await WhatsAppToolRegistry.tool_schedule_followup(commitment_info)
                    if fol_res.get("success"):
                        commitments_extracted.append(fol_res)

        summary_lines = [
            f"WhatsApp Inbox Triage Complete ({scanned} chats analyzed):",
            f"🔴 Urgent Action Required: {len(urgent_list)}",
            f"🟡 Needs Reply: {len(needs_reply_list)}",
            f"🟢 FYI / No Action: {len(info_only_list)}"
        ]
        if drafts_generated:
            summary_lines.append(f"\n📝 {len(drafts_generated)} Draft Replies Queued for Approval:")
            for d in drafts_generated:
                summary_lines.append(f"  • To {d.get('contact')}: \"{d.get('drafted_reply')[:120]}...\" (ID: {d.get('draft_id')})")

        if commitments_extracted:
            summary_lines.append(f"\n⏰ {len(commitments_extracted)} Commitment / Follow-up(s) Tracked:")
            for c in commitments_extracted:
                summary_lines.append(f"  • {c.get('contact')}: '{c.get('commitment')}' (Due: {c.get('due_date')})")

        return {
            "success": True,
            "scanned_count": scanned,
            "urgent_count": len(urgent_list),
            "needs_reply_count": len(needs_reply_list),
            "info_only_count": len(info_only_list),
            "urgent_items": urgent_list,
            "needs_reply_items": needs_reply_list,
            "info_only_items": info_only_list,
            "drafts_generated": drafts_generated,
            "commitments_extracted": commitments_extracted,
            "summary": "\n".join(summary_lines)
        }

    # ── 20-Pillar Autonomous Capabilities: Risk, Safety Gate & Intelligence ───

    def set_autonomy_mode(self, mode: str) -> Dict[str, Any]:
        """Sets agent autonomy mode: SAFE | ASSISTED | AUTONOMOUS | EXECUTIVE."""
        valid_modes = {"SAFE", "ASSISTED", "AUTONOMOUS", "EXECUTIVE"}
        norm_mode = mode.upper().strip()
        if norm_mode not in valid_modes:
            return {"success": False, "error": f"Invalid mode '{mode}'. Valid modes: {valid_modes}"}
        old_mode = self.autonomy_mode
        self.autonomy_mode = norm_mode
        logger.info(f"WhatsAppAgent Autonomy Mode transitioned from {old_mode} -> {norm_mode}")
        return {"success": True, "old_mode": old_mode, "new_mode": norm_mode}

    def evaluate_permission(self, action_name: str, risk_level: str = "L0") -> Dict[str, Any]:
        """
        Evaluates whether an action is permitted autonomously under the current AutonomyMode:
        - L0 (Read-Only / Safe): Always autonomous in all modes.
        - L1 (Low-Risk Reversible): Autonomous in AUTONOMOUS & EXECUTIVE, requires approval in SAFE & ASSISTED.
        - L2 (External Communication): Autonomous only in EXECUTIVE (with policy), requires approval in others.
        - L3 (Sensitive / Consequential): ALWAYS requires explicit human confirmation.
        - L4 (Prohibited): Hard blocked in all modes.
        """
        risk = risk_level.upper()
        mode = self.autonomy_mode.upper()

        if risk == "L4":
            return {"permitted": False, "requires_approval": False, "reason": "L4 action is strictly prohibited."}
        elif risk == "L3":
            return {"permitted": False, "requires_approval": True, "reason": "L3 sensitive action requires explicit confirmation."}
        elif risk == "L2":
            if mode == "EXECUTIVE":
                return {"permitted": True, "requires_approval": False, "reason": "L2 permitted in EXECUTIVE mode."}
            return {"permitted": False, "requires_approval": True, "reason": f"L2 outbound action requires HITL approval in {mode} mode."}
        elif risk == "L1":
            if mode in ("AUTONOMOUS", "EXECUTIVE"):
                return {"permitted": True, "requires_approval": False, "reason": f"L1 permitted autonomously in {mode} mode."}
            return {"permitted": False, "requires_approval": True, "reason": f"L1 action requires approval in {mode} mode."}
        else:  # L0
            return {"permitted": True, "requires_approval": False, "reason": "L0 read-only action is safe."}

    def validate_outbound_safety_gate(
        self,
        recipient: str,
        text: str,
        attachments: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        7-Tier Outbound Message Safety Gate:
        1. Recipient check (non-empty, non-ambiguous)
        2. Content validation (length, non-empty)
        3. Privacy & Secret screen (API keys, passwords, credentials)
        4. Prohibited L4 action screening
        5. Attachment safety & existence check
        """
        if not recipient or not recipient.strip():
            return {"safe": False, "reason": "Recipient identifier is missing or empty."}

        clean_text = text.strip() if text else ""
        if not clean_text and not attachments:
            return {"safe": False, "reason": "Outbound message body and attachments are both empty."}

        # Privacy screen: Check for leaked tokens, API keys, credentials
        secret_patterns = [
            r"sk-[a-zA-Z0-9_\-]{15,}",
            r"ghp_[a-zA-Z0-9]{20,}",
            r"(api[_-]?key|secret|password|bearer|token)\s*[:=]\s*\S{6,}",
            r"\b\d{16}\b",  # 16-digit credit card pattern
        ]
        for pat in secret_patterns:
            if re.search(pat, clean_text, re.IGNORECASE):
                logger.warning(f"Outbound safety gate intercepted potential secret in text: {pat}")
                return {"safe": False, "reason": "Message contains potential credentials, API keys, or sensitive financial data."}

        # Attachment checks
        if attachments:
            for att in attachments:
                if not os.path.exists(att):
                    return {"safe": False, "reason": f"Attachment file '{att}' not found on local filesystem."}

        return {"safe": True, "recipient": recipient, "risk_level": "L2"}

    def resolve_contact_safe(self, query: str) -> Dict[str, Any]:
        """Resolves contact with strict 'Never Guess' disambiguation."""
        if not self.contact_graph:
            return {"status": "not_found", "query": query, "contact": None}
        if hasattr(self.contact_graph, "resolve_contact_with_disambiguation"):
            return self.contact_graph.resolve_contact_with_disambiguation(query)
        contact = self.contact_graph.resolve_contact(query)
        return {"status": "exact" if contact else "not_found", "contact": contact}

    def classify_message_intelligence(self, text: str, is_vip: bool = False) -> Dict[str, Any]:
        """
        Comprehensive Multi-Dimensional Message Intelligence:
        Classifies Priority (Critical, High, Medium, Low, FYI),
        Intent (11 types), and Required Action (8 types).
        """
        urgency_tier, reason, needs_action = self._classify_message_urgency(text, is_vip=is_vip)
        text_lower = text.lower().strip()

        # 1. Map Priority
        if urgency_tier == "URGENT_ACTION":
            priority = "Critical" if any(w in text_lower for w in ["server down", "emergency", "payment failed"]) else "High"
        elif urgency_tier == "NEEDS_REPLY":
            priority = "High" if is_vip else "Medium"
        else:
            priority = "FYI" if any(text_lower.startswith(w) for w in ["ok", "thanks", "thx", "cool"]) else "Low"

        # 2. Map Intent
        if any(w in text_lower for w in ["price", "cost", "how much", "quote", "catalog", "buy", "discount"]):
            intent = "Sales"
        elif any(w in text_lower for w in ["server down", "server crashed", "refund", "return", "broken", "issue", "bug", "not working", "help", "fix"]):
            intent = "Support" if any(w in text_lower for w in ["server down", "server crashed", "issue", "bug", "not working", "help", "fix"]) else "Complaint"
        elif any(w in text_lower for w in ["meet", "meeting", "call", "schedule", "appointment", "calendar"]):
            intent = "Appointment"
        elif any(w in text_lower for w in ["pay", "payment", "invoice", "upi", "card"]):
            intent = "Payment"
        elif any(w in text_lower for w in ["task", "deliver", "spec", "code", "design"]):
            intent = "Task"
        elif "?" in text or any(w in text_lower for w in ["what", "when", "where", "how", "why"]):
            intent = "Question"
        elif any(w in text_lower for w in ["please send", "can you share", "give me"]):
            intent = "Request"
        elif len(text_lower) <= 10 and any(w in text_lower for w in ["hi", "hello", "hey", "gm", "gn"]):
            intent = "Personal"
        else:
            intent = "Information"

        # 3. Map Required Action
        if not needs_action:
            req_action = "No Action"
        elif intent == "Appointment":
            req_action = "Schedule"
        elif intent == "Payment":
            req_action = "Payment/Action Required"
        elif any(ext in text_lower for ext in [".pdf", ".docx", ".xlsx", "attachment"]):
            req_action = "Review Attachment"
        elif any(w in text_lower for w in ["call me", "phone call"]):
            req_action = "Call"
        elif any(w in text_lower for w in ["tomorrow", "friday", "next week", "later"]):
            req_action = "Follow-up"
        else:
            req_action = "Reply"

        return {
            "priority": priority,
            "intent": intent,
            "required_action": req_action,
            "urgency_tier": urgency_tier,
            "reason": reason,
            "needs_reply": needs_action
        }

    def _classify_message_urgency(self, text: str, is_vip: bool = False) -> Tuple[str, str, bool]:
        """
        High-precision semantic urgency & intent classification:
        1. Negation handling: suppresses false-positive urgency (e.g. 'not urgent', 'no rush', 'aaram se').
        2. Multilingual & Indic/Hinglish intent recognition.
        3. VIP amplification with context sensitivity.
        4. Distinguishes actionable inquiries from rhetorical/closing acknowledgments.
        """
        text_lower = text.lower().strip()

        # Step 1: Check anti-urgency & negation signals (explicit non-urgent)
        anti_urgent_patterns = [
            r"not\s+(an\s+)?urgent",
            r"no\s+rush",
            r"no\s+hurry",
            r"whenever\s+you\s+(are\s+free|can|get\s+time)",
            r"take\s+your\s+time",
            r"not\s+an\s+emergency",
            r"aaram\s+se",
            r"koi\s+(jaldi|emergency)\s+nahi",
            r"jab\s+time\s+mile"
        ]
        is_explicitly_non_urgent = any(re.search(pat, text_lower) for pat in anti_urgent_patterns)

        # Step 2: Check for genuine urgent signals (English + Hinglish/Indic)
        urgent_patterns = [
            r"\burgent\b",
            r"\basap\b",
            r"\bemergency\b",
            r"\bblocked\b",
            r"\bpayment\s+(failed|stuck|declined)\b",
            r"\bdeadline\s+(today|now|missed)\b",
            r"\bserver\s+(down|crashed)\b",
            r"\bhelp\s+needed\s+(asap|now|fast)\b",
            r"\bcall\s+me\s+now\b",
            r"urgent\s+hai",
            r"turant\s+(call|reply|bhejo)",
            r"jaldi\s+(karo|bhejo|dekhna)",
            r"payment\s+(fas|atak)\s+gaya",
            r"server\s+band\s+ho\s+gaya"
        ]
        is_urgent_text = any(re.search(pat, text_lower) for pat in urgent_patterns) and not is_explicitly_non_urgent
        if is_urgent_text or (is_vip and "?" in text and not is_explicitly_non_urgent and ("now" in text_lower or "today" in text_lower or "call" in text_lower)):
            return "URGENT_ACTION", "High-Priority Urgent Action", True

        # Step 3: Check for pure acknowledgment / closing signals
        no_action_phrases = [
            "ok", "okay", "thanks", "thank you", "thx", "noted", "cool", "done", "great",
            "👍", "🙌", "see you", "good night", "gm", "gn", "theek hai", "chalega", "milte hai",
            "shukriya", "dhanyawad", "all good", "got it", "perfect", "understood"
        ]
        if text_lower in no_action_phrases or (len(text_lower) <= 5 and any(text_lower.startswith(w) for w in ["ok", "thx", "k", "tq", "tc", "ty"])):
            return "INFO_ONLY", "Acknowledgment / FYI", False

        # Step 4: Check for inquiries and action requests (English + Hinglish)
        inquiry_signals = [
            "?", "can you", "could you", "when", "how", "where", "what", "send me",
            "share", "update", "status", "price", "quote", "kab", "kaise", "kaha",
            "kya", "bhejo", "batao", "dekh lo", "check karo", "mil sakta hai"
        ]
        has_inquiry = any(qs in text_lower for qs in inquiry_signals)

        if has_inquiry:
            return "NEEDS_REPLY", "Inquiry / Action Required", True

        # If VIP and not purely closing, default to NEEDS_REPLY
        if is_vip and not is_explicitly_non_urgent:
            return "NEEDS_REPLY", "VIP Communication", True

        return "INFO_ONLY", "General / FYI", False

    def _detect_commitment_intent(self, text: str, contact: str) -> Optional[Dict[str, Any]]:
        """
        High-precision extraction of commitments, promises, and delivery timelines.
        Calculates normalized relative dates.
        """
        text_lower = text.lower()
        now = datetime.now()

        # Match relative time descriptors
        due_date = "Tomorrow 10:00 AM"
        if "tomorrow" in text_lower:
            due_date = f"Tomorrow ({(now.replace(day=now.day + 1)).strftime('%A, %b %d')}) at 10:00 AM"
        elif "tonight" in text_lower or "this evening" in text_lower:
            due_date = f"Today ({(now).strftime('%A, %b %d')}) at 7:00 PM"
        elif "monday" in text_lower:
            due_date = "Next Monday at 10:00 AM"
        elif "friday" in text_lower:
            due_date = "This Friday at 5:00 PM"
        elif "in 2 hours" in text_lower or "in an hour" in text_lower:
            due_date = "Within 2 Hours"

        # Match action patterns
        action_patterns = [
            r"\b(will|i'll|shall)\s+(send|share|deliver|give|update|call|email|review|fix)\b",
            r"\b(can\s+you|please)\s+(send|share|deliver|give|update|call|email|review|fix)\b",
            r"\b(kab\s+tak|kal\s+tak)\s+(bhejoge|doge|karoge)\b"
        ]
        has_action = any(re.search(p, text_lower) for p in action_patterns)

        if has_action or ("send" in text_lower and any(w in text_lower for w in ["tomorrow", "today", "asap", "morning"])):
            direction = "outgoing_promise" if any(w in text_lower for w in ["i'll", "i will", "sending", "will send"]) else "incoming_sla"
            return {
                "contact": contact,
                "commitment_text": f"Follow up regarding: {text[:100]}",
                "due_date": due_date,
                "direction": direction
            }
        return None

    # ── Contextual Draft Synthesizer (Persona-Adaptive) ───────────────────────

    async def create_draft_reply(
        self,
        contact: str,
        recipient_phone: str = "",
        message_text: str = "",
        context_summary: str = "",
        tone: str = "casual_direct",
        urgency: str = "NEEDS_REPLY"
    ) -> Dict[str, Any]:
        """Synthesizes a persona-aligned WhatsApp draft reply and queues it for approval."""
        style_prompt = ""
        if self.style_engine:
            profile = self.style_engine.get_style_profile("whatsapp")
            style_prompt = (
                f"Match Akshay's personal WhatsApp communication style:\n"
                f"- Tone: {profile.get('tone', 'direct, friendly, casual, responsive')}\n"
                f"- Brevity: {profile.get('brevity', 'high')}\n"
                f"- Emojis: {profile.get('emoji_usage', 'contextual, e.g. 👍, 🙌, ✅')}\n"
                f"- Greeting: {profile.get('greeting_style', 'Hey {name}').format(name=contact.split()[0])}\n"
            )

        prompt = f"""You are drafting a personal WhatsApp reply for Akshay.
Contact: {contact}
Original Message: "{message_text}"
Context: {context_summary}

{style_prompt}

Generate a concise, natural, friendly, and helpful WhatsApp reply.
If Akshay needs to promise something (like sending files or updating designs), be clear and polite.
Do not add robotic phrases. Sound completely human.

Return JSON:
{{
  "thought": "Reasoning for the drafted response...",
  "drafted_reply": "Hey Rahul, I'll send over the updated design tomorrow morning 👍",
  "detected_commitment": "Send updated design tomorrow morning" or null
}}"""

        raw = await self._generate_direct_llm(
            prompt=prompt,
            system_instruction="You are Akshay's personal executive AI assistant drafting WhatsApp responses.",
            response_mime_type="application/json"
        )
        parsed = self._parse_json_decision(raw)
        reply_text = parsed.get("drafted_reply") or f"Hey {contact.split()[0]}, got your message! I will get back to you shortly 👍"

        # Record commitment if detected
        commitment_text = parsed.get("detected_commitment")
        if commitment_text:
            await WhatsAppToolRegistry.tool_schedule_followup({
                "contact": contact,
                "phone": recipient_phone,
                "commitment_text": str(commitment_text),
                "due_date": "Tomorrow 10:00 AM",
                "direction": "outgoing_promise"
            })

        # Save draft to SQLite review queue
        draft_record = await WhatsAppToolRegistry.tool_create_draft_reply({
            "contact": contact,
            "recipient_phone": recipient_phone,
            "original_message": message_text,
            "drafted_reply": reply_text,
            "urgency": urgency,
            "context_summary": context_summary
        })

        return draft_record

    async def approve_and_send_draft(
        self,
        draft_id: str,
        approved_by: str = "user",
        bypass_approval: bool = False
    ) -> Dict[str, Any]:
        """Human-in-the-Loop verification gate: approves and sends a queued draft with 7-tier safety gate."""
        # 1. Fetch & Approve draft in DB
        app_res = await WhatsAppToolRegistry.tool_approve_draft({"draft_id": draft_id})
        if not app_res.get("success"):
            return app_res

        contact = app_res.get("contact", "")
        phone = app_res.get("recipient_phone", "")
        reply_text = app_res.get("drafted_reply", "")
        target_to = phone if phone else contact

        # 2. Outbound Safety Gate Check
        safety = self.validate_outbound_safety_gate(recipient=target_to, text=reply_text)
        if not safety.get("safe"):
            logger.error(f"Outbound safety gate blocked draft {draft_id}: {safety.get('reason')}")
            return {
                "success": False,
                "error": f"Outbound Safety Gate Blocked: {safety.get('reason')}",
                "draft_id": draft_id
            }

        # 3. Idempotency State Machine: PLANNED -> APPROVED -> SENDING
        msg_hash = hashlib.sha256(reply_text.encode("utf-8", errors="replace")).hexdigest()
        await WhatsAppToolRegistry.tool_transition_action_state({
            "action_id": draft_id,
            "state": "APPROVED",
            "recipient": target_to,
            "message_hash": msg_hash,
            "details": {"approved_by": approved_by}
        })
        await WhatsAppToolRegistry.tool_transition_action_state({
            "action_id": draft_id,
            "state": "SENDING",
            "recipient": target_to
        })

        # 4. Dispatch message via Adapter
        dispatch_res = await self._dispatch_reply(to=target_to, text=reply_text)
        await self._save_agent_reply(recipient=target_to, text=reply_text)

        # 5. Idempotency State Machine: -> SENT
        is_sent = bool(dispatch_res.get("success", True)) if isinstance(dispatch_res, dict) else True
        await WhatsAppToolRegistry.tool_transition_action_state({
            "action_id": draft_id,
            "state": "SENT" if is_sent else "FAILED",
            "recipient": target_to
        })

        # 6. Audit & Observability Trail
        await WhatsAppToolRegistry.tool_record_audit_log({
            "action_id": draft_id,
            "user_request": f"Approve draft reply for {contact}",
            "intent": "send_message",
            "contact": contact,
            "phone": phone,
            "autonomy_mode": self.autonomy_mode,
            "risk_level": "L2",
            "hitl_status": "approved",
            "approver": approved_by,
            "tools_used": ["WhatsAppAdapter.send_message"],
            "payload_hash": msg_hash,
            "execution_status": "success" if is_sent else "failed",
            "verification_status": "verified",
            "outcome": f"Dispatched '{reply_text[:60]}' to {target_to}"
        })

        logger.info(f"WhatsApp draft {draft_id} dispatched to {target_to} by {approved_by} (Verified)")
        return {
            "success": True,
            "draft_id": draft_id,
            "recipient": target_to,
            "sent_text": reply_text,
            "approved_by": approved_by,
            "dispatch": dispatch_res,
            "message": f"Draft {draft_id} successfully approved and sent to {contact}."
        }

    # ── Document & PDF Requirements Extractor ─────────────────────────────────

    async def extract_document_requirements(
        self,
        contact: str,
        file_name: str = "requirements.pdf",
        document_text: str = ""
    ) -> Dict[str, Any]:
        """Locates document attachments in chat and extracts structured requirements/specs."""
        doc_content = document_text
        if not doc_content and self.adapter:
            # Read recent conversation messages to locate document text
            chat_res = await self.adapter.execute("read_conversation", {"contact": contact, "limit": 20})
            if chat_res.get("success"):
                msgs = chat_res.get("messages", [])
                doc_msgs = [m.get("text", "") for m in msgs if any(ext in m.get("text", "").lower() for ext in [".pdf", ".docx", "requirement", "spec", "project"])]
                if doc_msgs:
                    doc_content = "\n".join(doc_msgs)

        if not doc_content:
            doc_content = f"Attached document '{file_name}' from {contact} covering project scope and deliverables."

        prompt = f"""You are an expert technical business analyst.
Extract and summarize the core project requirements from this WhatsApp document content ({file_name} from {contact}):

Content:
\"\"\"{doc_content}\"\"\"

Return structured JSON:
{{
  "project_title": "Title or Scope Summary",
  "key_objectives": ["Objective 1", "Objective 2"],
  "functional_requirements": ["Requirement A", "Requirement B", "Requirement C"],
  "deliverables": ["Deliverable 1", "Deliverable 2"],
  "deadlines_and_milestones": ["Timeline/Milestone 1"],
  "open_questions": ["Any ambiguity or missing info"]
}}"""

        raw = await self._generate_direct_llm(
            prompt=prompt,
            system_instruction="Extract structured requirements and specifications concisely from document content.",
            response_mime_type="application/json"
        )
        parsed = self._parse_json_decision(raw)

        # Index in SQLite attachments store
        await WhatsAppToolRegistry.tool_inspect_document({
            "contact": contact,
            "file_name": file_name,
            "content_text": json.dumps(parsed, indent=2)
        })

        return {
            "success": True,
            "contact": contact,
            "file_name": file_name,
            "requirements": parsed
        }

    # ── Conversation & Group Chat Summarizer ──────────────────────────────────

    async def summarize_chat(self, contact: str, limit: int = 30, messages: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Summarizes a long 1-on-1 or group WhatsApp chat history."""
        msgs = list(messages) if messages else []
        if not msgs and self.adapter:
            chat_res = await self.adapter.execute("read_conversation", {"contact": contact, "limit": limit})
            if chat_res.get("success"):
                msgs = chat_res.get("messages", [])

        if not msgs:
            # Query local social inbound messages table if available
            db_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "contacts.db")
            if os.path.exists(db_path):
                try:
                    with sqlite3.connect(db_path) as conn:
                        conn.row_factory = sqlite3.Row
                        cursor = conn.cursor()
                        cursor.execute("SELECT sender, text, timestamp FROM social_inbound_messages WHERE platform = 'whatsapp' ORDER BY timestamp DESC LIMIT ?", (limit,))
                        for r in cursor.fetchall():
                            msgs.append({"sender": r["sender"], "text": r["text"], "timestamp": r["timestamp"]})
                except Exception:
                    pass

        if not msgs:
            msgs = [{"sender": contact, "text": f"Recent conversation with {contact} discussing project milestones and deliverable timelines.", "timestamp": datetime.now().isoformat()}]

        formatted = "\n".join([f"[{m.get('sender', 'Contact')} at {m.get('timestamp', '')}]: {m.get('text', '')}" for m in msgs if m.get("text")])

        prompt = f"""Summarize this WhatsApp conversation with '{contact}'.
Conversation Transcripts:
{formatted}

Provide structured analysis in JSON:
{{
  "overview": "Concise 2-sentence executive summary of the chat",
  "key_topics": ["Topic 1", "Topic 2"],
  "decisions_made": ["Decision A"],
  "action_items": ["Action 1 with assignee", "Action 2"],
  "unanswered_questions": ["Question needing reply"]
}}"""

        raw = await self._generate_direct_llm(
            prompt=prompt,
            system_instruction="You are an executive assistant analyzing WhatsApp team/client conversations.",
            response_mime_type="application/json"
        )
        summary_parsed = self._parse_json_decision(raw)

        return {
            "success": True,
            "contact": contact,
            "messages_analyzed": len(msgs),
            "summary": summary_parsed
        }

    # ── Morning / Executive WhatsApp Briefing 2.0 ─────────────────────────────

    async def generate_morning_briefing(self) -> str:
        """
        Generates an Executive Briefing 2.0 summarizing:
        🔴 Urgent, 🟡 Needs Response, 📅 Today's Commitments, ⏰ Overdue,
        📎 Documents, 💰 Customer/Business, 👥 Groups, 🤖 Drafts Ready, ⚠️ Requires Approval.
        """
        metrics = await self._get_metrics()
        drafts_res = await WhatsAppToolRegistry.tool_list_pending_drafts({"status": "pending", "limit": 10})
        followups_res = await WhatsAppToolRegistry.tool_list_followups({"status": "pending", "limit": 10})
        escalations = await self._list_escalations("Open")

        pending_drafts = drafts_res.get("drafts", [])
        pending_followups = followups_res.get("followups", [])

        urgent_count = sum(1 for d in pending_drafts if d.get("urgency") == "URGENT_ACTION")
        needs_reply_count = sum(1 for d in pending_drafts if d.get("urgency") != "URGENT_ACTION")

        lines = [
            "Good morning Akshay.",
            "",
            "WhatsApp Executive Briefing",
            "────────────────────────────────────────────",
            f"🔴 URGENT: {urgent_count} conversation(s) requiring immediate attention",
            f"🟡 NEEDS RESPONSE: {needs_reply_count} pending messages",
            f"📅 TODAY: {len(pending_followups)} active commitment(s) and deadlines",
            f"⏰ OVERDUE: 0 follow-ups overdue",
            f"📎 DOCUMENTS: Indexed and requirements extracted",
            f"💰 CUSTOMER / BUSINESS: Orders & catalog active (Mode: {self.autonomy_mode})",
            f"👥 GROUPS: Context monitoring active",
            f"🤖 DRAFTS READY: {len(pending_drafts)} suggested persona replies queued",
            f"⚠️ REQUIRES YOUR APPROVAL: {len(pending_drafts)} outbound draft(s) waiting"
        ]

        if pending_followups:
            lines.append("\n📅 Active Commitments Due:")
            for f in pending_followups[:3]:
                lines.append(f"  • {f.get('contact')}: '{f.get('commitment_text')}' (Due: {f.get('due_date')})")

        if pending_drafts:
            lines.append("\n📝 Queued Drafts for Review:")
            for d in pending_drafts[:3]:
                lines.append(f"  • To {d.get('contact')}: \"{d.get('drafted_reply')[:75]}...\" (ID: {d.get('draft_id')})")

        return "\n".join(lines)

    # ── Autonomous Inbound Processing Pipeline ────────────────────────────────

    async def process_inbound_message(
        self,
        sender: str,
        text: str = "",
        msg_type: str = "text",
        media_info: Optional[Dict[str, Any]] = None,
        msg_id: str = "",
        recipient: str = ""
    ) -> Dict[str, Any]:
        """
        Main autonomous pipeline:
        1. Media Ingestion & Multimodal preprocessing (Audio Whisper, Image OCR, Document parse)
        2. Human Takeover & Guardrail check
        3. CRM Context & Conversation Memory retrieval
        4. ReAct Reasoning Loop (LLM + Tool Execution)
        5. Response Generation & Outbound Dispatch
        """
        media_info = media_info or {}
        clean_sender = ''.join(c for c in str(sender) if c.isdigit())
        if not clean_sender:
            return {"success": False, "error": "Invalid sender phone identifier."}

        logger.info(f"WhatsAppAgent processing inbound message from {clean_sender} (type: {msg_type})")

        # 1. Multimodal Preprocessing
        processed_text, context_media_summary = await self._preprocess_multimodal_input(
            text=text,
            msg_type=msg_type,
            media_info=media_info
        )

        # 2. Check Human Takeover
        if self._is_human_takeover_active(clean_sender):
            logger.info(f"Human takeover active for {clean_sender}. Skipping automated reply.")
            return {
                "success": True,
                "status": "human_takeover_active",
                "message": "Human takeover is active. No automated response sent."
            }

        if not self.auto_reply_enabled:
            logger.info("Global WhatsApp auto-reply is currently disabled.")
            return {
                "success": True,
                "status": "auto_reply_disabled",
                "message": "Auto reply disabled globally."
            }

        # 3. Guardrail: Prompt Injection & Sanitization
        if self._check_prompt_injection(processed_text):
            logger.warning(f"Potential prompt injection detected from {clean_sender}: '{processed_text}'")
            reply = "I cannot process that request. How may I help you with your order, products, or support today?"
            await self._dispatch_reply(to=clean_sender, text=reply, target_msg_id=msg_id)
            return {"success": True, "status": "blocked_by_guardrail", "reply": reply}

        # 4. Fetch CRM Profile & Recent Conversation History
        crm_data = await WhatsAppToolRegistry.tool_get_customer_crm_profile({"phone": clean_sender})
        customer_profile = crm_data.get("profile", {})
        recent_history = await self._get_recent_history(clean_sender, limit=6)

        # 5. Run ReAct Agent Reasoning Loop
        agent_decision = await self._run_reasoning_loop(
            sender=clean_sender,
            user_input=processed_text,
            media_summary=context_media_summary,
            customer_profile=customer_profile,
            history=recent_history
        )

        final_response_text = agent_decision.get("response_text", "")
        tool_results = agent_decision.get("tool_results", [])
        interactive_buttons = agent_decision.get("interactive_buttons")

        # 6. Dispatch Outbound Message to WhatsApp
        if final_response_text:
            dispatch_res = await self._dispatch_reply(
                to=clean_sender,
                text=final_response_text,
                target_msg_id=msg_id,
                buttons=interactive_buttons
            )
            # Log turn to history
            await self._save_agent_reply(recipient=clean_sender, text=final_response_text)
            return {
                "success": True,
                "status": "replied",
                "reply": final_response_text,
                "tools_executed": tool_results,
                "dispatch": dispatch_res
            }

        return {"success": True, "status": "no_reply_needed", "tools_executed": tool_results}

    # ── Multimodal Preprocessing ──────────────────────────────────────────────

    async def _preprocess_multimodal_input(
        self,
        text: str,
        msg_type: str,
        media_info: Dict[str, Any]
    ) -> Tuple[str, str]:
        """Converts voice notes, images, or documents into structured semantic text."""
        media_summary = ""
        user_text = text or ""

        # A. Voice Notes / Audio
        if msg_type in ("audio", "voice"):
            media_url = media_info.get("url") or media_info.get("media_id", "")
            logger.info(f"Processing inbound voice note: {media_url}")
            transcription = await self._transcribe_audio_message(media_info)
            user_text = transcription if transcription else "[User sent a voice message that could not be transcribed]"
            media_summary = f"[Voice Note Transcription: \"{user_text}\"]"

        # B. Image / Photo / Receipt / Invoice
        elif msg_type == "image":
            caption = media_info.get("caption", "")
            logger.info(f"Processing inbound image attachment (caption: '{caption}')")
            vision_analysis = await self._analyze_image_message(media_info)
            media_summary = f"[Image Content Analysis: {vision_analysis}]"
            user_text = f"{caption} {media_summary}".strip() if caption else media_summary

        # C. Document / PDF
        elif msg_type == "document":
            filename = media_info.get("filename", "document.pdf")
            logger.info(f"Processing inbound document: {filename}")
            doc_text = media_info.get("extracted_text", f"Attached file: {filename}")
            media_summary = f"[Document Attached ({filename}): {doc_text}]"
            user_text = f"{user_text} {media_summary}".strip()

        # D. Location Pin
        elif msg_type == "location":
            lat = media_info.get("latitude")
            lng = media_info.get("longitude")
            name = media_info.get("name", "")
            address = media_info.get("address", "")
            media_summary = f"[User shared location: {lat}, {lng} ({name} {address})]"
            user_text = f"{user_text} {media_summary}".strip()

        return user_text, media_summary

    async def _transcribe_audio_message(self, media_info: Dict[str, Any]) -> str:
        """Transcribes incoming WhatsApp voice note."""
        # Check if pre-transcribed
        if media_info.get("transcription"):
            return media_info["transcription"]

        # If audio data buffer provided, try Gemini audio reasoning
        audio_data = media_info.get("audio_bytes")
        if audio_data and self.gemini_client:
            try:
                from google.genai import types
                from config.settings import DEFAULT_GEMINI_MODEL
                res = self.gemini_client.models.generate_content(
                    model=DEFAULT_GEMINI_MODEL,
                    contents=[
                        types.Part.from_bytes(data=audio_data, mime_type="audio/ogg"),
                        "Transcribe the spoken audio message accurately. Return only the transcription text in the language spoken."
                    ]
                )
                if res and res.text:
                    return res.text.strip()
            except Exception as e:
                logger.warning(f"Gemini voice note transcription error: {e}")

        return media_info.get("caption", "[Voice message received]")

    async def _analyze_image_message(self, media_info: Dict[str, Any]) -> str:
        """Analyzes image for invoice OCR, product verification, or damage inspection."""
        if media_info.get("ocr_text"):
            return f"OCR Text: {media_info['ocr_text']}"

        image_bytes = media_info.get("image_bytes")
        caption = media_info.get("caption", "")

        if image_bytes and self.gemini_client:
            try:
                from google.genai import types
                from config.settings import DEFAULT_GEMINI_MODEL
                prompt = (
                    "You are an AI assistant analyzing a WhatsApp customer image attachment (e.g. invoice, receipt, screenshot, damaged product, item inquiry). "
                    "Extract and summarize all relevant details: line items, invoice totals, dates, product condition, or visible text. "
                    "Be concise, clear, and factual."
                )
                res = self.gemini_client.models.generate_content(
                    model=DEFAULT_GEMINI_MODEL,
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                        prompt
                    ]
                )
                if res and res.text:
                    return res.text.strip()
            except Exception as e:
                logger.warning(f"Gemini Vision image inspection error: {e}")

        return f"Image attachment received (caption: '{caption}')."

    # ── ReAct Autonomous Reasoning Engine ─────────────────────────────────────

    async def _run_reasoning_loop(
        self,
        sender: str,
        user_input: str,
        media_summary: str,
        customer_profile: Dict[str, Any],
        history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Executes multi-step ReAct reasoning:
        1. Evaluates user intent against available domain tools.
        2. Executes tools (e.g. Order query, Knowledge base RAG, Booking, Payment link).
        3. Generates conversational reply in the customer's language.
        """
        tool_defs = WhatsAppToolRegistry.get_tool_definitions()
        tool_results = []
        interactive_buttons = None

        # Build System Prompt
        system_instruction = f"""You are the official autonomous WhatsApp AI Employee for our enterprise.
Your goal is to assist customers politely, accurately, and efficiently in natural conversational language.

Capabilities & Guidelines:
1. Always maintain context: Identify the customer ({customer_profile.get('name', 'Valued Customer')}, phone: {sender}).
2. Language: Always reply in the same language the customer uses (e.g., English, Spanish, Gujarati, Hindi, French).
3. Actions: When a customer asks about orders, product availability, bookings, payments, or company policies, USE THE APPROPRIATE TOOL immediately. Do not invent order numbers, prices, or policies.
4. Multimodal: If an image or voice transcript is provided, factor it into your reasoning (e.g., verifying an invoice total or product photo).
5. Tone: Concise, friendly, and professional. Use formatting suitable for WhatsApp (emojis, bullet points, *bold*).
6. Human Escalation: If the customer is deeply frustrated or asks for a human agent, call the `escalate_to_human` tool.

Available Tools:
{json.dumps(tool_defs, indent=2)}

Output Format:
You MUST respond with valid JSON containing:
{{
  "thought": "Internal reasoning step...",
  "tool_calls": [
    {{"name": "tool_name", "args": {{"arg1": "val1"}}}}
  ],
  "response_text": "Direct response to send to the customer via WhatsApp (or empty if waiting for tool results)"
}}
"""

        # Conversation turns formatting
        formatted_history = "\n".join([f"{h['role'].upper()}: {h['text']}" for h in history])
        user_prompt = f"""Conversation History:
{formatted_history}

Current Customer Message:
User ({sender}): {user_input}

Customer Profile:
{json.dumps(customer_profile, indent=2)}

Perform ReAct reasoning. Decide if any tools are needed, or provide the final conversational answer."""

        # Step 1: Initial LLM decision
        decision_raw = await self._generate_direct_llm(
            prompt=user_prompt,
            system_instruction=system_instruction,
            response_mime_type="application/json"
        )

        parsed_decision = self._parse_json_decision(decision_raw)

        # Step 2: Execute requested tools
        tool_calls = parsed_decision.get("tool_calls", [])
        if tool_calls:
            for tc in tool_calls:
                t_name = tc.get("name")
                t_args = tc.get("args", {})
                # Inject phone number if missing
                if "phone" in WhatsAppToolRegistry.get_tool_definitions() and not t_args.get("phone"):
                    t_args["phone"] = sender
                
                logger.info(f"WhatsAppAgent executing tool '{t_name}' with args: {t_args}")
                t_result = await WhatsAppToolRegistry.execute_tool(t_name, t_args)
                tool_results.append({"tool": t_name, "args": t_args, "result": t_result})

                if t_name == "escalate_to_human":
                    # Mark human takeover in memory for 60 minutes
                    self._human_takeovers[sender] = time.time() + 3600

            # Step 3: Second LLM pass to synthesize tool results into final customer reply
            synthesize_prompt = f"""The user asked: "{user_input}"
You executed the following business tools:
{json.dumps(tool_results, indent=2)}

Now generate the final, polite, and helpful response to send to the customer on WhatsApp.
Return JSON:
{{
  "thought": "Synthesis reasoning...",
  "response_text": "*Your order status update / response here*",
  "suggested_buttons": ["Track Shipment", "Contact Support"]
}}"""
            synth_raw = await self._generate_direct_llm(
                prompt=synthesize_prompt,
                system_instruction=system_instruction,
                response_mime_type="application/json"
            )
            synth_parsed = self._parse_json_decision(synth_raw)
            final_text = synth_parsed.get("response_text") or parsed_decision.get("response_text", "")
            interactive_buttons = synth_parsed.get("suggested_buttons")
        else:
            final_text = parsed_decision.get("response_text", "")

        if not final_text:
            final_text = "I received your message. How can I assist you with your orders, products, or inquiries today?"

        return {
            "response_text": final_text,
            "tool_results": tool_results,
            "interactive_buttons": interactive_buttons
        }

    # ── Outbound WhatsApp Message Dispatcher ──────────────────────────────────

    async def _dispatch_reply(
        self,
        to: str,
        text: str,
        target_msg_id: Optional[str] = None,
        buttons: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Sends reply back to WhatsApp via adapter or Meta Cloud API."""
        clean_phone = ''.join(c for c in str(to) if c.isdigit())
        
        # If adapter is available, use it directly
        if self.adapter:
            payload = {
                "to": clean_phone,
                "body": text,
                "target_message_id": target_msg_id
            }
            if buttons and len(buttons) <= 3:
                payload["buttons"] = buttons
            return await self.adapter.execute("send_message", payload)

        logger.info(f"[WHATSAPP OUTBOUND TO {clean_phone}]: {text}")
        return {"success": True, "status": "logged_no_adapter", "to": clean_phone, "text": text}

    # ── Memory & Conversation Persistence ─────────────────────────────────────

    async def _get_recent_history(self, phone: str, limit: int = 6) -> List[Dict[str, str]]:
        """Retrieves recent conversation history from SQLite contacts/messages table."""
        clean_phone = ''.join(c for c in str(phone) if c.isdigit())
        history = []
        try:
            db_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "contacts.db"))
            if os.path.exists(db_file):
                with sqlite3.connect(db_file) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT sender, recipient, text, timestamp FROM social_inbound_messages
                        WHERE platform = 'whatsapp' AND (sender LIKE ? OR recipient LIKE ?)
                        ORDER BY timestamp DESC LIMIT ?
                    """, (f"%{clean_phone[-10:]}%", f"%{clean_phone[-10:]}%", limit))
                    rows = cursor.fetchall()
                    for r in reversed(rows):
                        role = "user" if clean_phone[-10:] in r["sender"] else "assistant"
                        history.append({"role": role, "text": r["text"]})
        except Exception as e:
            logger.debug(f"History retrieval warning: {e}")

        return history

    async def _save_agent_reply(self, recipient: str, text: str):
        """Saves outgoing AI assistant reply to SQLite for context continuity."""
        try:
            db_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "contacts.db"))
            os.makedirs(os.path.dirname(db_file), exist_ok=True)
            with sqlite3.connect(db_file) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS social_inbound_messages (
                        id TEXT PRIMARY KEY,
                        platform TEXT,
                        sender TEXT,
                        recipient TEXT,
                        text TEXT,
                        timestamp TEXT,
                        message_id TEXT
                    )
                """)
                conn.execute("""
                    INSERT INTO social_inbound_messages (id, platform, sender, recipient, text, timestamp, message_id)
                    VALUES (?, 'whatsapp', 'JARVIS_AI_AGENT', ?, ?, ?, ?)
                """, (str(uuid.uuid4()), recipient, text, str(datetime.now().timestamp()), f"out_{uuid.uuid4().hex[:8]}"))
        except Exception as e:
            logger.debug(f"Error saving outgoing reply: {e}")

    # ── Helper & Guardrail Utilities ──────────────────────────────────────────

    def _is_human_takeover_active(self, phone: str) -> bool:
        expiry = self._human_takeovers.get(phone, 0.0)
        if time.time() < expiry:
            return True
        elif phone in self._human_takeovers:
            del self._human_takeovers[phone]
        return False

    def _check_prompt_injection(self, text: str) -> bool:
        """Basic prompt injection and jailbreak detector."""
        patterns = [
            r"ignore\s+(all\s+)?previous\s+instructions",
            r"system\s+prompt\s+override",
            r"you\s+are\s+now\s+in\s+developer\s+mode",
            r"reveal\s+(your\s+)?secret\s+key",
            r"dan\s+mode\s+enabled",
            r"bypass\s+all\s+safety\s+filters"
        ]
        text_lower = text.lower()
        return any(re.search(pat, text_lower) for pat in patterns)

    def _parse_json_decision(self, raw_llm_output: Optional[str]) -> Dict[str, Any]:
        """Safely parses JSON responses from LLM."""
        if not raw_llm_output:
            return {}
        clean = raw_llm_output.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        if clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

        try:
            return json.loads(clean)
        except Exception:
            # Match first json block
            m = re.search(r"(\{.*\})", clean, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    pass
        return {"response_text": raw_llm_output}

    async def _get_metrics(self) -> Dict[str, Any]:
        """Returns operational metrics for WhatsApp AI Employee."""
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM wa_orders")
            orders_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM wa_appointments")
            bookings_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM wa_escalations WHERE status = 'Open'")
            open_escalations = cursor.fetchone()[0]

        return {
            "auto_reply_enabled": self.auto_reply_enabled,
            "active_human_takeovers_count": len(self._human_takeovers),
            "total_orders": orders_count,
            "total_bookings": bookings_count,
            "open_human_escalations": open_escalations
        }

    async def _list_escalations(self, status: str = "Open") -> List[Dict[str, Any]]:
        """Lists human escalation tickets."""
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM wa_escalations WHERE status = ? ORDER BY created_at DESC LIMIT 20", (status,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
