import os
import logging
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("JARVIS.Services.NotificationService")

class NotificationService:
    """
    Handles task alerts, Slack Webhooks, and SMTP/SendGrid email notifications.
    """
    @staticmethod
    def send_webhook(webhook_url: str, title: str, message: str, status: str = "info") -> bool:
        if not webhook_url:
            return False
        try:
            payload = {
                "text": f"*{title}*\nStatus: {status.upper()}\nMessage: {message}"
            }
            res = requests.post(webhook_url, json=payload, timeout=10)
            return res.status_code == 200
        except Exception as e:
            logger.error(f"Failed to dispatch webhook alert: {e}")
            return False

    @staticmethod
    def send_email(subject: str, html_content: str, recipient: str = None) -> bool:
        smtp_host = os.environ.get("JARVIS_SMTP_HOST")
        smtp_port = os.environ.get("JARVIS_SMTP_PORT", "587")
        smtp_user = os.environ.get("JARVIS_SMTP_USER")
        smtp_pass = os.environ.get("JARVIS_SMTP_PASS")
        sender = os.environ.get("JARVIS_SMTP_SENDER", "jarvis@localhost")
        recipient = recipient or os.environ.get("JARVIS_NOTIFY_EMAIL")

        if not (smtp_host and smtp_user and smtp_pass and recipient):
            if recipient:
                logger.warning(f"SMTP settings not configured. [SIMULATED EMAIL] To: {recipient}, Subject: {subject}, Content: {html_content}")
                return True
            logger.warning("SMTP settings not configured. Skipping email notification.")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = sender
            msg["To"] = recipient

            part = MIMEText(html_content, "html")
            msg.attach(part)

            server = smtplib.SMTP(smtp_host, int(smtp_port))
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(sender, [recipient], msg.as_string())
            server.quit()
            logger.info(f"Notification email sent successfully to {recipient}")
            return True
        except Exception as e:
            logger.error(f"Failed to dispatch notification email: {e}")
            return False

    @staticmethod
    def send_sms(message: str, recipient: str) -> bool:
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_FROM_NUMBER")
        
        if not recipient:
            logger.warning("No recipient phone number provided. Skipping SMS notification.")
            return False

        if not (account_sid and auth_token and from_number):
            logger.warning(f"SMS settings not configured. [SIMULATED SMS] To: {recipient}, Message: {message}")
            return True
            
        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
            data = {
                "To": recipient,
                "From": from_number,
                "Body": message
            }
            res = requests.post(url, data=data, auth=(account_sid, auth_token), timeout=10)
            if res.status_code in [200, 201]:
                logger.info(f"SMS notification sent successfully to {recipient}")
                return True
            else:
                logger.error(f"Twilio API returned status {res.status_code}: {res.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to dispatch SMS notification: {e}")
            return False
