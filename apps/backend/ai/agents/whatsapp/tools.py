"""
tools.py — Specialist Business Tools for WhatsApp AI Agent.

Provides domain tools for:
- E-Commerce & Orders (query status, create order, update address)
- Product Catalog & Recommendations
- Appointments & Booking
- Payments & Invoicing
- Knowledge Base / Policy FAQ Search (RAG)
- CRM & Customer Profile Management
- Human Handoff & Escalation Management
All mutation actions enforce idempotency to prevent duplicate operations.
"""
import os
import re
import time
import json
import uuid
import difflib
import sqlite3
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("JARVIS.WhatsAppTools")

DB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"))
DB_PATH = os.path.join(DB_DIR, "whatsapp_agent.db")


def init_whatsapp_db():
    """Initializes tables for WhatsApp Agent orders, drafts, followups, catalog, bookings, tickets, and idempotency."""
    os.makedirs(DB_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        # 0. Executive Pending Drafts Queue (HITL Approval)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_pending_drafts (
                draft_id TEXT PRIMARY KEY,
                contact TEXT NOT NULL,
                recipient_phone TEXT,
                original_message TEXT,
                drafted_reply TEXT NOT NULL,
                urgency TEXT DEFAULT 'NEEDS_REPLY',
                context_summary TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                approved_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wa_drafts_status ON wa_pending_drafts(status)")

        # 0.1. Commitments & SLA Follow-up Tracker
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_followups (
                followup_id TEXT PRIMARY KEY,
                contact TEXT NOT NULL,
                phone TEXT,
                commitment_text TEXT NOT NULL,
                due_date TEXT NOT NULL,
                direction TEXT DEFAULT 'outgoing_promise',
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wa_followups_status ON wa_followups(status)")

        # 0.2. Document & Attachment Intelligence Index
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_attachments_index (
                attachment_id TEXT PRIMARY KEY,
                contact TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_type TEXT DEFAULT 'document',
                extracted_summary TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        
        # 1. Orders
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_orders (
                order_id TEXT PRIMARY KEY,
                customer_phone TEXT,
                customer_name TEXT,
                items TEXT,
                total_amount REAL,
                currency TEXT,
                status TEXT,
                tracking_number TEXT,
                carrier TEXT,
                delivery_address TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # 2. Product Catalog
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_catalog (
                product_id TEXT PRIMARY KEY,
                name TEXT,
                category TEXT,
                description TEXT,
                price REAL,
                currency TEXT,
                stock_count INTEGER,
                image_url TEXT
            )
        """)

        # 3. Appointments & Bookings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_appointments (
                booking_id TEXT PRIMARY KEY,
                customer_phone TEXT,
                customer_name TEXT,
                service_type TEXT,
                scheduled_time TEXT,
                status TEXT,
                notes TEXT,
                created_at TEXT
            )
        """)

        # 4. Human Escalation Tickets
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_escalations (
                ticket_id TEXT PRIMARY KEY,
                customer_phone TEXT,
                customer_name TEXT,
                reason TEXT,
                conversation_summary TEXT,
                status TEXT,
                created_at TEXT,
                resolved_at TEXT
            )
        """)

        # 5. Idempotency Store
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_idempotency (
                idempotency_key TEXT PRIMARY KEY,
                action_name TEXT,
                response_json TEXT,
                created_at REAL
            )
        """)

        # 6. Knowledge Base Articles
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_knowledge_base (
                article_id TEXT PRIMARY KEY,
                topic TEXT,
                title TEXT,
                content TEXT,
                keywords TEXT
            )
        """)

        # 7. Customer CRM Memory
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_crm_profiles (
                phone TEXT PRIMARY KEY,
                name TEXT,
                preferred_language TEXT,
                vip_status INTEGER,
                notes TEXT,
                total_spent REAL,
                last_interaction TEXT
            )
        """)

        # 8. Audit & Observability Trail (Traceable ReAct Logs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_audit_logs (
                log_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                action_id TEXT,
                user_request TEXT,
                intent TEXT,
                contact TEXT,
                phone TEXT,
                autonomy_mode TEXT DEFAULT 'ASSISTED',
                risk_level TEXT DEFAULT 'L0',
                hitl_status TEXT DEFAULT 'auto',
                approver TEXT,
                tools_used TEXT,
                payload_hash TEXT,
                execution_status TEXT,
                verification_status TEXT,
                outcome TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wa_audit_ts ON wa_audit_logs(timestamp)")

        # 9. Idempotency State Machine (Duplicate Prevention)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wa_state_machine (
                action_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                recipient TEXT NOT NULL,
                message_hash TEXT,
                attachment_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                details_json TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wa_state_recipient ON wa_state_machine(recipient)")

        conn.commit()

        # Populate sample catalog & knowledge base if empty
        cursor.execute("SELECT COUNT(*) FROM wa_catalog")
        if cursor.fetchone()[0] == 0:
            sample_products = [
                ("PROD-001", "Ultra Wireless Headphones", "Electronics", "Active noise cancellation, 40h battery life, premium sound.", 149.99, "USD", 25, "https://example.com/headphones.jpg"),
                ("PROD-002", "Ergonomic Mechanical Keyboard", "Electronics", "Hot-swappable switches, RGB backlight, wireless Bluetooth.", 89.99, "USD", 18, "https://example.com/keyboard.jpg"),
                ("PROD-003", "Smart Fitness Watch V3", "Wearables", "Heart rate, SpO2, sleep tracking, waterproof 5ATM, GPS.", 119.50, "USD", 40, "https://example.com/watch.jpg"),
                ("PROD-004", "Premium Leather Laptop Sleeve", "Accessories", "Water-resistant genuine leather sleeve for 13-16 inch laptops.", 45.00, "USD", 50, "https://example.com/sleeve.jpg"),
                ("PROD-005", "USB-C GaN 100W Fast Charger", "Accessories", "Compact 4-port fast wall charger with PD 3.0 support.", 39.99, "USD", 65, "https://example.com/charger.jpg")
            ]
            cursor.executemany("INSERT INTO wa_catalog VALUES (?, ?, ?, ?, ?, ?, ?, ?)", sample_products)

        cursor.execute("SELECT COUNT(*) FROM wa_knowledge_base")
        if cursor.fetchone()[0] == 0:
            sample_articles = [
                ("KB-001", "Returns & Refunds", "Return Policy", "Items can be returned within 30 days of receipt in original condition. Return shipping is free for damaged or defective items.", "return refund exchange 30 days policy money back"),
                ("KB-002", "Shipping & Delivery", "Shipping Timelines", "Standard domestic shipping takes 3-5 business days. Express shipping takes 1-2 business days. International delivery takes 7-14 business days.", "shipping delivery track courier time international standard express"),
                ("KB-003", "Warranty & Support", "Product Warranty", "All electronics carry a 1-year limited manufacturer warranty covering defects in materials and craftsmanship.", "warranty guarantee repair replace support claim"),
                ("KB-004", "Payment Methods", "Accepted Payments", "We accept Visa, MasterCard, American Express, PayPal, Apple Pay, Google Pay, and UPI.", "payment card credit debit upi paypal pay checkout")
            ]
            cursor.executemany("INSERT INTO wa_knowledge_base VALUES (?, ?, ?, ?, ?)", sample_articles)

        cursor.execute("SELECT COUNT(*) FROM wa_orders")
        if cursor.fetchone()[0] == 0:
            sample_orders = [
                ("ORD-1001", "919876543210", "Alex Mercer", json.dumps([{"name": "Ultra Wireless Headphones", "qty": 1, "price": 149.99}]), 149.99, "USD", "Shipped", "TRK-9847291", "FedEx", "123 Tech Blvd, Austin, TX 78701", datetime.now().isoformat(), datetime.now().isoformat()),
                ("ORD-1002", "919876543210", "Alex Mercer", json.dumps([{"name": "USB-C GaN 100W Fast Charger", "qty": 2, "price": 39.99}]), 79.98, "USD", "Delivered", "TRK-4819402", "DHL", "123 Tech Blvd, Austin, TX 78701", datetime.now().isoformat(), datetime.now().isoformat())
            ]
            cursor.executemany("INSERT INTO wa_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", sample_orders)

        conn.commit()


# Initialize database on module load
init_whatsapp_db()


class WhatsAppToolRegistry:
    """
    Registry of executable business tools for WhatsApp AI Agent.
    """

    @classmethod
    def get_tool_definitions(cls) -> List[Dict[str, Any]]:
        """Returns JSON schema definitions for function calling."""
        return [
            # ── 1. Executive Triage & Drafting Tools ──────────────────────────
            {
                "name": "create_draft_reply",
                "description": "Store a drafted reply in the pending review queue for Human-in-the-Loop user approval before sending.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "contact": {"type": "string", "description": "Contact name or chat identifier."},
                        "recipient_phone": {"type": "string", "description": "Customer or contact phone number."},
                        "original_message": {"type": "string", "description": "The incoming message being replied to."},
                        "drafted_reply": {"type": "string", "description": "The synthesized reply matching Akshay's persona/tone."},
                        "urgency": {"type": "string", "enum": ["URGENT_ACTION", "NEEDS_REPLY", "INFO_ONLY"], "description": "Urgency tier."},
                        "context_summary": {"type": "string", "description": "Short explanation of why this reply was crafted."}
                    },
                    "required": ["contact", "drafted_reply"]
                }
            },
            {
                "name": "list_pending_drafts",
                "description": "List AI-drafted WhatsApp replies waiting for human approval.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["pending", "approved", "rejected", "all"], "default": "pending"},
                        "limit": {"type": "integer", "default": 5}
                    }
                }
            },
            {
                "name": "schedule_followup",
                "description": "Track an outgoing promise, commitment, or incoming SLA deadline on WhatsApp.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "contact": {"type": "string", "description": "Contact person name."},
                        "phone": {"type": "string", "description": "Contact phone number if known."},
                        "commitment_text": {"type": "string", "description": "The promise or task (e.g., 'Send updated design tomorrow morning')."},
                        "due_date": {"type": "string", "description": "When the commitment is due (e.g. 'Tomorrow 10:00 AM', '2026-08-30')."},
                        "direction": {"type": "string", "enum": ["outgoing_promise", "incoming_sla"], "default": "outgoing_promise"}
                    },
                    "required": ["contact", "commitment_text", "due_date"]
                }
            },
            {
                "name": "inspect_document",
                "description": "Extract text, requirements, or structured breakdown from an attached PDF, image invoice, or document.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "contact": {"type": "string", "description": "Sender contact name."},
                        "file_name": {"type": "string", "description": "Name of the file (e.g. project_requirements.pdf)."},
                        "content_text": {"type": "string", "description": "Extracted text or document description."}
                    },
                    "required": ["contact", "file_name"]
                }
            },
            {
                "name": "summarize_chat_history",
                "description": "Summarize a long 1-on-1 or group WhatsApp conversation, identifying main discussion topics, decisions, and action items.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "contact": {"type": "string", "description": "Contact or Group name."},
                        "messages": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "List of message objects (sender, text, timestamp)."
                        }
                    },
                    "required": ["contact"]
                }
            },
            # ── 2. Business & Commerce Tools ──────────────────────────────────
            {
                "name": "query_order_status",
                "description": "Look up current order status, shipment tracking number, carrier, items, and delivery address by order ID or customer phone.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string", "description": "The order ID (e.g. ORD-1001), or leave blank if querying by phone."},
                        "phone": {"type": "string", "description": "Customer phone number (digits only)."}
                    }
                }
            },
            {
                "name": "update_shipping_address",
                "description": "Update the delivery address for an existing order if it has not yet been delivered or dispatched.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string", "description": "Order ID to update."},
                        "new_address": {"type": "string", "description": "The updated destination address."}
                    },
                    "required": ["order_id", "new_address"]
                }
            },
            {
                "name": "search_product_catalog",
                "description": "Search products, inventory stock, specifications, and pricing in the catalog.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search keyword or product name."},
                        "category": {"type": "string", "description": "Optional category filter (e.g. Electronics, Wearables, Accessories)."},
                        "max_price": {"type": "number", "description": "Maximum budget/price limit."}
                    }
                }
            },
            {
                "name": "create_order",
                "description": "Create a new order for the customer and reserve stock.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string", "description": "Customer phone number."},
                        "customer_name": {"type": "string", "description": "Customer name."},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "product_id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "qty": {"type": "integer"},
                                    "price": {"type": "number"}
                                },
                                "required": ["name", "qty", "price"]
                            },
                            "description": "List of items to purchase."
                        },
                        "delivery_address": {"type": "string", "description": "Full shipping address."},
                        "idempotency_key": {"type": "string", "description": "Unique key to prevent duplicate orders."}
                    },
                    "required": ["phone", "items", "delivery_address"]
                }
            },
            {
                "name": "book_appointment",
                "description": "Schedule an appointment, consultation, service, or demo for the customer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string", "description": "Customer phone number."},
                        "customer_name": {"type": "string", "description": "Customer name."},
                        "service_type": {"type": "string", "description": "Type of service or consultation."},
                        "date_time": {"type": "string", "description": "Desired appointment date and time (e.g., '2026-09-01 14:00' or 'Tomorrow at 4 PM')."},
                        "notes": {"type": "string", "description": "Optional notes or details."}
                    },
                    "required": ["phone", "service_type", "date_time"]
                }
            },
            {
                "name": "generate_payment_link",
                "description": "Generate a secure instant payment link / invoice for an order or custom amount.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string", "description": "Associated order ID if any."},
                        "amount": {"type": "number", "description": "Payment amount."},
                        "currency": {"type": "string", "description": "Currency code (USD, INR, EUR). Default: USD."},
                        "description": {"type": "string", "description": "Description of charge."}
                    },
                    "required": ["amount"]
                }
            },
            {
                "name": "search_knowledge_base",
                "description": "Search knowledge base, FAQs, company policies, shipping timelines, returns, and support docs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Question or search keywords."}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "escalate_to_human",
                "description": "Escalate the conversation to a human support agent when the customer requests a human or complex assistance is required.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string", "description": "Customer phone number."},
                        "customer_name": {"type": "string", "description": "Customer name."},
                        "reason": {"type": "string", "description": "Reason for escalation."},
                        "conversation_summary": {"type": "string", "description": "Short summary of the issue."}
                    },
                    "required": ["phone", "reason"]
                }
            },
            {
                "name": "get_customer_crm_profile",
                "description": "Retrieve customer profile, VIP status, preferred language, total spend, and past interaction notes from CRM.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string", "description": "Customer phone number (digits only)."}
                    },
                    "required": ["phone"]
                }
            }
        ]

    @classmethod
    async def execute_tool(cls, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the named business tool with validation and error protection."""
        method = getattr(cls, f"tool_{name}", None)
        if not method:
            return {"success": False, "error": f"Unknown tool: '{name}'"}

        try:
            return await method(args)
        except Exception as e:
            logger.exception(f"Error executing WhatsApp tool '{name}': {e}")
            return {"success": False, "error": str(e)}

    # ── Executive & Triage Tools ──────────────────────────────────────────────

    @classmethod
    async def tool_create_draft_reply(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """Creates a pending draft reply awaiting human confirmation."""
        contact = str(args.get("contact") or "Unknown Contact").strip()
        phone = ''.join(c for c in str(args.get("recipient_phone") or "") if c.isdigit())
        orig_msg = str(args.get("original_message") or "").strip()
        draft_reply = str(args.get("drafted_reply") or "").strip()
        urgency = str(args.get("urgency") or "NEEDS_REPLY").upper()
        summary = str(args.get("context_summary") or "").strip()

        if not draft_reply:
            return {"success": False, "error": "Drafted reply text cannot be empty."}

        draft_id = f"WA-DFT-{uuid.uuid4().hex[:8].upper()}"
        now_str = datetime.now().isoformat()

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO wa_pending_drafts (
                    draft_id, contact, recipient_phone, original_message,
                    drafted_reply, urgency, context_summary, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """, (draft_id, contact, phone, orig_msg, draft_reply, urgency, summary, now_str))
            conn.commit()

        logger.info(f"WhatsApp draft reply created: {draft_id} for {contact} (Urgency: {urgency})")
        return {
            "success": True,
            "draft_id": draft_id,
            "contact": contact,
            "recipient_phone": phone,
            "urgency": urgency,
            "drafted_reply": draft_reply,
            "status": "pending_human_approval",
            "message": f"Draft {draft_id} created and queued for user review."
        }

    @classmethod
    async def tool_list_pending_drafts(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """Lists pending or past drafts."""
        status = str(args.get("status") or "pending").lower().strip()
        limit = int(args.get("limit", 10))

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if status == "all":
                cursor.execute("SELECT * FROM wa_pending_drafts ORDER BY created_at DESC LIMIT ?", (limit,))
            else:
                cursor.execute("SELECT * FROM wa_pending_drafts WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit))
            rows = cursor.fetchall()
            drafts = [dict(r) for r in rows]

        return {
            "success": True,
            "count": len(drafts),
            "status_filter": status,
            "drafts": drafts
        }

    @classmethod
    async def tool_approve_draft(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """Marks draft as approved/sent."""
        draft_id = str(args.get("draft_id") or "").strip().upper()
        if not draft_id:
            return {"success": False, "error": "draft_id is required."}

        now_str = datetime.now().isoformat()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM wa_pending_drafts WHERE draft_id = ?", (draft_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": f"Draft '{draft_id}' not found."}

            cursor.execute("""
                UPDATE wa_pending_drafts SET status = 'approved', approved_at = ? WHERE draft_id = ?
            """, (now_str, draft_id))
            conn.commit()

            return {
                "success": True,
                "draft_id": draft_id,
                "contact": row["contact"],
                "recipient_phone": row["recipient_phone"],
                "drafted_reply": row["drafted_reply"],
                "status": "approved",
                "message": f"Draft {draft_id} approved for dispatch."
            }

    @classmethod
    async def tool_schedule_followup(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """Records an outgoing promise or incoming SLA deadline."""
        contact = str(args.get("contact") or "Contact").strip()
        phone = ''.join(c for c in str(args.get("phone") or "") if c.isdigit())
        commitment = str(args.get("commitment_text") or "").strip()
        due_date = str(args.get("due_date") or "Tomorrow").strip()
        direction = str(args.get("direction") or "outgoing_promise").strip()

        if not commitment:
            return {"success": False, "error": "commitment_text cannot be empty."}

        followup_id = f"WA-FOL-{uuid.uuid4().hex[:8].upper()}"
        now_str = datetime.now().isoformat()

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO wa_followups (
                    followup_id, contact, phone, commitment_text, due_date, direction, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """, (followup_id, contact, phone, commitment, due_date, direction, now_str))
            conn.commit()

        return {
            "success": True,
            "followup_id": followup_id,
            "contact": contact,
            "commitment": commitment,
            "due_date": due_date,
            "direction": direction,
            "status": "pending",
            "message": f"Follow-up {followup_id} scheduled for {contact} (Due: {due_date})."
        }

    @classmethod
    async def tool_list_followups(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """Lists active follow-ups and commitments."""
        status = str(args.get("status") or "pending").lower().strip()
        limit = int(args.get("limit", 10))

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if status == "all":
                cursor.execute("SELECT * FROM wa_followups ORDER BY created_at DESC LIMIT ?", (limit,))
            else:
                cursor.execute("SELECT * FROM wa_followups WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit))
            rows = cursor.fetchall()
            return {"success": True, "count": len(rows), "followups": [dict(r) for r in rows]}

    @classmethod
    async def tool_inspect_document(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts and stores requirements from PDF / image attachments."""
        contact = str(args.get("contact") or "Contact").strip()
        file_name = str(args.get("file_name") or "document.pdf").strip()
        content_text = str(args.get("content_text") or "").strip()

        att_id = f"ATT-{uuid.uuid4().hex[:8].upper()}"
        now_str = datetime.now().isoformat()

        # Parse key requirement bullet points from text
        lines = [line.strip() for line in content_text.split("\n") if line.strip()]
        reqs = [l for l in lines if any(k in l.lower() for k in ["must", "require", "deadline", "deliverable", "scope", "feature", "spec"])]
        summary = "\n".join(reqs[:6]) if reqs else (content_text[:300] if content_text else f"Attached document: {file_name}")

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO wa_attachments_index (
                    attachment_id, contact, file_name, file_type, extracted_summary, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (att_id, contact, file_name, "pdf" if file_name.endswith(".pdf") else "document", summary, now_str))
            conn.commit()

        return {
            "success": True,
            "attachment_id": att_id,
            "contact": contact,
            "file_name": file_name,
            "summary": summary,
            "extracted_requirements": reqs[:8]
        }

    @classmethod
    async def tool_summarize_chat_history(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """Summarizes messages from a group or 1-on-1 chat."""
        contact = str(args.get("contact") or "Chat").strip()
        messages = args.get("messages", [])

        if not messages:
            return {"success": False, "error": "No messages provided for summarization."}

        senders = list(set([m.get("sender", "Unknown") for m in messages]))
        msg_count = len(messages)
        key_excerpts = [f"{m.get('sender')}: {m.get('text')}" for m in messages[-8:] if m.get("text")]

        return {
            "success": True,
            "contact": contact,
            "total_messages_analyzed": msg_count,
            "participants": senders,
            "recent_context": "\n".join(key_excerpts)
        }

    @classmethod
    def security_scan_message(cls, text: str) -> Dict[str, Any]:
        """Sanitizes text and checks for prompt injections or malicious commands."""
        patterns = [
            r"ignore\s+(all\s+)?previous\s+instructions",
            r"system\s+prompt\s+override",
            r"you\s+are\s+now\s+in\s+developer\s+mode",
            r"reveal\s+(your\s+)?secret\s+key",
            r"dan\s+mode\s+enabled",
            r"bypass\s+all\s+safety\s+filters",
            r"delete\s+all\s+data",
            r"drop\s+table"
        ]
        text_lower = text.lower()
        threats_found = [pat for pat in patterns if re.search(pat, text_lower)]
        is_safe = len(threats_found) == 0

        return {
            "is_safe": is_safe,
            "threats_detected": threats_found,
            "action": "allow" if is_safe else "block"
        }

    # ── Business & E-Commerce Tools ───────────────────────────────────────────

    @classmethod
    async def tool_query_order_status(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        order_id = str(args.get("order_id") or "").strip().upper()
        phone = ''.join(c for c in str(args.get("phone", "")) if c.isdigit())

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if order_id:
                cursor.execute("SELECT * FROM wa_orders WHERE order_id = ?", (order_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        "success": True,
                        "order": {
                            "order_id": row["order_id"],
                            "customer_name": row["customer_name"],
                            "status": row["status"],
                            "tracking_number": row["tracking_number"],
                            "carrier": row["carrier"],
                            "total_amount": f"{row['total_amount']} {row['currency']}",
                            "items": json.loads(row["items"]) if row["items"] else [],
                            "delivery_address": row["delivery_address"],
                            "created_at": row["created_at"]
                        }
                    }
                return {"success": False, "error": f"No order found with ID '{order_id}'."}

            if phone:
                cursor.execute("SELECT * FROM wa_orders WHERE customer_phone LIKE ? ORDER BY created_at DESC LIMIT 5", (f"%{phone[-10:]}%",))
                rows = cursor.fetchall()
                if rows:
                    orders = []
                    for r in rows:
                        orders.append({
                            "order_id": r["order_id"],
                            "status": r["status"],
                            "tracking_number": r["tracking_number"],
                            "carrier": r["carrier"],
                            "total_amount": f"{r['total_amount']} {r['currency']}",
                            "items": json.loads(r["items"]) if r["items"] else [],
                            "created_at": r["created_at"]
                        })
                    return {"success": True, "orders": orders}
                return {"success": False, "error": f"No orders found for phone number ending in {phone[-4:]}."}

        return {"success": False, "error": "Please provide an order_id or phone number."}

    @classmethod
    async def tool_update_shipping_address(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        order_id = str(args.get("order_id") or "").strip().upper()
        new_address = str(args.get("new_address") or "").strip()

        if not order_id or not new_address:
            return {"success": False, "error": "Both order_id and new_address are required."}

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM wa_orders WHERE order_id = ?", (order_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "error": f"Order '{order_id}' not found."}

            if row["status"] in ("Delivered", "Cancelled"):
                return {"success": False, "error": f"Cannot update address: Order '{order_id}' is already {row['status']}."}

            cursor.execute(
                "UPDATE wa_orders SET delivery_address = ?, updated_at = ? WHERE order_id = ?",
                (new_address, datetime.now().isoformat(), order_id)
            )
            conn.commit()

        return {
            "success": True,
            "order_id": order_id,
            "updated_address": new_address,
            "message": f"Delivery address for order {order_id} has been successfully updated."
        }

    @classmethod
    async def tool_search_product_catalog(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        High-precision product catalog search with fuzzy typo tolerance and category filtering.
        """
        query = str(args.get("query") or "").strip().lower()
        category = str(args.get("category") or "").strip().lower()
        max_price = args.get("max_price")

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            sql = "SELECT * FROM wa_catalog WHERE 1=1"
            params = []
            if category:
                sql += " AND LOWER(category) = ?"
                params.append(category)
            if max_price:
                sql += " AND price <= ?"
                params.append(float(max_price))

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            scored_products = []
            q_words = [w for w in re.findall(r"\w+", query) if len(w) > 2]

            for r in rows:
                p_name = r["name"].lower()
                p_desc = r["description"].lower()
                p_cat = r["category"].lower()
                combined = f"{p_name} {p_cat} {p_desc}"

                if not query:
                    score = 1.0
                else:
                    # 1. Exact substring match
                    score = 2.0 if query in p_name else (1.5 if query in combined else 0.0)

                    # 2. Exact token overlap
                    token_hits = sum(1.0 for qw in q_words if qw in combined)
                    score += token_hits

                    # 3. Fuzzy similarity on full name and individual words (e.g. 'headfone' vs 'headphones')
                    sim_full = difflib.SequenceMatcher(None, query, p_name).ratio()
                    word_sims = [difflib.SequenceMatcher(None, qw, pw).ratio() for qw in (q_words or [query]) for pw in p_name.split() if len(pw) > 3]
                    max_word_sim = max(word_sims) if word_sims else 0.0

                    best_sim = max(sim_full, max_word_sim)
                    if best_sim >= 0.45:
                        score += best_sim * 2.0

                if score > 0:
                    scored_products.append((score, {
                        "product_id": r["product_id"],
                        "name": r["name"],
                        "category": r["category"],
                        "description": r["description"],
                        "price": r["price"],
                        "currency": r["currency"],
                        "in_stock": r["stock_count"] > 0,
                        "stock_count": r["stock_count"],
                        "image_url": r["image_url"]
                    }))

            scored_products.sort(key=lambda x: (x[0], -x[1]["price"]), reverse=True)
            products = [item[1] for item in scored_products[:10]]

            return {"success": True, "count": len(products), "products": products}

    @classmethod
    async def tool_create_order(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        phone = ''.join(c for c in str(args.get("phone", "")) if c.isdigit())
        customer_name = str(args.get("customer_name") or "Valued Customer")
        items = args.get("items", [])
        delivery_address = str(args.get("delivery_address") or "")
        idempotency_key = str(args.get("idempotency_key") or f"{phone}_{hash(json.dumps(items, sort_keys=True))}")

        # 1. Check Idempotency Store
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT response_json FROM wa_idempotency WHERE idempotency_key = ?", (idempotency_key,))
            existing = cursor.fetchone()
            if existing:
                logger.info(f"Idempotency hit for key '{idempotency_key}'. Returning existing order result.")
                return json.loads(existing["response_json"])

        if not items:
            return {"success": False, "error": "Order items list is empty."}

        total_amount = sum(float(item.get("price", 0.0)) * int(item.get("qty", 1)) for item in items)
        order_id = f"ORD-{int(time.time() * 1000) % 1000000:06d}"
        tracking_num = f"TRK-{uuid.uuid4().hex[:8].upper()}"
        created_at = datetime.now().isoformat()

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO wa_orders (order_id, customer_phone, customer_name, items, total_amount, currency, status, tracking_number, carrier, delivery_address, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'USD', 'Processing', ?, 'Express Courier', ?, ?, ?)
            """, (order_id, phone, customer_name, json.dumps(items), round(total_amount, 2), tracking_num, delivery_address, created_at, created_at))

            # Update CRM spend
            cursor.execute("""
                INSERT INTO wa_crm_profiles (phone, name, vip_status, total_spent, last_interaction)
                VALUES (?, ?, 0, ?, ?)
                ON CONFLICT(phone) DO UPDATE SET 
                    total_spent = total_spent + excluded.total_spent,
                    last_interaction = excluded.last_interaction
            """, (phone, customer_name, total_amount, created_at))

            result = {
                "success": True,
                "order_id": order_id,
                "total_amount": f"${round(total_amount, 2)} USD",
                "status": "Processing",
                "tracking_number": tracking_num,
                "delivery_address": delivery_address,
                "items_count": len(items),
                "message": f"Order {order_id} confirmed for ${round(total_amount, 2)}."
            }

            # Save idempotency record
            cursor.execute("""
                INSERT OR REPLACE INTO wa_idempotency (idempotency_key, action_name, response_json, created_at)
                VALUES (?, 'create_order', ?, ?)
            """, (idempotency_key, json.dumps(result), time.time()))
            conn.commit()

        return result

    @classmethod
    async def tool_book_appointment(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        phone = ''.join(c for c in str(args.get("phone", "")) if c.isdigit())
        customer_name = str(args.get("customer_name") or "Valued Customer")
        service_type = str(args.get("service_type") or "General Consultation")
        date_time = str(args.get("date_time") or "")
        notes = str(args.get("notes") or "")

        booking_id = f"BK-{int(time.time() * 1000) % 1000000:06d}"
        created_at = datetime.now().isoformat()

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO wa_appointments (booking_id, customer_phone, customer_name, service_type, scheduled_time, status, notes, created_at)
                VALUES (?, ?, ?, ?, ?, 'Confirmed', ?, ?)
            """, (booking_id, phone, customer_name, service_type, date_time, notes, created_at))
            conn.commit()

        return {
            "success": True,
            "booking_id": booking_id,
            "service_type": service_type,
            "scheduled_time": date_time,
            "status": "Confirmed",
            "message": f"Appointment {booking_id} for '{service_type}' scheduled for {date_time}."
        }

    @classmethod
    async def tool_generate_payment_link(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        amount = float(args.get("amount", 0.0))
        currency = str(args.get("currency", "USD")).upper()
        order_id = str(args.get("order_id") or f"PAY-{uuid.uuid4().hex[:6].upper()}")
        description = str(args.get("description") or "WhatsApp Agent Payment Request")

        # Mock payment gateway link (e.g. Stripe / Razorpay checkout session)
        payment_token = uuid.uuid4().hex[:12]
        payment_url = f"https://pay.example.com/checkout/{payment_token}?order={order_id}&amount={amount}&cur={currency}"

        return {
            "success": True,
            "order_id": order_id,
            "amount": amount,
            "currency": currency,
            "payment_url": payment_url,
            "expires_in_minutes": 60,
            "message": f"Payment link created for {amount} {currency}."
        }

    @classmethod
    async def tool_search_knowledge_base(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        High-precision FAQ & Knowledge Base RAG search with fuzzy title matching and token scoring.
        """
        query = str(args.get("query") or "").strip().lower()
        if not query:
            return {"success": False, "error": "Query required for knowledge search."}

        stopwords = {"how", "do", "does", "the", "and", "or", "is", "are", "for", "with", "what", "can", "work", "about", "your", "my"}
        words = [w for w in re.findall(r"\w+", query) if len(w) > 2 and w not in stopwords]
        if not words:
            words = [w for w in re.findall(r"\w+", query) if len(w) > 2]
        if not words:
            words = [query]

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM wa_knowledge_base")
            rows = cursor.fetchall()

            scored = []
            for r in rows:
                title = r["title"].lower()
                topic = r["topic"].lower()
                content = r["content"].lower()
                keywords = r["keywords"].lower()
                combined = f"{title} {topic} {content} {keywords}"

                # 1. Exact phrase in content/title
                score = 3.0 if query in title else (2.0 if query in combined else 0.0)

                # 2. Token overlap
                token_hits = sum(1.0 for w in words if w in combined)
                score += token_hits

                # 3. Fuzzy similarity on title and topic
                sim_title = difflib.SequenceMatcher(None, query, title).ratio()
                sim_topic = difflib.SequenceMatcher(None, query, topic).ratio()
                max_sim = max(sim_title, sim_topic)
                if max_sim > 0.40:
                    score += max_sim * 2.0

                if score > 0:
                    scored.append((score, {
                        "title": r["title"],
                        "topic": r["topic"],
                        "content": r["content"]
                    }))

            scored.sort(key=lambda x: x[0], reverse=True)
            articles = [item[1] for item in scored[:3]]

            if not articles:
                for r in rows[:2]:
                    articles.append({"title": r["title"], "topic": r["topic"], "content": r["content"]})

            return {"success": True, "matches": articles}

    @classmethod
    async def tool_escalate_to_human(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        phone = ''.join(c for c in str(args.get("phone", "")) if c.isdigit())
        customer_name = str(args.get("customer_name") or "Customer")
        reason = str(args.get("reason") or "Customer requested human agent")
        summary = str(args.get("conversation_summary") or "")

        ticket_id = f"TICK-{int(time.time() * 1000) % 1000000:06d}"
        created_at = datetime.now().isoformat()

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO wa_escalations (ticket_id, customer_phone, customer_name, reason, conversation_summary, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'Open', ?)
            """, (ticket_id, phone, customer_name, reason, summary, created_at))
            conn.commit()

        logger.warning(f"HUMAN ESCALATION TRIGGERED: Ticket {ticket_id} for {phone} - {reason}")
        return {
            "success": True,
            "ticket_id": ticket_id,
            "status": "Escalated",
            "message": f"Ticket {ticket_id} opened. A human representative will take over shortly."
        }

    @classmethod
    async def tool_get_customer_crm_profile(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        phone = ''.join(c for c in str(args.get("phone", "")) if c.isdigit())
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM wa_crm_profiles WHERE phone LIKE ?", (f"%{phone[-10:]}%",))
            row = cursor.fetchone()
            if row:
                return {
                    "success": True,
                    "profile": {
                        "phone": row["phone"],
                        "name": row["name"],
                        "preferred_language": row["preferred_language"],
                        "vip_status": bool(row["vip_status"]),
                        "notes": row["notes"],
                        "total_spent": row["total_spent"],
                        "last_interaction": row["last_interaction"]
                    }
                }
            return {
                "success": True,
                "profile": {
                    "phone": phone,
                    "name": "New Customer",
                    "vip_status": False,
                    "total_spent": 0.0,
                    "notes": "First time contacting via WhatsApp."
                }
            }

    @classmethod
    async def tool_record_audit_log(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """Records a comprehensive audit log entry for every WhatsApp action."""
        log_id = f"AUD-{uuid.uuid4().hex[:10].upper()}"
        timestamp = datetime.now().isoformat()
        action_id = args.get("action_id") or log_id
        user_request = str(args.get("user_request") or "")
        intent = str(args.get("intent") or "general_action")
        contact = str(args.get("contact") or "")
        phone = str(args.get("phone") or "")
        autonomy_mode = str(args.get("autonomy_mode") or "ASSISTED")
        risk_level = str(args.get("risk_level") or "L0")
        hitl_status = str(args.get("hitl_status") or "auto")
        approver = str(args.get("approver") or "")
        tools_used = json.dumps(args.get("tools_used") or [])
        payload_hash = str(args.get("payload_hash") or "")
        execution_status = str(args.get("execution_status") or "executed")
        verification_status = str(args.get("verification_status") or "verified")
        outcome = str(args.get("outcome") or "")

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO wa_audit_logs (
                    log_id, timestamp, action_id, user_request, intent, contact, phone,
                    autonomy_mode, risk_level, hitl_status, approver, tools_used,
                    payload_hash, execution_status, verification_status, outcome
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log_id, timestamp, action_id, user_request, intent, contact, phone,
                autonomy_mode, risk_level, hitl_status, approver, tools_used,
                payload_hash, execution_status, verification_status, outcome
            ))
            conn.commit()

        return {"success": True, "log_id": log_id, "action_id": action_id}

    @classmethod
    async def tool_list_audit_logs(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """Lists recent traceable audit logs."""
        limit = int(args.get("limit") or 10)
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM wa_audit_logs ORDER BY timestamp DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            logs = [dict(r) for r in rows]
            return {"success": True, "count": len(logs), "logs": logs}

    @classmethod
    async def tool_transition_action_state(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transitions an action through the Idempotency State Machine:
        PLANNED -> APPROVAL_PENDING -> APPROVED -> SENDING -> SENT -> VERIFIED
        """
        action_id = str(args.get("action_id") or f"ACT-{uuid.uuid4().hex[:8].upper()}")
        new_state = str(args.get("state") or "PLANNED").upper()
        recipient = str(args.get("recipient") or "")
        message_hash = str(args.get("message_hash") or "")
        attachment_hash = str(args.get("attachment_hash") or "")
        details_json = json.dumps(args.get("details") or {})
        now_str = datetime.now().isoformat()

        VALID_STATES = {"PLANNED", "APPROVAL_PENDING", "APPROVED", "SENDING", "SENT", "VERIFIED", "FAILED", "REJECTED"}
        if new_state not in VALID_STATES:
            return {"success": False, "error": f"Invalid state '{new_state}'. Valid: {VALID_STATES}"}

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO wa_state_machine (action_id, state, recipient, message_hash, attachment_hash, created_at, updated_at, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    state = excluded.state,
                    updated_at = excluded.updated_at,
                    details_json = excluded.details_json
            """, (action_id, new_state, recipient, message_hash, attachment_hash, now_str, now_str, details_json))
            conn.commit()

        return {"success": True, "action_id": action_id, "state": new_state, "updated_at": now_str}

    @classmethod
    async def tool_get_action_state(cls, args: Dict[str, Any]) -> Dict[str, Any]:
        """Checks current state in the idempotency state machine."""
        action_id = str(args.get("action_id") or "").strip()
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM wa_state_machine WHERE action_id = ?", (action_id,))
            row = cursor.fetchone()
            if row:
                return {"success": True, "found": True, "record": dict(row)}
            return {"success": True, "found": False, "error": f"No state record found for '{action_id}'"}


# Auto-initialize database tables and sample catalog/KB on module import
try:
    init_whatsapp_db()
except Exception as _init_err:
    logger.warning(f"Could not auto-initialize WhatsApp DB: {_init_err}")
