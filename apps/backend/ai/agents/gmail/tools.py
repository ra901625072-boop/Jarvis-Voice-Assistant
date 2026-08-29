"""
tools.py — Specialist Domain Tools and SQLite State Registry for Autonomous Gmail AI Agent.

Provides structured tools for:
- Threat Sentinel & Prompt Injection Sanitizer
- Thread Categorization, Urgency & Triage Engine
- Contextual Draft Queue & Persona Generation
- Calendar Meeting / Event Extractor
- Follow-up & Promise SLA Tracker
- Inbox Analytics & Executive Digest Aggregator
- Immutable Audit Ledger & Idempotency Store
"""
import os
import re
import time
import json
import uuid
import sqlite3
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("JARVIS.GmailTools")

DB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"))
DB_PATH = os.path.join(DB_DIR, "gmail_agent.db")


def init_gmail_db():
    """Initializes tables for Gmail Agent threads, drafts, follow-ups, calendar events, and audit logs."""
    os.makedirs(DB_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        # 1. Email Threads State
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_threads (
                thread_id TEXT PRIMARY KEY,
                subject TEXT,
                sender TEXT,
                recipients TEXT,
                category TEXT,
                urgency_score REAL,
                action_state TEXT,
                summary TEXT,
                last_message_id TEXT,
                message_count INTEGER DEFAULT 1,
                has_attachments INTEGER DEFAULT 0,
                is_quarantined INTEGER DEFAULT 0,
                security_flags TEXT,
                last_updated TEXT
            )
        """)

        # 2. Draft Queue (HITL Review / Autonomous Drafting)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS draft_queue (
                draft_id TEXT PRIMARY KEY,
                thread_id TEXT,
                recipient TEXT,
                subject TEXT,
                body TEXT,
                tone TEXT,
                key_points TEXT,
                status TEXT,
                created_at TEXT,
                approved_at TEXT,
                sent_at TEXT
            )
        """)

        # 3. Follow-ups and Commitments (Promises & SLA)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_followups (
                followup_id TEXT PRIMARY KEY,
                thread_id TEXT,
                recipient TEXT,
                direction TEXT,
                promise_text TEXT,
                due_date TEXT,
                status TEXT,
                created_at TEXT,
                resolved_at TEXT
            )
        """)

        # 4. Calendar Events Extracted
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events_extracted (
                event_id TEXT PRIMARY KEY,
                thread_id TEXT,
                title TEXT,
                start_time TEXT,
                end_time TEXT,
                attendees TEXT,
                location TEXT,
                description TEXT,
                status TEXT,
                created_at TEXT
            )
        """)

        # 5. Immutable Audit Log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_audit_log (
                log_id TEXT PRIMARY KEY,
                action_type TEXT,
                target_id TEXT,
                tier INTEGER,
                details TEXT,
                status TEXT,
                approved_by TEXT,
                timestamp TEXT
            )
        """)

        # 6. Idempotency Store
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_idempotency (
                idempotency_key TEXT PRIMARY KEY,
                action_name TEXT,
                response_json TEXT,
                created_at TEXT
            )
        """)

        conn.commit()
        logger.info(f"Initialized Gmail Agent SQLite Database at {DB_PATH}")


