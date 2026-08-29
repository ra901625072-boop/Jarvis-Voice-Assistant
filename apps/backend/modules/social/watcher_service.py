"""
watcher_service.py — Proactive Background Watcher & VIP Event Listener.

Continuously monitors connected social channels (Gmail, WhatsApp, Instagram) in the background,
evaluates message urgency against the ContactGraph VIP list, and triggers real-time
proactive voice announcements when urgent communication arrives.
"""
import asyncio
import logging
from typing import Dict, Any, Optional, Set, List
from datetime import datetime

from modules.task.events import task_event_bus
from ai.agents.types import AgentTask

logger = logging.getLogger("JARVIS.SocialWatcher")


class SocialWatcherService:
    """
    Background polling daemon for proactive social triage and VIP alerts.
    """

    def __init__(
        self,
        social_media_agent=None,
        contact_graph=None,
        poll_interval_seconds: int = 60
    ):
        self.agent = social_media_agent
        self.contact_graph = contact_graph
        self.poll_interval = poll_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._seen_ids: Set[str] = set()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"SocialWatcherService started (interval: {self.poll_interval}s).")

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("SocialWatcherService stopped.")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SocialWatcherService poll error: {e}")

            await asyncio.sleep(self.poll_interval)

    async def poll_once(self) -> List[Dict[str, Any]]:
        """
        Executes a single monitoring cycle across all connected channels.
        """
        if not self.agent:
            return []

        discovered_alerts = []

        # 1. Check Gmail Unread
        try:
            gmail_task = AgentTask(task_type="get_unread_emails", payload={"platform": "gmail", "limit": 5})
            g_res = await self.agent.handle(gmail_task)
            if g_res.success:
                messages = g_res.result.get("messages", [])
                for msg in messages:
                    msg_id = f"gmail_{msg.get('id')}"
                    if msg_id not in self._seen_ids:
                        self._seen_ids.add(msg_id)
                        sender = msg.get("from", "")
                        subject = msg.get("subject", "")
                        is_vip = self.contact_graph.is_vip(sender) if self.contact_graph else False

                        alert = {
                            "platform": "gmail",
                            "sender": sender,
                            "summary": subject,
                            "is_vip": is_vip,
                            "type": "email"
                        }
                        discovered_alerts.append(alert)
                        if is_vip:
                            self._announce_proactive_event(
                                f"Urgent email from VIP {sender}: '{subject}'"
                            )
        except Exception as e:
            logger.debug(f"Watcher Gmail check error: {e}")

        # 2. Check WhatsApp Unread
        try:
            wa_task = AgentTask(task_type="get_unread_chats", payload={"platform": "whatsapp", "limit": 5})
            wa_res = await self.agent.handle(wa_task)
            if wa_res.success:
                chats = wa_res.result.get("chats", [])
                for c in chats:
                    contact_name = c.get("contact", "")
                    last_msg = c.get("last_message", "")
                    wa_id = f"wa_{contact_name}_{last_msg[:20]}"
                    if wa_id not in self._seen_ids:
                        self._seen_ids.add(wa_id)
                        is_vip = self.contact_graph.is_vip(contact_name) if self.contact_graph else False

                        alert = {
                            "platform": "whatsapp",
                            "sender": contact_name,
                            "summary": last_msg,
                            "is_vip": is_vip,
                            "type": "chat"
                        }
                        discovered_alerts.append(alert)
                        if is_vip:
                            self._announce_proactive_event(
                                f"New WhatsApp message from VIP {contact_name}: '{last_msg}'"
                            )
        except Exception as e:
            logger.debug(f"Watcher WhatsApp check error: {e}")

        return discovered_alerts

    def _announce_proactive_event(self, text: str) -> None:
        """Publishes urgent event to TaskEventBus so TaskAnnouncer speaks to Akshay."""
        logger.info(f"PROACTIVE SOCIAL ALERT: {text}")
        task_event_bus.publish({
            "task_id": "social_watcher_alert",
            "status": "completed",
            "announce": True,
            "priority": "high",
            "speech_text": text,
            "result_summary": text,
            "timestamp": datetime.now().isoformat()
        })
