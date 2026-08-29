import os
import uuid
import sqlite3
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse
from container import ServiceContainer

logger = logging.getLogger("JARVIS.Webhooks")
router = APIRouter(prefix="/api/social/webhook", tags=["Social Media Webhooks"])

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "contacts.db"))


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
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


# Initialize database table
init_db()


@router.get("/whatsapp", response_class=PlainTextResponse)
async def verify_whatsapp(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    token = os.environ.get("META_VERIFY_TOKEN") or os.environ.get("JARVIS_META_VERIFY_TOKEN", "jarvis_token")
    if hub_mode == "subscribe" and hub_verify_token == token:
        logger.info("WhatsApp webhook verification successful.")
        return hub_challenge
    logger.warning("WhatsApp webhook verification failed.")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


import hmac
import hashlib
import asyncio

_processed_message_ids = set()

def verify_meta_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """Validates X-Hub-Signature-256 against Meta App Secret."""
    app_secret = os.environ.get("META_APP_SECRET") or os.environ.get("JARVIS_META_APP_SECRET")
    if not app_secret or not signature_header:
        return True  # Permissive in dev if secret is not set
    if not signature_header.startswith("sha256="):
        return False
    expected_hash = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected_hash}", signature_header)


@router.post("/whatsapp")
async def handle_whatsapp_webhook(request: Request):
    raw_body = await request.body()
    sig_header = request.headers.get("X-Hub-Signature-256")
    
    if not verify_meta_signature(raw_body, sig_header):
        logger.warning("WhatsApp webhook signature verification failed.")
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    logger.debug(f"WhatsApp webhook received payload: {payload}")

    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                metadata = value.get("metadata", {})
                recipient = metadata.get("display_phone_number", "unknown")

                for msg in messages:
                    msg_id = msg.get("id", str(uuid.uuid4()))
                    
                    # Idempotency deduplication check
                    if msg_id in _processed_message_ids:
                        logger.info(f"Duplicate WhatsApp message_id '{msg_id}' ignored.")
                        continue
                    _processed_message_ids.add(msg_id)
                    if len(_processed_message_ids) > 5000:
                        _processed_message_ids.clear()

                    sender = msg.get("from")  # sender phone number
                    msg_type = msg.get("type", "text")
                    text = ""
                    media_info = {}

                    if msg_type == "text":
                        text = msg.get("text", {}).get("body", "")
                    elif msg_type == "interactive":
                        interactive = msg.get("interactive", {})
                        i_type = interactive.get("type")
                        if i_type == "button_reply":
                            text = interactive.get("button_reply", {}).get("title", "")
                        elif i_type == "list_reply":
                            text = interactive.get("list_reply", {}).get("title", "")
                        else:
                            text = "[Interactive Response]"
                    elif msg_type == "button":
                        text = msg.get("button", {}).get("text", "")
                    elif msg_type in ("audio", "voice"):
                        audio_obj = msg.get("audio") or msg.get("voice", {})
                        media_info = {
                            "media_id": audio_obj.get("id"),
                            "mime_type": audio_obj.get("mime_type", "audio/ogg"),
                            "voice": bool(audio_obj.get("voice", True))
                        }
                        text = "[Voice Note]"
                    elif msg_type == "image":
                        img_obj = msg.get("image", {})
                        media_info = {
                            "media_id": img_obj.get("id"),
                            "mime_type": img_obj.get("mime_type", "image/jpeg"),
                            "caption": img_obj.get("caption", "")
                        }
                        text = img_obj.get("caption", "[Image Attachment]")
                    elif msg_type == "document":
                        doc_obj = msg.get("document", {})
                        media_info = {
                            "media_id": doc_obj.get("id"),
                            "filename": doc_obj.get("filename", "document.pdf"),
                            "caption": doc_obj.get("caption", "")
                        }
                        text = doc_obj.get("caption", f"[Document: {doc_obj.get('filename')}]")
                    elif msg_type == "location":
                        loc_obj = msg.get("location", {})
                        media_info = {
                            "latitude": loc_obj.get("latitude"),
                            "longitude": loc_obj.get("longitude"),
                            "name": loc_obj.get("name", ""),
                            "address": loc_obj.get("address", "")
                        }
                        text = f"[Location: {loc_obj.get('name') or loc_obj.get('address') or 'Pin'}]"
                    else:
                        text = f"[{msg_type.upper()} attachment]"

                    timestamp = msg.get("timestamp", str(datetime.now().timestamp()))

                    # 1. Store in database
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute("""
                            INSERT OR REPLACE INTO social_inbound_messages (id, platform, sender, recipient, text, timestamp, message_id)
                            VALUES (?, 'whatsapp', ?, ?, ?, ?, ?)
                        """, (str(uuid.uuid4()), sender, recipient, text, timestamp, msg_id))

                    # 2. Asynchronously dispatch to Autonomous WhatsApp AI Agent
                    container = ServiceContainer.instance()
                    wa_agent = container.get_or_none("whatsapp_agent") if container else None
                    bus = container.get_or_none("agent_bus") if container else None

                    if wa_agent:
                        # Trigger direct autonomous reasoning & response in background
                        asyncio.create_task(wa_agent.process_inbound_message(
                            sender=sender,
                            text=text,
                            msg_type=msg_type,
                            media_info=media_info,
                            msg_id=msg_id,
                            recipient=recipient
                        ))
                    elif bus:
                        from ai.agents.types import AgentTask
                        task = AgentTask(
                            task_type="process_inbound_message",
                            payload={
                                "platform": "whatsapp",
                                "sender": sender,
                                "text": text,
                                "msg_type": msg_type,
                                "media_info": media_info,
                                "timestamp": timestamp,
                                "message_id": msg_id,
                                "recipient": recipient
                            }
                        )
                        asyncio.create_task(bus.dispatch(task))

    except Exception as e:
        logger.error(f"Error parsing WhatsApp webhook: {e}")

    return {"status": "success"}


