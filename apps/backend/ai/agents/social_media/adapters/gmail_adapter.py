"""
gmail_adapter.py — Full-Access Google Gmail REST & IMAP/SMTP Client for JARVIS.

Provides complete email intelligence and human-grade automation:
- Full multipart body decoding (plain text, HTML) and header parsing
- Conversation thread inspection and chronological discussion context
- Advanced search operators (from, to, subject, has:attachment, date filters)
- Sending, replying (with In-Reply-To threading), and forwarding
- Draft creation, listing, sending, and deleting
- Labeling & triage: read/unread, starred, archiving, trashing, and custom labels
- Dual-engine fallback: Google OAuth2 REST API and Native App Password IMAP/SMTP.
"""
import os
import time
import base64
import logging
import asyncio
import imaplib
import smtplib
import email
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, Optional, List, Tuple
import aiohttp

from ai.agents.social_media.adapters.base_adapter import PlatformAdapter

logger = logging.getLogger("JARVIS.GmailAdapter")

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GmailAdapter(PlatformAdapter):
    """
    Full-Access Gmail Adapter using Google REST API with OAuth2 token management,
    with seamless native IMAP/SMTP App-Password fallback.
    """

    def __init__(self, credential_vault=None, max_requests_per_hour: int = 60):
        super().__init__(platform_name="gmail", max_requests_per_hour=max_requests_per_hour)
        self.vault = credential_vault

    def _get_app_credentials(self) -> Optional[Tuple[str, str]]:
        user = os.environ.get("JARVIS_SMTP_USER") or os.environ.get("GMAIL_USER") or os.environ.get("JARVIS_SMTP_SENDER")
        pwd = os.environ.get("JARVIS_SMTP_PASS") or os.environ.get("GMAIL_APP_PASSWORD") or os.environ.get("GMAIL_PASS")
        if user and pwd:
            return user.strip(), pwd.strip().replace(" ", "")
        return None

    async def _get_access_token(self) -> Optional[str]:
        """Fetch active access token from CredentialVault or environment, refreshing if needed."""
        tokens = self.vault.get_oauth_tokens("gmail") if self.vault else None
        
        # Fallback to environment variables if not in vault
        if not tokens:
            env_access = os.environ.get("GMAIL_ACCESS_TOKEN")
            env_refresh = os.environ.get("GMAIL_REFRESH_TOKEN")
            env_client_id = os.environ.get("GMAIL_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID")
            env_client_secret = os.environ.get("GMAIL_CLIENT_SECRET") or os.environ.get("GOOGLE_CLIENT_SECRET")
            if env_access or env_refresh:
                tokens = {
                    "access_token": env_access,
                    "refresh_token": env_refresh,
                    "client_id": env_client_id,
                    "client_secret": env_client_secret,
                    "expires_at": time.time() + 3600 if env_access else 0
                }

        if not tokens:
            return None

        access_token = tokens.get("access_token")
        expires_at = tokens.get("expires_at", 0)
        refresh_token = tokens.get("refresh_token")
        client_id = tokens.get("client_id") or os.environ.get("GMAIL_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID")
        client_secret = tokens.get("client_secret") or os.environ.get("GMAIL_CLIENT_SECRET") or os.environ.get("GOOGLE_CLIENT_SECRET")

        # Refresh if expired (or within 60s of expiring)
        if (not access_token or (expires_at and expires_at <= time.time() + 60)) and refresh_token and client_id and client_secret:
            refreshed = await self._refresh_token(refresh_token, client_id, client_secret)
            if refreshed and "access_token" in refreshed:
                access_token = refreshed["access_token"]
                new_expires = time.time() + float(refreshed.get("expires_in", 3600))
                tokens["access_token"] = access_token
                tokens["expires_at"] = new_expires
                if self.vault:
                    self.vault.store_oauth_tokens("gmail", tokens, expires_at=new_expires)

        return access_token

    async def _refresh_token(self, refresh_token: str, client_id: str, client_secret: str) -> Optional[Dict[str, Any]]:
        """Request new access token from Google OAuth endpoint."""
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(GOOGLE_TOKEN_URI, data=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info("Successfully refreshed Google OAuth token for Gmail.")
                        return data
                    else:
                        err_text = await resp.text()
                        logger.error(f"Failed to refresh Google OAuth token ({resp.status}): {err_text}")
                        return None
        except Exception as e:
            logger.error(f"Exception during Google OAuth refresh: {e}")
            return None

    async def connect(self, **kwargs) -> bool:
        token = await self._get_access_token()
        if token:
            return True
        app_creds = self._get_app_credentials()
        return bool(app_creds)

    async def disconnect(self) -> bool:
        if self.vault:
            return self.vault.revoke("gmail")
        return True

    async def health(self) -> Dict[str, Any]:
        token = await self._get_access_token()
        app_creds = self._get_app_credentials()
        connected = bool(token) or bool(app_creds)
        mode = "oauth2_rest" if token else ("imap_smtp_app_password" if app_creds else "none")
        user = app_creds[0] if app_creds else ("OAuth User" if token else None)
        return {
            "platform": "gmail",
            "connected": connected,
            "authenticated": connected,
            "mode": mode,
            "user": user,
            "rate_limit": self.get_rate_limit_status()
        }

    # ── MIME & Payload Helpers ────────────────────────────────────────────────

    def _decode_body_part(self, data_str: str) -> str:
        if not data_str:
            return ""
        try:
            padded = data_str + "=" * ((4 - len(data_str) % 4) % 4)
            return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"Failed decoding email body part: {e}")
            return ""

    def _parse_payload(self, payload: Dict[str, Any]) -> Tuple[str, str, List[Dict[str, Any]]]:
        text_plain = ""
        text_html = ""
        attachments = []

        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")
        filename = payload.get("filename", "")

        if filename:
            attachments.append({
                "filename": filename,
                "mimeType": mime_type,
                "size": payload.get("body", {}).get("size", 0),
                "attachmentId": payload.get("body", {}).get("attachmentId")
            })

        if body_data:
            decoded = self._decode_body_part(body_data)
            if "text/plain" in mime_type:
                text_plain += decoded
            elif "text/html" in mime_type:
                text_html += decoded
            elif not text_plain:
                text_plain += decoded

        for part in payload.get("parts", []):
            p_plain, p_html, p_att = self._parse_payload(part)
            if p_plain:
                text_plain += ("\n" + p_plain if text_plain else p_plain)
            if p_html:
                text_html += ("\n" + p_html if text_html else p_html)
            attachments.extend(p_att)

        return text_plain.strip(), text_html.strip(), attachments

    def _extract_headers_dict(self, payload: Dict[str, Any]) -> Dict[str, str]:
        headers_list = payload.get("headers", [])
        return {h.get("name", "").lower(): h.get("value", "") for h in headers_list}

    # ── Master Dispatcher ─────────────────────────────────────────────────────

    async def execute(self, task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        token = await self._get_access_token()
        app_creds = self._get_app_credentials()

        if not token and not app_creds:
            return {
                "success": False,
                "error": "Gmail is not connected. Please authenticate via OAuth (scripts/connect_gmail.py) or configure JARVIS_SMTP_USER & JARVIS_SMTP_PASS in .env."
            }

        # Enforce rate limits on mutations
        if task_type in ("send_email", "send_message", "reply_email", "forward_email", "send_draft", "trash_email", "delete_email"):
            allowed, err = await self.check_rate_limit()
            if not allowed:
                return {"success": False, "error": err}

        # ── REST API ENGINE (when OAuth token exists) ─────────────────────────
        if token:
            if task_type in ("read_inbox", "list_emails", "inbox"):
                return await self._read_inbox(token, payload)
            elif task_type in ("get_email_details", "read_email", "get_message"):
                return await self._get_email_details(token, payload)
            elif task_type in ("read_thread", "get_thread_messages", "thread_details"):
                return await self._read_thread(token, payload)
            elif task_type in ("search_emails", "search_conversation", "query_emails", "find_emails"):
                return await self._search_emails(token, payload)
            elif task_type in ("get_unread_emails", "unread_emails"):
                return await self._get_unread_emails(token, payload)
            elif task_type in ("get_starred_emails", "starred_emails"):
                return await self._get_starred_emails(token, payload)
            elif task_type in ("get_sent_emails", "sent_emails"):
                return await self._get_sent_emails(token, payload)
            elif task_type in ("get_attachment", "download_attachment"):
                return await self._get_attachment(token, payload)
            elif task_type in ("send_email", "send_message"):
                return await self._send_email(token, payload)
            elif task_type in ("reply_email", "reply"):
                return await self._reply_email(token, payload)
            elif task_type in ("forward_email", "forward"):
                return await self._forward_email(token, payload)
            elif task_type in ("create_draft", "draft_reply", "save_draft"):
                return await self._create_draft(token, payload)
            elif task_type in ("list_drafts", "get_drafts"):
                return await self._list_drafts(token, payload)
            elif task_type in ("send_draft",):
                return await self._send_draft(token, payload)
            elif task_type in ("delete_draft",):
                return await self._delete_draft(token, payload)
            elif task_type in ("mark_as_read", "read"):
                return await self._modify_labels(token, payload.get("message_id") or payload.get("id"), remove_labels=["UNREAD"])
            elif task_type in ("mark_as_unread", "unread"):
                return await self._modify_labels(token, payload.get("message_id") or payload.get("id"), add_labels=["UNREAD"])
            elif task_type in ("star_email", "star"):
                return await self._modify_labels(token, payload.get("message_id") or payload.get("id"), add_labels=["STARRED"])
            elif task_type in ("unstar_email", "unstar"):
                return await self._modify_labels(token, payload.get("message_id") or payload.get("id"), remove_labels=["STARRED"])
            elif task_type in ("archive_email", "archive"):
                return await self._modify_labels(token, payload.get("message_id") or payload.get("id"), remove_labels=["INBOX"])
            elif task_type in ("trash_email", "delete_email", "trash"):
                return await self._trash_email(token, payload)
            elif task_type in ("apply_label",):
                label_id = payload.get("label_id") or payload.get("label")
                return await self._modify_labels(token, payload.get("message_id") or payload.get("id"), add_labels=[label_id] if label_id else [])
            elif task_type in ("remove_label",):
                label_id = payload.get("label_id") or payload.get("label")
                return await self._modify_labels(token, payload.get("message_id") or payload.get("id"), remove_labels=[label_id] if label_id else [])
            elif task_type in ("list_labels", "labels"):
                return await self._list_labels(token)

        # ── NATIVE IMAP & SMTP ENGINE (App Password) ──────────────────────────
        user, pwd = app_creds
        if task_type in ("read_inbox", "list_emails", "inbox"):
            return await self._imap_fetch(user, pwd, query="ALL", limit=payload.get("limit", 10))
        elif task_type in ("get_unread_emails", "unread_emails"):
            return await self._imap_fetch(user, pwd, query="UNSEEN", limit=payload.get("limit", 10), unread_only=True)
        elif task_type in ("search_emails", "search_conversation", "query_emails", "find_emails"):
            q = payload.get("query") or payload.get("q") or "ALL"
            return await self._imap_search(user, pwd, q, limit=payload.get("limit", 10))
        elif task_type in ("get_email_details", "read_email", "get_message"):
            msg_id = payload.get("message_id") or payload.get("id")
            return await self._imap_get_details(user, pwd, msg_id)
        elif task_type in ("send_email", "send_message", "reply_email", "forward_email"):
            return await self._smtp_send(user, pwd, payload)
        elif task_type in ("mark_as_read", "read"):
            msg_id = payload.get("message_id") or payload.get("id")
            return await self._imap_set_flags(user, pwd, msg_id, add_flags=[r"\Seen"])
        elif task_type in ("mark_as_unread", "unread"):
            msg_id = payload.get("message_id") or payload.get("id")
            return await self._imap_set_flags(user, pwd, msg_id, remove_flags=[r"\Seen"])
        elif task_type in ("star_email", "star"):
            msg_id = payload.get("message_id") or payload.get("id")
            return await self._imap_set_flags(user, pwd, msg_id, add_flags=[r"\Flagged"])
        elif task_type in ("trash_email", "delete_email", "trash"):
            msg_id = payload.get("message_id") or payload.get("id")
            return await self._imap_set_flags(user, pwd, msg_id, add_flags=[r"\Deleted"])

        return {
            "success": False,
            "error": f"GmailAdapter does not support task type '{task_type}'"
        }

    # ── IMAP / SMTP Native Methods ────────────────────────────────────────────

    def _decode_hdr(self, val: Any) -> str:
        if not val:
            return ""
        try:
            parts = decode_header(str(val))
            res = []
            for t, c in parts:
                if isinstance(t, bytes):
                    res.append(t.decode(c or "utf-8", errors="replace"))
                else:
                    res.append(str(t))
            return "".join(res)
        except Exception:
            return str(val)

    def _sync_imap_fetch(self, user: str, pwd: str, search_crit: str, limit: int, unread_only: bool) -> List[Dict[str, Any]]:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(user, pwd)
        mail.select("INBOX")
        status, data = mail.search(None, search_crit)
        if status != "OK" or not data[0]:
            mail.logout()
            return []

        ids = data[0].split()
        selected = ids[-limit:]
        selected.reverse()

        messages = []
        for mid in selected:
            res, msg_data = mail.fetch(mid, "(RFC822)")
            if res != "OK" or not msg_data:
                continue
            for rpart in msg_data:
                if isinstance(rpart, tuple):
                    msg = email.message_from_bytes(rpart[1])
                    subject = self._decode_hdr(msg.get("Subject", "(No Subject)"))
                    sender = self._decode_hdr(msg.get("From", "Unknown"))
                    date_str = msg.get("Date", "")
                    
                    body_text = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            ctype = part.get_content_type()
                            cdispo = str(part.get("Content-Disposition"))
                            if ctype == "text/plain" and "attachment" not in cdispo:
                                p_bytes = part.get_payload(decode=True)
                                if p_bytes:
                                    body_text += p_bytes.decode(part.get_content_charset() or "utf-8", errors="replace")
                    else:
                        p_bytes = msg.get_payload(decode=True)
                        if p_bytes:
                            body_text = p_bytes.decode(msg.get_content_charset() or "utf-8", errors="replace")

                    messages.append({
                        "id": mid.decode("utf-8") if isinstance(mid, bytes) else str(mid),
                        "subject": subject,
                        "from": sender,
                        "date": date_str,
                        "body_snippet": body_text[:250].strip(),
                        "body_text": body_text.strip(),
                        "unread": unread_only
                    })
        mail.logout()
        return messages

    async def _imap_fetch(self, user: str, pwd: str, query: str = "ALL", limit: int = 10, unread_only: bool = False) -> Dict[str, Any]:
        try:
            crit = "UNSEEN" if unread_only else "ALL"
            msgs = await asyncio.to_thread(self._sync_imap_fetch, user, pwd, crit, limit, unread_only)
            self.record_action()
            return {
                "success": True,
                "platform": "gmail",
                "mode": "imap",
                "count": len(msgs),
                "messages": msgs
            }
        except Exception as e:
            logger.exception("Failed fetching emails via IMAP")
            return {"success": False, "error": str(e)}

    async def _imap_search(self, user: str, pwd: str, query_str: str, limit: int = 10) -> Dict[str, Any]:
        try:
            # Format IMAP query criteria
            clean_q = query_str.lower()
            if "from:" in clean_q:
                sender = clean_q.split("from:")[1].split()[0].strip()
                crit = f'(FROM "{sender}")'
            elif "subject:" in clean_q:
                subj = clean_q.split("subject:")[1].split()[0].strip()
                crit = f'(SUBJECT "{subj}")'
            else:
                crit = f'(TEXT "{query_str}")'

            msgs = await asyncio.to_thread(self._sync_imap_fetch, user, pwd, crit, limit, False)
            self.record_action()
            return {
                "success": True,
                "platform": "gmail",
                "mode": "imap_search",
                "query": query_str,
                "count": len(msgs),
                "messages": msgs
            }
        except Exception as e:
            logger.exception(f"Failed searching Gmail IMAP for '{query_str}'")
            return {"success": False, "error": str(e)}

    async def _imap_get_details(self, user: str, pwd: str, msg_id: str) -> Dict[str, Any]:
        if not msg_id:
            return {"success": False, "error": "message_id is required"}

        def _fetch_single():
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            mail.login(user, pwd)
            mail.select("INBOX")
            res, msg_data = mail.fetch(str(msg_id).encode("utf-8"), "(RFC822)")
            if res != "OK" or not msg_data:
                mail.logout()
                return None
            msg = email.message_from_bytes(msg_data[0][1])
            subj = self._decode_hdr(msg.get("Subject", "(No Subject)"))
            sender = self._decode_hdr(msg.get("From", "Unknown"))
            to_val = self._decode_hdr(msg.get("To", ""))
            date_val = msg.get("Date", "")
            
            body_text = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        b = part.get_payload(decode=True)
                        if b:
                            body_text += b.decode(part.get_content_charset() or "utf-8", errors="replace")
            else:
                b = msg.get_payload(decode=True)
                if b:
                    body_text = b.decode(msg.get_content_charset() or "utf-8", errors="replace")
            mail.logout()
            return {
                "id": str(msg_id),
                "subject": subj,
                "from": sender,
                "to": to_val,
                "date": date_val,
                "body_text": body_text.strip(),
                "body_snippet": body_text[:300].strip()
            }

        try:
            details = await asyncio.to_thread(_fetch_single)
            if not details:
                return {"success": False, "error": f"Message '{msg_id}' not found"}
            self.record_action()
            return {"success": True, "platform": "gmail", "message": details}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _smtp_send(self, user: str, pwd: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        to = payload.get("to") or payload.get("recipient")
        subject = payload.get("subject", "No Subject")
        body = payload.get("body") or payload.get("text", "")
        if not to or not body:
            return {"success": False, "error": "Both 'to' and 'body' are required"}

        def _send():
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = user
            msg["To"] = to

            smtp_host = os.environ.get("JARVIS_SMTP_HOST", "smtp.gmail.com")
            smtp_port = int(os.environ.get("JARVIS_SMTP_PORT", 587))
            
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(user, pwd)
                server.send_message(msg)

        try:
            await asyncio.to_thread(_send)
            self.record_action()
            return {
                "success": True,
                "platform": "gmail",
                "status": "sent",
                "recipient": to,
                "subject": subject
            }
        except Exception as e:
            logger.exception("Failed sending email via SMTP")
            return {"success": False, "error": str(e)}

    async def _imap_set_flags(self, user: str, pwd: str, msg_id: str, add_flags: List[str] = None, remove_flags: List[str] = None) -> Dict[str, Any]:
        if not msg_id:
            return {"success": False, "error": "message_id is required"}

        def _modify():
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            mail.login(user, pwd)
            mail.select("INBOX")
            if add_flags:
                for f in add_flags:
                    mail.store(str(msg_id).encode("utf-8"), "+FLAGS", f)
            if remove_flags:
                for f in remove_flags:
                    mail.store(str(msg_id).encode("utf-8"), "-FLAGS", f)
            mail.logout()

        try:
            await asyncio.to_thread(_modify)
            self.record_action()
            return {"success": True, "platform": "gmail", "message_id": msg_id, "modified": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── 1. Read & Search REST Operations ──────────────────────────────────────

    async def _read_inbox(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        limit = min(payload.get("limit", 10), 50)
        query = payload.get("query", "label:INBOX")

        headers = {"Authorization": f"Bearer {token}"}
        url = f"{GMAIL_API_BASE}/messages?maxResults={limit}&q={query}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        return {"success": False, "error": f"Failed to list messages ({resp.status}): {err_text}"}

                    data = await resp.json()
                    msg_refs = data.get("messages", [])

                    messages = []
                    for ref in msg_refs:
                        m_id = ref["id"]
                        m_url = f"{GMAIL_API_BASE}/messages/{m_id}?format=full"
                        async with session.get(m_url, headers=headers) as m_resp:
                            if m_resp.status == 200:
                                m_data = await m_resp.json()
                                headers_dict = self._extract_headers_dict(m_data.get("payload", {}))
                                plain, html, attachments = self._parse_payload(m_data.get("payload", {}))
                                messages.append({
                                    "id": m_id,
                                    "thread_id": m_data.get("threadId"),
                                    "subject": headers_dict.get("subject", "(No Subject)"),
                                    "from": headers_dict.get("from", "Unknown"),
                                    "to": headers_dict.get("to", ""),
                                    "date": headers_dict.get("date", ""),
                                    "snippet": m_data.get("snippet", ""),
                                    "body": plain,
                                    "body_plain": plain,
                                    "unread": "UNREAD" in m_data.get("labelIds", []),
                                    "labels": m_data.get("labelIds", []),
                                    "has_attachments": len(attachments) > 0,
                                    "attachments": attachments
                                })

                    self.record_action()
                    return {
                        "success": True,
                        "platform": "gmail",
                        "count": len(messages),
                        "messages": messages
                    }
        except Exception as e:
            logger.exception("Failed reading Gmail inbox")
            return {"success": False, "error": str(e)}

    async def _get_unread_emails(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        p = dict(payload)
        p["query"] = "is:unread label:INBOX"
        return await self._read_inbox(token, p)

    async def _get_starred_emails(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        p = dict(payload)
        p["query"] = "is:starred"
        return await self._read_inbox(token, p)

    async def _get_sent_emails(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        p = dict(payload)
        p["query"] = "label:SENT"
        return await self._read_inbox(token, p)

    async def _search_emails(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        query = payload.get("query") or payload.get("q") or ""
        limit = min(payload.get("limit", 10), 30)
        return await self._read_inbox(token, {"query": query, "limit": limit})

    async def _get_email_details(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        msg_id = payload.get("message_id") or payload.get("id")
        if not msg_id:
            return {"success": False, "error": "message_id is required"}

        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GMAIL_API_BASE}/messages/{msg_id}?format=full"
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return {"success": False, "error": f"Failed fetching message ({resp.status}): {text}"}

                    data = await resp.json()
                    headers_dict = self._extract_headers_dict(data.get("payload", {}))
                    plain, html, attachments = self._parse_payload(data.get("payload", {}))

                    self.record_action()
                    return {
                        "success": True,
                        "platform": "gmail",
                        "message_id": msg_id,
                        "thread_id": data.get("threadId"),
                        "subject": headers_dict.get("subject", ""),
                        "from": headers_dict.get("from", ""),
                        "to": headers_dict.get("to", ""),
                        "date": headers_dict.get("date", ""),
                        "snippet": data.get("snippet", ""),
                        "body": plain,
                        "body_text": plain,
                        "body_plain": plain,
                        "body_html": html,
                        "labels": data.get("labelIds", []),
                        "attachments": attachments
                    }
        except Exception as e:
            logger.exception(f"Failed getting Gmail details for {msg_id}")
            return {"success": False, "error": str(e)}

    async def _read_thread(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        thread_id = payload.get("thread_id") or payload.get("id")
        if not thread_id:
            return {"success": False, "error": "thread_id is required"}

        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GMAIL_API_BASE}/threads/{thread_id}?format=full"
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return {"success": False, "error": f"Failed fetching thread ({resp.status}): {text}"}

                    data = await resp.json()
                    messages = []
                    for m in data.get("messages", []):
                        h_dict = self._extract_headers_dict(m.get("payload", {}))
                        plain, html, atts = self._parse_payload(m.get("payload", {}))
                        messages.append({
                            "id": m["id"],
                            "from": h_dict.get("from", ""),
                            "to": h_dict.get("to", ""),
                            "date": h_dict.get("date", ""),
                            "snippet": m.get("snippet", ""),
                            "body": plain,
                            "body_plain": plain
                        })

                    self.record_action()
                    return {
                        "success": True,
                        "platform": "gmail",
                        "thread_id": thread_id,
                        "count": len(messages),
                        "message_count": len(messages),
                        "messages": messages
                    }
        except Exception as e:
            logger.exception(f"Failed reading Gmail thread {thread_id}")
            return {"success": False, "error": str(e)}

    async def _get_attachment(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        msg_id = payload.get("message_id")
        att_id = payload.get("attachment_id")
        if not msg_id or not att_id:
            return {"success": False, "error": "Both message_id and attachment_id are required"}

        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GMAIL_API_BASE}/messages/{msg_id}/attachments/{att_id}"
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return {"success": False, "error": f"Failed downloading attachment ({resp.status}): {text}"}

                    data = await resp.json()
                    self.record_action()
                    return {
                        "success": True,
                        "platform": "gmail",
                        "size": data.get("size"),
                        "data_base64": data.get("data")
                    }
        except Exception as e:
            logger.exception("Failed getting attachment from Gmail")
            return {"success": False, "error": str(e)}

    # ── 2. Compose, Reply & Forward REST Operations ───────────────────────────

    def _build_mime_message(self, to: str, subject: str, body: str, html_body: Optional[str] = None, in_reply_to: Optional[str] = None) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        part1 = MIMEText(body, "plain", "utf-8")
        msg.attach(part1)

        if html_body:
            part2 = MIMEText(html_body, "html", "utf-8")
            msg.attach(part2)

        return msg

    async def _send_email(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        to = payload.get("to") or payload.get("recipient")
        subject = payload.get("subject", "No Subject")
        body = payload.get("body") or payload.get("text", "")
        html_body = payload.get("html")

        if not to or not body:
            return {"success": False, "error": "Both 'to' and 'body' are required"}

        mime_msg = self._build_mime_message(to, subject, body, html_body)
        raw_msg = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GMAIL_API_BASE}/messages/send"
                async with session.post(url, headers=headers, json={"raw": raw_msg}) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        self.record_action()
                        return {
                            "success": True,
                            "platform": "gmail",
                            "status": "sent",
                            "message_id": data.get("id"),
                            "thread_id": data.get("threadId"),
                            "recipient": to,
                            "subject": subject
                        }
                    else:
                        text = await resp.text()
                        return {"success": False, "error": f"Failed sending email ({resp.status}): {text}"}
        except Exception as e:
            logger.exception("Failed sending email via Gmail")
            return {"success": False, "error": str(e)}

    async def _reply_email(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        msg_id = payload.get("message_id")
        reply_body = payload.get("body") or payload.get("text", "")
        if not msg_id or not reply_body:
            return {"success": False, "error": "Both 'message_id' and 'body' are required"}

        # Fetch original email for subject and sender
        details = await self._get_email_details(token, {"message_id": msg_id})
        if not details.get("success"):
            return details

        to = details.get("from")
        orig_subject = details.get("subject", "")
        subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"
        thread_id = details.get("thread_id")

        mime_msg = self._build_mime_message(to, subject, reply_body, in_reply_to=msg_id)
        raw_msg = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body_payload = {"raw": raw_msg, "threadId": thread_id}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GMAIL_API_BASE}/messages/send"
                async with session.post(url, headers=headers, json=body_payload) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        self.record_action()
                        return {
                            "success": True,
                            "platform": "gmail",
                            "status": "sent",
                            "message_id": data.get("id"),
                            "thread_id": thread_id,
                            "recipient": to,
                            "subject": subject
                        }
                    else:
                        text = await resp.text()
                        return {"success": False, "error": f"Failed replying to email ({resp.status}): {text}"}
        except Exception as e:
            logger.exception("Failed replying to Gmail message")
            return {"success": False, "error": str(e)}

    async def _forward_email(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        msg_id = payload.get("message_id")
        to = payload.get("to")
        note = payload.get("note", "")
        if not msg_id or not to:
            return {"success": False, "error": "Both 'message_id' and 'to' are required"}

        details = await self._get_email_details(token, {"message_id": msg_id})
        if not details.get("success"):
            return details

        orig_subject = details.get("subject", "")
        subject = f"Fwd: {orig_subject}" if not orig_subject.lower().startswith("fwd:") else orig_subject
        orig_body = details.get("body_plain", "")

        fwd_content = f"{note}\n\n---------- Forwarded message ---------\nFrom: {details.get('from')}\nDate: {details.get('date')}\nSubject: {orig_subject}\nTo: {details.get('to')}\n\n{orig_body}"

        return await self._send_email(token, {"to": to, "subject": subject, "body": fwd_content})

    # ── 3. Draft REST Operations ──────────────────────────────────────────────

    async def _create_draft(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        to = payload.get("to") or payload.get("recipient", "")
        subject = payload.get("subject", "Draft Subject")
        body = payload.get("body") or payload.get("text", "")

        mime_msg = self._build_mime_message(to, subject, body)
        raw_msg = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GMAIL_API_BASE}/drafts"
                async with session.post(url, headers=headers, json={"message": {"raw": raw_msg}}) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        self.record_action()
                        return {
                            "success": True,
                            "platform": "gmail",
                            "status": "draft_created",
                            "draft_id": data.get("id"),
                            "message_id": data.get("message", {}).get("id")
                        }
                    else:
                        text = await resp.text()
                        return {"success": False, "error": f"Failed creating draft ({resp.status}): {text}"}
        except Exception as e:
            logger.exception("Failed creating Gmail draft")
            return {"success": False, "error": str(e)}

    async def _list_drafts(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GMAIL_API_BASE}/drafts"
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.record_action()
                        return {"success": True, "platform": "gmail", "drafts": data.get("drafts", [])}
                    else:
                        text = await resp.text()
                        return {"success": False, "error": f"Failed listing drafts ({resp.status}): {text}"}
        except Exception as e:
            logger.exception("Failed listing Gmail drafts")
            return {"success": False, "error": str(e)}

    async def _send_draft(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        draft_id = payload.get("draft_id") or payload.get("id")
        if not draft_id:
            return {"success": False, "error": "draft_id is required"}

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GMAIL_API_BASE}/drafts/send"
                async with session.post(url, headers=headers, json={"id": draft_id}) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        self.record_action()
                        return {"success": True, "platform": "gmail", "status": "sent", "message_id": data.get("id")}
                    else:
                        text = await resp.text()
                        return {"success": False, "error": f"Failed sending draft ({resp.status}): {text}"}
        except Exception as e:
            logger.exception("Failed sending Gmail draft")
            return {"success": False, "error": str(e)}

    async def _delete_draft(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        draft_id = payload.get("draft_id") or payload.get("id")
        if not draft_id:
            return {"success": False, "error": "draft_id is required"}

        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GMAIL_API_BASE}/drafts/{draft_id}"
                async with session.delete(url, headers=headers) as resp:
                    if resp.status in (200, 204):
                        self.record_action()
                        return {"success": True, "platform": "gmail", "status": "deleted", "draft_id": draft_id}
                    else:
                        text = await resp.text()
                        return {"success": False, "error": f"Failed deleting draft ({resp.status}): {text}"}
        except Exception as e:
            logger.exception("Failed deleting Gmail draft")
            return {"success": False, "error": str(e)}

    # ── 4. Labeling & Triage REST Operations ──────────────────────────────────

    async def _modify_labels(self, token: str, msg_id: str, add_labels: List[str] = None, remove_labels: List[str] = None) -> Dict[str, Any]:
        if not msg_id:
            return {"success": False, "error": "message_id is required"}

        body = {
            "addLabelIds": add_labels or [],
            "removeLabelIds": remove_labels or []
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GMAIL_API_BASE}/messages/{msg_id}/modify"
                async with session.post(url, headers=headers, json=body) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.record_action()
                        return {
                            "success": True,
                            "platform": "gmail",
                            "message_id": msg_id,
                            "current_labels": data.get("labelIds", [])
                        }
                    else:
                        text = await resp.text()
                        return {"success": False, "error": f"Failed modifying labels ({resp.status}): {text}"}
        except Exception as e:
            logger.exception("Failed modifying Gmail labels")
            return {"success": False, "error": str(e)}

    async def _trash_email(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        msg_id = payload.get("message_id") or payload.get("id")
        if not msg_id:
            return {"success": False, "error": "message_id is required"}

        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GMAIL_API_BASE}/messages/{msg_id}/trash"
                async with session.post(url, headers=headers) as resp:
                    if resp.status == 200:
                        self.record_action()
                        return {"success": True, "platform": "gmail", "message_id": msg_id, "status": "trashed"}
                    else:
                        text = await resp.text()
                        return {"success": False, "error": f"Failed trashing message ({resp.status}): {text}"}
        except Exception as e:
            logger.exception("Failed trashing Gmail message")
            return {"success": False, "error": str(e)}

    async def _list_labels(self, token: str) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{GMAIL_API_BASE}/labels"
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {"success": True, "platform": "gmail", "labels": data.get("labels", [])}
                    else:
                        text = await resp.text()
                        return {"success": False, "error": f"Failed listing labels ({resp.status}): {text}"}
        except Exception as e:
            logger.exception("Failed listing Gmail labels")
            return {"success": False, "error": str(e)}
