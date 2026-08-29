from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.security.manager import SecurityManager
from modules.memory.manager import MemoryManager
from modules.notification.notification_service import NotificationService
import logging
import os

logger = logging.getLogger("JARVIS.Tools.Notification")

class NotificationTools(JarvisToolset):
    """
    NotificationTools exposes capabilities to dispatch alerts and messages via email and SMS.
    """
    def __init__(self, memory: MemoryManager, security: SecurityManager, room=None):
        super().__init__(security, room)
        self.memory = memory

    def _get_current_username(self) -> str:
        """Helper to get username of the active participant in the room."""
        if self.room:
            for p in self.room.remote_participants.values():
                if p.identity:
                    return p.identity
        return "admin"

    def _get_user_contact_info(self, username: str) -> tuple[str, str]:
        """Query database for user's email and phone number."""
        try:
            conn = self.memory.dbs.get_conn()
            c = conn.cursor()
            c.execute("SELECT email, phone_number FROM users WHERE username = ?", (username,))
            row = c.fetchone()
            if row:
                return row[0] or "", row[1] or ""
        except Exception as e:
            logger.error(f"Error querying user contact details for {username}: {e}")
        return "", ""

    @llm.function_tool(
        description=(
            "Send a notification alert, text message, SMS, email, or webhook to a recipient or contact. "
            "Supported channels are 'email', 'sms', and 'webhook'. "
            "The message parameter should contain the text content to send. "
            "The channel parameter must be set to 'sms' for text/mobile messages, 'email' for emails, and 'webhook' for webhooks. "
            "The recipient parameter can be a phone number (e.g. '9313840278'), an email address, or webhook url. "
            "If recipient is omitted, it automatically defaults to the current user's profile contact details."
        )
    )
    async def send_user_notification(
        self,
        message: str,
        title: str = "JARVIS Notification",
        channel: str = "email",
        recipient: str = None,
        confirmed: bool = False
    ) -> str:
        def _do_send():
            try:
                chan = channel.lower().strip()
                username = self._get_current_username()
                email, phone = self._get_user_contact_info(username)
                
                if chan == "email":
                    target = recipient or email or os.environ.get("JARVIS_NOTIFY_EMAIL")
                    if not target:
                        return "Error: Recipient email is not specified and no email is configured in your profile."
                    html_content = f"<h3>{title}</h3><p>{message}</p>"
                    success = NotificationService.send_email(title, html_content, target)
                    if success:
                        return f"Email notification successfully sent to {target} (simulated if SMTP credentials not configured)."
                    else:
                        return "Failed to send email. Check SMTP configuration settings."
                        
                elif chan == "sms":
                    target = recipient or phone
                    if not target:
                        return "Error: Recipient phone number is not specified and no phone number is configured in your profile."
                    success = NotificationService.send_sms(message, target)
                    if success:
                        return f"SMS notification successfully sent to {target} (simulated if Twilio credentials not configured)."
                    else:
                        return "Failed to send SMS."
                        
                elif chan == "webhook":
                    url = recipient or os.environ.get("JARVIS_NOTIFY_WEBHOOK")
                    if not url:
                        return "Error: Webhook URL is not specified and not set in environment."
                    success = NotificationService.send_webhook(url, title, message)
                    if success:
                        return "Webhook notification successfully dispatched."
                    else:
                        return "Failed to trigger webhook."
                else:
                    return f"Error: Unsupported notification channel '{chan}'. Supported channels: email, sms, webhook."
            except Exception as e:
                logger.error(f"Error in _do_send: {e}", exc_info=True)
                return f"Error executing notification tool: {e}"

        return await self.safe_execute(
            _do_send,
            confirmation_category="notify",
            confirmation_action=f"send {channel} notification",
            confirmed=confirmed,
        )