@router.get("/instagram", response_class=PlainTextResponse)
async def verify_instagram(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge")
):
    token = os.environ.get("META_VERIFY_TOKEN") or os.environ.get("JARVIS_META_VERIFY_TOKEN", "jarvis_token")
    if hub_mode == "subscribe" and hub_verify_token == token:
        logger.info("Instagram webhook verification successful.")
        return hub_challenge
    logger.warning("Instagram webhook verification failed.")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


@router.post("/instagram")
async def handle_instagram_webhook(request: Request):
    payload = await request.json()
    logger.debug(f"Instagram webhook received payload: {payload}")

    try:
        entries = payload.get("entry", [])
        for entry in entries:
            messaging = entry.get("messaging", [])
            for msg_event in messaging:
                sender_id = msg_event.get("sender", {}).get("id")
                recipient_id = msg_event.get("recipient", {}).get("id")
                message = msg_event.get("message", {})
                msg_id = message.get("mid")
                text = message.get("text", "")

                # Check if it's not our own sent message echo
                if sender_id and message:
                    timestamp = str(msg_event.get("timestamp", str(datetime.now().timestamp())))

                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute("""
                            INSERT OR REPLACE INTO social_inbound_messages (id, platform, sender, recipient, text, timestamp, message_id)
                            VALUES (?, 'instagram', ?, ?, ?, ?, ?)
                        """, (str(uuid.uuid4()), sender_id, recipient_id, text, timestamp, msg_id))

                    # Dispatch to agent bus
                    container = ServiceContainer.instance()
                    bus = container.get_or_none("agent_bus") if container else None
                    if bus:
                        from ai.agents.types import AgentTask
                        task = AgentTask(
                            task_type="notify_inbound_message",
                            payload={
                                "platform": "instagram",
                                "sender": sender_id,
                                "text": text,
                                "timestamp": timestamp,
                                "message_id": msg_id
                            }
                        )
                        await bus.dispatch(task)

    except Exception as e:
        logger.error(f"Error parsing Instagram webhook: {e}")

    return {"status": "success"}