class GmailToolRegistry:
    """Registry and execution engine for all specialist Gmail tools."""

    @staticmethod
    def _sanitize_untrusted_input(text: str) -> str:
        """Sanitizes untrusted email body content against system prompt injection."""
        if not text:
            return ""
        cleaned = text.replace("```system", "```escaped_block").replace("```json", "```escaped_json")
        return cleaned

    @classmethod
    async def security_scan_email(cls, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Zero-Trust security scan: detects prompt injection, domain spoofing, and malicious patterns.
        """
        init_gmail_db()
        subject = str(email_data.get("subject", ""))
        sender = str(email_data.get("from", "") or email_data.get("sender", ""))
        body = str(email_data.get("body", "") or email_data.get("body_text", "") or email_data.get("snippet", ""))

        flags = []
        is_quarantined = False

        # 1. Prompt Injection Checks
        injection_patterns = [
            r"ignore\s+(all\s+)?previous\s+instructions",
            r"disregard\s+(all\s+)?prior\s+prompts",
            r"system\s*:\s*override",
            r"you\s+are\s+now\s+in\s+developer\s+mode",
            r"forward\s+(all\s+)?emails\s+to",
            r"drop\s+table\s+",
            r"admin\s+mode\s+enabled",
            r"delete\s+all\s+(drafts|files|emails)",
            r"export\s+credentials",
        ]
        for pattern in injection_patterns:
            if re.search(pattern, body, re.IGNORECASE) or re.search(pattern, subject, re.IGNORECASE):
                flags.append(f"Prompt Injection Signature: '{pattern}'")
                is_quarantined = True

        # 2. Phishing & Suspicious Link Patterns
        phishing_indicators = [
            r"account\s+suspended.*verify\s+password",
            r"urgent\s+wire\s+transfer",
            r"crypto.*wallet.*seed\s+phrase",
            r"irs\s+tax\s+penalty.*pay\s+immediately",
            r"login\s+to\s+claim\s+your\s+prize",
        ]
        for indicator in phishing_indicators:
            if re.search(indicator, body, re.IGNORECASE) or re.search(indicator, subject, re.IGNORECASE):
                flags.append(f"Phishing Indicator: '{indicator}'")
                is_quarantined = True

        # 3. Suspicious Domain Spoofing Checks
        if "paypa1.com" in sender.lower() or "micros0ft.com" in sender.lower() or "goog1e.com" in sender.lower():
            flags.append("Domain Typosquatting / Spoofing detected")
            is_quarantined = True

        return {
            "success": True,
            "is_quarantined": is_quarantined,
            "security_flags": flags,
            "risk_level": "CRITICAL" if is_quarantined else ("ELEVATED" if flags else "LOW"),
            "safe_body": "[QUARANTINED CONTENT — POTENTIAL SECURITY RISK]" if is_quarantined else cls._sanitize_untrusted_input(body)
        }

    @classmethod
    async def classify_and_triage_thread(cls, thread_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classifies thread category, urgency score (0.0 to 1.0), and determines action DAG.
        """
        init_gmail_db()
        thread_id = str(thread_data.get("thread_id") or thread_data.get("id") or str(uuid.uuid4()))
        subject = str(thread_data.get("subject", "")).strip()
        sender = str(thread_data.get("from", "") or thread_data.get("sender", "")).strip()
        recipients = str(thread_data.get("to", "") or thread_data.get("recipients", "")).strip()
        body = str(thread_data.get("body", "") or thread_data.get("body_text", "") or thread_data.get("snippet", ""))
        has_attachments = 1 if thread_data.get("has_attachments") or thread_data.get("attachments") else 0

        # Run Security Scan First
        sec_result = await cls.security_scan_email(thread_data)
        is_quarantined = 1 if sec_result.get("is_quarantined") else 0
        security_flags = json.dumps(sec_result.get("security_flags", []))

        category = "General"
        urgency_score = 0.3
        action_state = "read_only"
        summary = ""

        lower_sub = subject.lower()
        lower_body = body.lower()

        if is_quarantined:
            category = "Spam_Suspicious"
            urgency_score = 0.0
            action_state = "quarantine"
            summary = f"Quarantined due to security risks: {', '.join(sec_result.get('security_flags', []))}"
        else:
            if any(k in lower_body or k in lower_sub for k in ["unsubscribe", "view in browser", "privacy policy", "opt-out", "newsletter", "promotional email"]):
                category = "Newsletter_Marketing"
                urgency_score = 0.1
                action_state = "archive_candidate"
                summary = "Marketing / Newsletter message"

            elif any(k in lower_sub or k in lower_body for k in ["invoice", "receipt", "payment confirmation", "billed to", "order confirmation", "transaction id"]):
                category = "Invoice_Financial"
                urgency_score = 0.5
                action_state = "extract_financial"
                summary = "Financial invoice or transaction receipt"

            elif any(k in lower_sub or k in lower_body for k in ["meeting", "schedule a call", "google meet", "zoom meeting", "discussion on ai", "calendar invite", "demo"]):
                category = "Work_Task"
                urgency_score = 0.8
                action_state = "calendar_and_reply"
                summary = "Meeting invitation or scheduling request"

            elif any(k in lower_sub or k in lower_body for k in ["urgent", "asap", "emergency", "deadline", "action required", "time sensitive", "immediate attention"]):
                category = "Urgent_VIP"
                urgency_score = 0.95
                action_state = "priority_reply_needed"
                summary = "High-priority urgent message requiring prompt action"

            elif "?" in body or any(k in lower_body for k in ["please provide", "can you", "let me know", "update on", "review", "status"]):
                category = "Work_Task"
                urgency_score = 0.7
                action_state = "reply_needed"
                summary = "Direct inquiry or work request requiring response"

            else:
                category = "Work_Task" if "@" in sender and not any(d in sender for d in ["no-reply", "noreply", "notifications"]) else "Personal"
                urgency_score = 0.4
                action_state = "informational"
                summary = f"Message regarding '{subject}'"

        now_str = datetime.now().isoformat()

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO email_threads (
                    thread_id, subject, sender, recipients, category, urgency_score,
                    action_state, summary, last_message_id, message_count, has_attachments,
                    is_quarantined, security_flags, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    subject=excluded.subject,
                    sender=excluded.sender,
                    recipients=excluded.recipients,
                    category=excluded.category,
                    urgency_score=excluded.urgency_score,
                    action_state=excluded.action_state,
                    summary=excluded.summary,
                    has_attachments=excluded.has_attachments,
                    is_quarantined=excluded.is_quarantined,
                    security_flags=excluded.security_flags,
                    last_updated=excluded.last_updated
            """, (
                thread_id, subject, sender, recipients, category, urgency_score,
                action_state, summary, thread_data.get("id", ""),
                thread_data.get("message_count", 1), has_attachments,
                is_quarantined, security_flags, now_str
            ))
            conn.commit()

        return {
            "success": True,
            "thread_id": thread_id,
            "category": category,
            "urgency_score": urgency_score,
            "action_state": action_state,
            "summary": summary,
            "is_quarantined": bool(is_quarantined),
            "security_flags": sec_result.get("security_flags", [])
        }

    @classmethod
    async def generate_contextual_draft(
        cls,
        thread_id: str,
        recipient: str,
        subject: str,
        context_body: str,
        tone: str = "professional_warm",
        key_points: Optional[List[str]] = None,
        custom_instructions: str = ""
    ) -> Dict[str, Any]:
        """
        Creates a high-quality email draft, stores it in the draft_queue, and logs the audit event.
        """
        init_gmail_db()
        draft_id = f"DFT-{uuid.uuid4().hex[:8].upper()}"
        clean_subject = subject if subject.startswith("Re:") else f"Re: {subject}"

        points_text = "\n".join([f"- {p}" for p in (key_points or [])])
        
        greeting = f"Hi {recipient.split('<')[0].strip().split(' ')[0] if recipient else 'there'},"
        body_lines = [
            greeting,
            "",
            "Thank you for reaching out."
        ]

        if "meeting" in subject.lower() or "meeting" in context_body.lower():
            body_lines.append("I have reviewed your proposal and would be glad to connect. The proposed timing works well on my end.")
        elif key_points:
            body_lines.append("Regarding your questions:")
            body_lines.append(points_text)
        else:
            body_lines.append("I have reviewed your note and am looking into this right now. I will follow up shortly with full details.")

        body_lines.extend([
            "",
            "Best regards,",
            "JARVIS (on behalf of User)"
        ])
        body = "\n".join(body_lines)

        now_str = datetime.now().isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO draft_queue (
                    draft_id, thread_id, recipient, subject, body, tone, key_points,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                draft_id, thread_id, recipient, clean_subject, body, tone,
                json.dumps(key_points or []), "pending", now_str
            ))
            
            cursor.execute("""
                INSERT INTO email_audit_log (
                    log_id, action_type, target_id, tier, details, status, approved_by, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f"LOG-{uuid.uuid4().hex[:8]}", "create_draft", draft_id, 0,
                f"Generated draft reply for {recipient} ({clean_subject})",
                "created", "autonomous_agent", now_str
            ))
            conn.commit()

        return {
            "success": True,
            "draft_id": draft_id,
            "thread_id": thread_id,
            "recipient": recipient,
            "subject": clean_subject,
            "body": body,
            "status": "pending"
        }

    @classmethod
    async def extract_calendar_event(cls, thread_id: str, text: str, sender: str = "", subject: str = "") -> Dict[str, Any]:
        """
        Detects meeting proposals, times, and attendees from email conversation.
        """
        init_gmail_db()
        event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"

        title = f"Meeting: {subject.replace('Re:', '').strip()}" if subject else "Meeting Discussion"
        
        time_match = re.search(r"(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))", text)
        extracted_time = time_match.group(1) if time_match else "Upcoming"

        date_match = re.search(r"\b(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text, re.IGNORECASE)
        extracted_date = date_match.group(1).capitalize() if date_match else "Soon"

        start_time = f"{extracted_date} at {extracted_time}"
        end_time = f"{extracted_date} (1 hour duration)"
        attendees = sender if sender else "Team"

        now_str = datetime.now().isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO calendar_events_extracted (
                    event_id, thread_id, title, start_time, end_time, attendees,
                    location, description, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id, thread_id, title, start_time, end_time, attendees,
                "Google Meet / Virtual", f"Extracted from email thread: {subject}", "proposed", now_str
            ))
            conn.commit()

        return {
            "success": True,
            "event_id": event_id,
            "thread_id": thread_id,
            "title": title,
            "start_time": start_time,
            "attendees": attendees,
            "status": "proposed"
        }

    @classmethod
    async def schedule_followup_reminder(
        cls,
        thread_id: str,
        recipient: str,
        promise_text: str,
        due_date: str = "In 3 days",
        direction: str = "outgoing_promise"
    ) -> Dict[str, Any]:
        """
        Tracks commitments and unanswered SLA follow-ups.
        """
        init_gmail_db()
        followup_id = f"FLP-{uuid.uuid4().hex[:8].upper()}"
        now_str = datetime.now().isoformat()

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO email_followups (
                    followup_id, thread_id, recipient, direction, promise_text,
                    due_date, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                followup_id, thread_id, recipient, direction, promise_text,
                due_date, "pending", now_str
            ))
            conn.commit()

        return {
            "success": True,
            "followup_id": followup_id,
            "thread_id": thread_id,
            "recipient": recipient,
            "promise_text": promise_text,
            "due_date": due_date,
            "status": "pending"
        }

    @classmethod
    async def list_pending_drafts(cls, status: str = "pending", limit: int = 10) -> Dict[str, Any]:
        """Retrieves list of drafted emails in the review queue."""
        init_gmail_db()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM draft_queue WHERE status = ? ORDER BY created_at DESC LIMIT ?
            """, (status, limit))
            rows = cursor.fetchall()
            drafts = [dict(r) for r in rows]

        return {
            "success": True,
            "count": len(drafts),
            "drafts": drafts
        }

    @classmethod
    async def approve_and_send_draft(cls, draft_id: str, approved_by: str = "user") -> Dict[str, Any]:
        """Approves a draft in the queue and prepares it for transmission."""
        init_gmail_db()
        now_str = datetime.now().isoformat()

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM draft_queue WHERE draft_id = ?", (draft_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": f"Draft '{draft_id}' not found in queue"}

            draft = dict(row)
            cursor.execute("""
                UPDATE draft_queue SET status = 'approved', approved_at = ? WHERE draft_id = ?
            """, (now_str, draft_id))

            cursor.execute("""
                INSERT INTO email_audit_log (
                    log_id, action_type, target_id, tier, details, status, approved_by, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f"LOG-{uuid.uuid4().hex[:8]}", "approve_draft", draft_id, 2,
                f"Draft approved for dispatch to {draft.get('recipient')} ({draft.get('subject')})",
                "approved", approved_by, now_str
            ))
            conn.commit()

        return {
            "success": True,
            "draft_id": draft_id,
            "draft": draft,
            "status": "approved",
            "approved_at": now_str
        }

    @classmethod
    async def query_inbox_analytics(cls) -> Dict[str, Any]:
        """Aggregates executive analytics across all indexed email threads."""
        init_gmail_db()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) as cnt FROM email_threads")
            total_threads = cursor.fetchone()["cnt"]

            cursor.execute("SELECT category, COUNT(*) as cnt FROM email_threads GROUP BY category")
            categories = {r["category"]: r["cnt"] for r in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) as cnt FROM email_threads WHERE urgency_score >= 0.8")
            urgent_count = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) as cnt FROM email_threads WHERE is_quarantined = 1")
            quarantined_count = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) as cnt FROM draft_queue WHERE status = 'pending'")
            pending_drafts = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) as cnt FROM email_followups WHERE status = 'pending'")
            pending_followups = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) as cnt FROM calendar_events_extracted WHERE status = 'proposed'")
            extracted_meetings = cursor.fetchone()["cnt"]

        return {
            "success": True,
            "total_threads_indexed": total_threads,
            "urgent_threads_count": urgent_count,
            "quarantined_threats_count": quarantined_count,
            "pending_drafts_count": pending_drafts,
            "pending_followups_count": pending_followups,
            "extracted_meetings_count": extracted_meetings,
            "categories": categories
        }

    @classmethod
    async def get_audit_trail(cls, limit: int = 50) -> Dict[str, Any]:
        """Retrieves recent entries from the immutable email audit log."""
        init_gmail_db()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM email_audit_log ORDER BY timestamp DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            logs = [dict(r) for r in rows]

        return {
            "success": True,
            "count": len(logs),
            "logs": logs
        }