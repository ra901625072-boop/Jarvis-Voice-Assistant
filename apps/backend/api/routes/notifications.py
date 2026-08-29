from fastapi import APIRouter, Depends, HTTPException
from api.middleware.auth import get_current_user, require_role
from api.dependencies import get_memory
from modules.notification.notification_service import NotificationService
import os
import json
import logging

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])
logger = logging.getLogger("JARVIS.API.Notifications")

NOTIF_LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "database", "notifications_log.json"
)

def log_notification(notif_type: str, details: dict):
    try:
        os.makedirs(os.path.dirname(NOTIF_LOG_FILE), exist_ok=True)
        logs = []
        if os.path.exists(NOTIF_LOG_FILE):
            with open(NOTIF_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        
        from datetime import datetime
        details["timestamp"] = datetime.utcnow().isoformat()
        details["type"] = notif_type
        logs.append(details)
        
        with open(NOTIF_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs[-100:], f, indent=4) # keep last 100 logs
    except Exception as e:
        logger.error(f"Failed to log notification: {e}")

@router.get("")
async def get_notification_logs(current_user: dict = Depends(get_current_user)):
    if not os.path.exists(NOTIF_LOG_FILE):
        return {"notifications": []}
    try:
        with open(NOTIF_LOG_FILE, "r", encoding="utf-8") as f:
            return {"notifications": json.load(f)}
    except Exception:
        return {"notifications": []}

@router.post("")
async def trigger_notification(body: dict, current_user: dict = Depends(get_current_user), memory = Depends(get_memory)):
    notif_type = body.get("type", "webhook")
    title = body.get("title", "JARVIS Alert")
    message = body.get("message")
    
    if not message:
        raise HTTPException(status_code=400, detail="Missing required field: message")
        
    # Restrict webhooks to admins
    if notif_type == "webhook" and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can send webhook notifications")
        
    success = False
    if notif_type == "webhook":
        url = body.get("url", os.environ.get("JARVIS_NOTIFY_WEBHOOK"))
        if not url:
            raise HTTPException(status_code=400, detail="Webhook URL not supplied")
        success = NotificationService.send_webhook(url, title, message, body.get("status", "info"))
    elif notif_type == "email":
        recipient = body.get("recipient")
        if not recipient:
            username = current_user.get("sub")
            if username:
                conn = memory.dbs.get_conn()
                c = conn.cursor()
                c.execute("SELECT email FROM users WHERE username = ?", (username,))
                row = c.fetchone()
                if row and row[0]:
                    recipient = row[0]
        if not recipient:
            recipient = os.environ.get("JARVIS_NOTIFY_EMAIL")
        if not recipient:
            raise HTTPException(status_code=400, detail="Recipient email not supplied and not configured in profile")
            
        html_content = f"<h3>{title}</h3><p>{message}</p>"
        success = NotificationService.send_email(title, html_content, recipient)
    elif notif_type == "sms":
        recipient = body.get("recipient")
        if not recipient:
            username = current_user.get("sub")
            if username:
                conn = memory.dbs.get_conn()
                c = conn.cursor()
                c.execute("SELECT phone_number FROM users WHERE username = ?", (username,))
                row = c.fetchone()
                if row and row[0]:
                    recipient = row[0]
        if not recipient:
            raise HTTPException(status_code=400, detail="Recipient phone number not supplied and not configured in profile")
            
        success = NotificationService.send_sms(message, recipient)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported notification type: {notif_type}")
        
    log_notification(notif_type, {"title": title, "message": message, "success": success})
    return {"status": "success" if success else "failed"}
