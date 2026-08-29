"""
tools/builtin/social/tool.py — SocialMediaTools for LiveKit Voice & Text Assistant.

Exposes high-level social media connection, inspection, and messaging tools
to the voice assistant for WhatsApp, Instagram, Gmail, and LinkedIn.
"""
import logging
import os
from typing import Optional
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.security.manager import SecurityManager
from container import ServiceContainer
from ai.agents.types import AgentTask

logger = logging.getLogger("JARVIS.SocialMediaTools")


class SocialMediaTools(JarvisToolset):
    """
    SocialMediaTools manages social media connections and interactions across
    WhatsApp, Instagram, Gmail, and LinkedIn.
    """

    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)

    def _get_agent(self):
        c = ServiceContainer.instance()
        return c.get_or_none("social_media_agent") if c else None

    def _get_whatsapp_agent(self):
        c = ServiceContainer.instance()
        return c.get_or_none("whatsapp_agent") if c else None

    def _get_gmail_agent(self):
        c = ServiceContainer.instance()
        return c.get_or_none("gmail_agent") if c else None

    def _get_instagram_agent(self):
        c = ServiceContainer.instance()
        return c.get_or_none("instagram_agent") if c else None

    def _get_browser(self):
        c = ServiceContainer.instance()
        browser = c.get_or_none("browser_controller") if c else None
        if browser is None:
            from modules.controls.browser_controller import BrowserController
            browser = BrowserController()
        return browser

    @llm.function_tool(
        description="Connect, log in, or authenticate a social media account: whatsapp, instagram, gmail, or linkedin. Opens WhatsApp Web for QR scan or Instagram/LinkedIn in browser."
    )
    async def connect_social_account(self, platform: str) -> str:
        """Connect or log in to a social media platform."""
        p = platform.lower().strip()
        if p not in ("whatsapp", "instagram", "gmail", "linkedin"):
            return f"Unsupported platform '{platform}'. Please choose from whatsapp, instagram, gmail, or linkedin."

        agent = self._get_agent()
        browser = self._get_browser()

        if p == "whatsapp":
            if browser:
                try:
                    await browser._ensure_driver()
                    page = None
                    if browser.context:
                        for pg in browser.context.pages:
                            if "web.whatsapp.com" in pg.url:
                                page = pg
                                break
                        if not page:
                            page = await browser.context.new_page()
                            await page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")
                    
                    if page:
                        try:
                            await page.bring_to_front()
                        except Exception:
                            pass
                        try:
                            from container import ServiceContainer
                            c = ServiceContainer.instance()
                            wc = c.get_or_none("window_controller") if c else None
                            if wc:
                                wc.focus_window("WhatsApp") or wc.focus_window("Chrome") or wc.focus_window("Edge")
                        except Exception:
                            pass

                        try:
                            await page.wait_for_selector("#pane-side, div[id='side'], header[data-testid='chatlist-header'], div[role='grid'], canvas[aria-label*='Scan'], div[data-ref]", timeout=8000)
                        except Exception:
                            pass

                        is_logged_in = await page.query_selector("#pane-side, div[id='side'], header[data-testid='chatlist-header'], div[role='grid'], div[data-testid='chat-list']")
                        if is_logged_in:
                            return "WhatsApp Web is already connected and active. You can now ask me to read chats, check unread messages, or send messages."
                        return "Opening WhatsApp Web on screen in JARVIS dedicated browser. Please scan the QR code using your phone (WhatsApp -> Settings -> Linked Devices -> Link a Device). Once scanned, your session will be saved automatically."
                except Exception as e:
                    logger.error(f"Error opening WhatsApp Web: {e}")
                    return f"Failed to open WhatsApp Web in separate browser: {e}"

            return "Opening WhatsApp Web in JARVIS separate browser. Please scan the QR code with your phone to connect."

        elif p == "instagram":
            if browser:
                try:
                    await browser._ensure_driver()
                    page = None
                    if browser.context:
                        for pg in browser.context.pages:
                            if "instagram.com" in pg.url:
                                page = pg
                                break
                        if not page:
                            page = await browser.context.new_page()
                            await page.goto("https://www.instagram.com", wait_until="domcontentloaded")

                    if page:
                        try:
                            await page.bring_to_front()
                        except Exception:
                            pass
                        try:
                            from container import ServiceContainer
                            c = ServiceContainer.instance()
                            wc = c.get_or_none("window_controller") if c else None
                            if wc:
                                wc.focus_window("Instagram") or wc.focus_window("Chrome") or wc.focus_window("Edge")
                        except Exception:
                            pass

                        try:
                            await page.wait_for_selector("a[href*='/direct/inbox/'], svg[aria-label='Direct'], svg[aria-label='Messenger'], input[name='username']", timeout=5000)
                        except Exception:
                            pass

                        login_form = await page.query_selector("input[name='username'], input[name='password']")
                        logged_in_elem = await page.query_selector("a[href*='/direct/inbox/'], svg[aria-label='Direct'], svg[aria-label='Messenger'], a[href*='/explore/'], svg[aria-label='Home']")

                        is_logged_in = bool(logged_in_elem) and not bool(login_form)
                        if is_logged_in:
                            return "Instagram is already connected and active. You can now search profiles, check DMs, or see recent followers."
                        return "Opening Instagram on screen in JARVIS dedicated browser. Please log into your account in the browser. Once logged in, your session will be saved automatically."
                except Exception as e:
                    logger.error(f"Error opening Instagram: {e}")
                    return f"Failed to open Instagram in separate browser: {e}"

            return "Opening Instagram in JARVIS separate browser. Please log in to connect."

        elif p == "gmail":
            if agent and "gmail" in agent.adapters:
                h = await agent.adapters["gmail"].health()
                if h.get("connected"):
                    return "Gmail is already connected and authenticated via OAuth."
            return "Gmail requires Google OAuth credentials in your .env (GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN) or via the API."

        elif p == "linkedin":
            if browser:
                try:
                    await browser._ensure_driver()
                    if browser.context:
                        page = await browser.context.new_page()
                        await page.goto("https://www.linkedin.com", wait_until="domcontentloaded")
                        try:
                            await page.bring_to_front()
                        except Exception:
                            pass
                        try:
                            from container import ServiceContainer
                            c = ServiceContainer.instance()
                            wc = c.get_or_none("window_controller") if c else None
                            if wc:
                                wc.focus_window("LinkedIn") or wc.focus_window("Chrome") or wc.focus_window("Edge")
                        except Exception:
                            pass
                        return "Opening LinkedIn on screen in JARVIS dedicated browser. Please log in to your account. Your session will be saved automatically."
                except Exception as e:
                    logger.error(f"Error opening LinkedIn: {e}")
                    return f"Failed to open LinkedIn in separate browser: {e}"

            return "Opening LinkedIn in JARVIS separate browser. Please log in to authenticate."

        return f"Initiated connection for {platform}."

    @llm.function_tool(
        description="Check connection status and health for all social media accounts (Gmail, WhatsApp, Instagram, LinkedIn)."
    )
    async def get_social_status(self) -> str:
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        t = AgentTask(task_type="get_status", payload={})
        res = await agent.handle(t)
        if not res.success:
            return f"Failed to get status: {res.error}"

        platforms = res.result.get("platforms", {})
        parts = []
        for name, data in platforms.items():
            st = "Connected" if data.get("connected") else "Not connected"
            parts.append(f"{name.capitalize()}: {st}")
        return "Social media statuses:\n" + "\n".join(parts)

    @llm.function_tool(
        description="Read messages, unread messages, or conversation history across WhatsApp, Gmail, or Instagram. To check unread messages across all chats, leave contact empty and set filter='unread'. For a specific person/contact, specify contact='Name'."
    )
    async def read_social_messages(self, platform: str, contact: str = "", filter: str = "", limit: int = 10, query: str = "") -> str:
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        p = platform.lower().strip()
        clean_contact = contact.strip() if contact and contact.lower() not in ("inbox", "unread", "all", "none", "whatsapp", "chats", "chat", "messages") else ""
        filter_type = filter.lower().strip() if filter else ""

        if p == "whatsapp":
            if clean_contact:
                t = AgentTask(task_type="read_conversation", payload={"platform": "whatsapp", "contact": clean_contact, "limit": limit})
            else:
                t = AgentTask(task_type="get_unread_chats", payload={"platform": "whatsapp", "unread_only": True, "filter": "unread", "limit": limit})
        elif p == "gmail":
            if clean_contact:
                t = AgentTask(task_type="search_emails", payload={"platform": "gmail", "query": f"from:{clean_contact}"})
            elif query:
                t = AgentTask(task_type="search_emails", payload={"platform": "gmail", "query": query})
            else:
                t = AgentTask(task_type="get_unread_emails", payload={"platform": "gmail", "limit": limit})
        elif p == "instagram":
            if clean_contact:
                t = AgentTask(task_type="read_conversation", payload={"platform": "instagram", "username": clean_contact, "limit": limit})
            elif filter_type == "unread":
                t = AgentTask(task_type="get_unread_chats", payload={"platform": "instagram", "unread_only": True, "filter": "unread", "limit": limit})
            else:
                t = AgentTask(task_type="read_inbox", payload={"platform": "instagram", "limit": limit})
        else:
            return f"Unsupported platform '{platform}' for reading messages."

        res = await agent.handle(t)
        if not res.success:
            return f"Failed reading {platform}: {res.error}"

        if p == "whatsapp":
            if clean_contact:
                msgs = res.result.get("messages", [])
                if not msgs:
                    return f"No messages found with {clean_contact} on WhatsApp."
                lines = [f"[{m.get('sender', 'Contact')} at {m.get('timestamp', '')}] {m.get('text', '')}" for m in msgs[-6:] if m.get('text')]
                return f"Messages from {clean_contact}:\n" + "\n".join(lines)
            else:
                chats = res.result.get("chats", [])
                total_badge = res.result.get("total_badge", "")
                badge_str = f" ({total_badge} total badge)" if total_badge and total_badge != str(len(chats)) else ""
                if not chats:
                    return "No unread WhatsApp messages."
                lines = []
                for c in chats[:limit]:
                    count_str = f" ({c.get('unread_count')} unread)" if c.get('unread_count', 0) > 1 else ""
                    time_str = f" [{c.get('timestamp')}]" if c.get('timestamp') else ""
                    msg_preview = f": {c.get('last_message')}" if c.get('last_message') else ""
                    lines.append(f"• {c.get('contact')}{count_str}{time_str}{msg_preview}")
                return f"Unread WhatsApp messages ({len(chats)} chats{badge_str}):\n" + "\n".join(lines)

        elif p == "gmail":
            msgs = res.result.get("messages", [])
            if not msgs:
                return "No unread emails in Gmail."
            lines = []
            for m in msgs[:limit]:
                content = m.get("body_text") or m.get("body") or m.get("body_snippet") or m.get("snippet", "")
                snippet = content[:500].strip()
                lines.append(f"From: {m.get('from', 'Unknown')}\nSubject: {m.get('subject', '(No Subject)')}\nContent: {snippet}")
            return f"Gmail Emails ({len(msgs)}):\n" + "\n\n".join(lines)

        elif p == "instagram":
            if clean_contact:
                msgs = res.result.get("messages", [])
                if not msgs:
                    return f"No messages found with @{clean_contact.lstrip('@')} on Instagram or the conversation is empty."
                lines = [f"[{m.get('sender')}] {m.get('text')}" for m in msgs[-6:] if m.get('text')]
                return f"Instagram DMs with @{clean_contact.lstrip('@')}:\n" + "\n".join(lines)
            else:
                threads = res.result.get("threads", []) or res.result.get("chats", [])
                total_badge = res.result.get("total_badge", "")
                badge_str = f" ({total_badge} total unread badge)" if total_badge else ""
                if filter_type == "unread":
                    unread_threads = [t for t in threads if t.get("unread")] if any(t.get("unread") for t in threads) else threads
                    if not unread_threads:
                        return "No unread messages found in Instagram Direct inbox."
                    lines = []
                    for t in unread_threads[:limit]:
                        count_str = f" ({t.get('unread_count')} unread)" if t.get('unread_count', 0) > 1 else ""
                        time_str = f" [{t.get('timestamp')}]" if t.get('timestamp') else ""
                        snippet = f": {t.get('last_snippet') or t.get('last_message')}" if (t.get('last_snippet') or t.get('last_message')) else ""
                        lines.append(f"• @{t.get('username') or t.get('contact')}{count_str}{time_str}{snippet}")
                    return f"Unread Instagram Direct messages ({len(unread_threads)} chats{badge_str}):\n" + "\n".join(lines)
                else:
                    if not threads:
                        return "No conversations found in Instagram Direct inbox."
                    lines = []
                    for t in threads[:limit]:
                        unread_tag = " (UNREAD)" if t.get("unread") else ""
                        count_str = f" ({t.get('unread_count')} unread)" if t.get('unread_count', 0) > 1 else ""
                        time_str = f" [{t.get('timestamp')}]" if t.get('timestamp') else ""
                        snippet = f": {t.get('last_snippet') or t.get('last_message')}" if (t.get('last_snippet') or t.get('last_message')) else ""
                        lines.append(f"• @{t.get('username') or t.get('contact')}{unread_tag}{count_str}{time_str}{snippet}")
                    return f"Instagram Direct Inbox ({len(threads)} chats{badge_str}):\n" + "\n".join(lines)

        return str(res.result)

    @llm.function_tool(
        description="Send a message, direct message, or email across WhatsApp, Instagram, or Gmail (e.g. platform='whatsapp', recipient='+919876543210', message='Hello')."
    )
    async def send_social_message(self, platform: str, recipient: str, message: str, subject: str = "Message from JARVIS") -> str:
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        p = platform.lower().strip()
        if p == "whatsapp":
            t = AgentTask(task_type="send_message", payload={"platform": "whatsapp", "contact": recipient, "message": message})
        elif p == "instagram":
            t = AgentTask(task_type="send_message", payload={"platform": "instagram", "username": recipient, "message": message})
        elif p == "gmail":
            t = AgentTask(task_type="send_email", payload={"platform": "gmail", "to": recipient, "subject": subject, "body": message})
        else:
            return f"Unsupported platform '{platform}' for sending messages."

        res = await agent.handle(t)
        if not res.success:
            return f"Failed sending message on {platform}: {res.error}"
        return f"Successfully sent message to {recipient} on {platform}."

    @llm.function_tool(
        description="Open WhatsApp Web or Instagram directly onto the user's screen in the browser. Leave contact empty to bring WhatsApp Web to foreground, or specify contact='Name' to open a specific chat."
    )
    async def open_chat_in_browser(self, platform: str, contact: str = "") -> str:
        agent = self._get_agent()
        browser = self._get_browser()
        p = platform.lower().strip()
        clean_contact = contact.strip() if contact and contact.lower() not in ("inbox", "unread", "all", "none", "whatsapp", "chats", "chat", "messages") else ""

        if p == "whatsapp":
            if agent:
                t = AgentTask(
                    task_type="search_conversation",
                    payload={
                        "platform": "whatsapp",
                        "query": clean_contact,
                        "execution_context": "foreground",
                        "foreground": True,
                        "open_on_screen": True
                    },
                    execution_context="foreground"
                )
                res = await agent.handle(t)
                if res.success:
                    try:
                        from modules.controls.window_controller import WindowController
                        wc = WindowController()
                        wc.focus_window("WhatsApp") or wc.focus_window("Edge") or wc.focus_window("Chrome")
                    except Exception:
                        pass
                    if clean_contact:
                        return f"Opened chat with '{clean_contact}' on WhatsApp Web on your screen."
                    return "WhatsApp Web opened and brought to screen."
                return f"Failed to open WhatsApp: {res.error}"

        elif p == "instagram" and browser:
            try:
                await browser._ensure_driver()
                if browser.context:
                    page = await browser.context.new_page()
                    target_url = f"https://www.instagram.com/direct/t/{clean_contact}" if clean_contact else "https://www.instagram.com/direct/inbox/"
                    await page.goto(target_url, wait_until="domcontentloaded")
                    await page.bring_to_front()
                    try:
                        from modules.controls.window_controller import WindowController
                        wc = WindowController()
                        wc.focus_window("Instagram") or wc.focus_window("Edge") or wc.focus_window("Chrome")
                    except Exception:
                        pass
                    return f"Opened Instagram chat with '{clean_contact or 'inbox'}' on screen."
            except Exception as e:
                return f"Failed to open Instagram chat: {e}"

        return f"Opened {platform} on screen."


    @llm.function_tool(
        description="Search for a user profile on Instagram or LinkedIn to get bio, followers count, and details."
    )
    async def search_social_profile(self, platform: str, username: str) -> str:
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        p = platform.lower().strip()
        t = AgentTask(task_type="search_profile", payload={"platform": p, "username": username})
        res = await agent.handle(t)
        if not res.success:
            return f"Failed to find profile on {platform}: {res.error}"

        prof = res.result.get("profile", {})
        return f"Profile @{prof.get('username')}: {prof.get('full_name', '')}. Followers: {prof.get('follower_count')}, Following: {prof.get('following_count')}, Posts: {prof.get('posts_count')}. Bio: {prof.get('bio', '')}"

    @llm.function_tool(
        description="Draft or write a message or email without sending it immediately. Supports Gmail, WhatsApp, and Instagram. (e.g. platform='gmail', recipient='alice@example.com', message='Hello', subject='Meeting')."
    )
    async def draft_social_message(self, platform: str, recipient: str, message: str, subject: str = "Draft from JARVIS") -> str:
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        p = platform.lower().strip()
        if p == "whatsapp":
            t = AgentTask(task_type="draft_reply", payload={"platform": "whatsapp", "contact": recipient, "body": message})
        elif p == "instagram":
            t = AgentTask(task_type="draft_reply", payload={"platform": "instagram", "username": recipient, "message": message})
        elif p in ("gmail", "email"):
            t = AgentTask(task_type="create_draft", payload={"platform": "gmail", "to": recipient, "subject": subject, "body": message})
        else:
            return f"Unsupported platform '{platform}' for drafting messages. Supported: whatsapp, instagram, gmail."

        res = await agent.handle(t)
        if not res.success:
            return f"Failed drafting message on {platform}: {res.error}"
        return f"Successfully created draft for {recipient} on {platform}."

    @llm.function_tool(
        description="Search for a contact, user, or email sender across WhatsApp, Instagram, or Gmail (email) to see if they exist or retrieve matching records/details (e.g. platform='whatsapp', query='John Doe')."
    )
    async def search_social_people(self, platform: str, query: str) -> str:
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        p = platform.lower().strip()
        if p == "whatsapp":
            t = AgentTask(task_type="search_conversation", payload={"platform": "whatsapp", "contact": query})
            res = await agent.handle(t)
            if not res.success:
                return f"Failed searching for '{query}' on WhatsApp: {res.error}"
            return f"Successfully found and opened chat with '{query}' on WhatsApp."
            
        elif p == "instagram":
            t = AgentTask(task_type="search_profile", payload={"platform": "instagram", "username": query})
            res = await agent.handle(t)
            if not res.success:
                return f"Failed to find Instagram profile for '{query}': {res.error}"
            prof = res.result.get("profile", {})
            return f"Found Instagram profile @{prof.get('username')}: {prof.get('full_name', '')}. Followers: {prof.get('follower_count')}, Following: {prof.get('following_count')}, Posts: {prof.get('posts_count')}. Bio: {prof.get('bio', '')}"
            
        elif p in ("gmail", "email"):
            t = AgentTask(task_type="search_emails", payload={"platform": "gmail", "query": query})
            res = await agent.handle(t)
            if not res.success:
                return f"Failed to search emails for '{query}': {res.error}"
            emails = res.result.get("messages", [])
            if not emails:
                return f"No emails or contacts found matching '{query}' in Gmail."
            lines = []
            for m in emails[:3]:
                lines.append(f"- From: {m.get('from')} | Subject: {m.get('subject')} | Snippet: {m.get('snippet')[:100]}...")
            return f"Found {len(emails)} emails matching '{query}':\n" + "\n".join(lines)
            
        else:
            return f"Unsupported platform '{platform}' for searching people. Supported: whatsapp, instagram, gmail."

    @llm.function_tool(
        description="Check status, total orders, bookings, and active escalations of the autonomous WhatsApp AI Employee."
    )
    async def get_whatsapp_ai_agent_status(self) -> str:
        """Inspect autonomous WhatsApp Agent health and business metrics."""
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        t = AgentTask(task_type="get_agent_metrics", payload={})
        res = await wa_agent.handle(t)
        if not res.success:
            return f"Failed fetching WhatsApp agent metrics: {res.error}"

        m = res.result
        return (
            f"WhatsApp AI Employee Status:\n"
            f"- Auto-reply active: {m.get('auto_reply_enabled')}\n"
            f"- Total customer orders processed: {m.get('total_orders')}\n"
            f"- Appointments booked: {m.get('total_bookings')}\n"
            f"- Open human escalations: {m.get('open_human_escalations')}\n"
            f"- Active human takeover sessions: {m.get('active_human_takeovers_count')}"
        )

    @llm.function_tool(
        description="Enable or disable autonomous auto-reply on WhatsApp (e.g. enabled=True to let AI employee handle messages, or enabled=False to pause AI)."
    )
    async def toggle_whatsapp_auto_reply(self, enabled: bool) -> str:
        """Toggle autonomous WhatsApp auto-replies."""
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        t = AgentTask(task_type="toggle_auto_reply", payload={"enabled": enabled})
        res = await wa_agent.handle(t)
        state_str = "ENABLED (AI Employee is active)" if enabled else "DISABLED (AI responses paused)"
        return f"WhatsApp auto-reply is now {state_str}."

    @llm.function_tool(
        description="List any open customer tickets escalated to human support on WhatsApp."
    )
    async def list_whatsapp_escalations(self) -> str:
        """List open human escalations from WhatsApp customers."""
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        t = AgentTask(task_type="list_escalations", payload={"status": "Open"})
        res = await wa_agent.handle(t)
        if not res.success:
            return f"Failed fetching escalations: {res.error}"

        escalations = res.result.get("escalations", [])
        if not escalations:
            return "No open human escalations. WhatsApp AI Employee is handling all customer queries smoothly."

        lines = [f"Found {len(escalations)} open escalation(s):"]
        for e in escalations:
            lines.append(f"- Ticket {e.get('ticket_id')} ({e.get('customer_name')}, {e.get('customer_phone')}): Reason: '{e.get('reason')}' | Summary: {e.get('conversation_summary')}")
        return "\n".join(lines)

    @llm.function_tool(
        description="Run an autonomous triage across WhatsApp messages: categorizes into 🔴 Urgent, 🟡 Needs reply, 🟢 FYI/No action, auto-drafts replies matching Akshay's tone, and tracks commitments/promises (e.g. 'Find all unread messages from today and tell me which ones need a reply')."
    )
    async def triage_whatsapp_messages(self, limit: int = 10, unread_only: bool = True) -> str:
        """Runs full autonomous triage across unread WhatsApp chats."""
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        t = AgentTask(task_type="triage_inbox", payload={"limit": limit, "unread_only": unread_only})
        res = await wa_agent.handle(t)
        if not res.success:
            return f"Failed triaging WhatsApp messages: {res.error}"

        data = res.result
        return data.get("summary") or "WhatsApp triage complete."

    @llm.function_tool(
        description="Summarize a 1-on-1 or group WhatsApp chat history (who said what, key decisions made, action items, and pending questions)."
    )
    async def summarize_whatsapp_conversation(self, contact: str, limit: int = 30) -> str:
        """Summarize a 1-on-1 or group WhatsApp conversation."""
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        t = AgentTask(task_type="summarize_chat", payload={"contact": contact, "limit": limit})
        res = await wa_agent.handle(t)
        if not res.success:
            return f"Failed summarizing WhatsApp chat with '{contact}': {res.error}"

        summary_data = res.result.get("summary", {})
        overview = summary_data.get("overview", "")
        topics = ", ".join(summary_data.get("key_topics", []))
        decisions = "; ".join(summary_data.get("decisions_made", [])) or "None"
        actions = "; ".join(summary_data.get("action_items", [])) or "None"

        return (
            f"WhatsApp Summary for '{contact}':\n\n"
            f"📌 Overview: {overview}\n"
            f"🏷️ Key Topics: {topics}\n"
            f"✅ Decisions: {decisions}\n"
            f"🎯 Action Items: {actions}"
        )

    @llm.function_tool(
        description="Inspect a document or requirements PDF sent in WhatsApp, extract project specifications, deadlines, deliverables, and requirements."
    )
    async def inspect_whatsapp_document(self, contact: str, file_name: str = "requirements.pdf") -> str:
        """Extracts and summarizes project requirements from a WhatsApp PDF/document."""
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        t = AgentTask(task_type="extract_document_requirements", payload={"contact": contact, "file_name": file_name})
        res = await wa_agent.handle(t)
        if not res.success:
            return f"Failed inspecting document from '{contact}': {res.error}"

        reqs = res.result.get("requirements", {})
        title = reqs.get("project_title", file_name)
        objectives = "\n".join([f"- {o}" for o in reqs.get("key_objectives", [])])
        functional = "\n".join([f"- {f}" for f in reqs.get("functional_requirements", [])])
        deliverables = "\n".join([f"- {d}" for d in reqs.get("deliverables", [])])
        milestones = "\n".join([f"- {m}" for m in reqs.get("deadlines_and_milestones", [])]) or "None specified"

        return (
            f"📋 Requirements Breakdown: {title} (from {contact})\n\n"
            f"🎯 Objectives:\n{objectives}\n\n"
            f"⚙️ Functional Requirements:\n{functional}\n\n"
            f"📦 Deliverables:\n{deliverables}\n\n"
            f"⏰ Deadlines:\n{milestones}"
        )

    @llm.function_tool(
        description="Review AI-drafted WhatsApp replies waiting in the queue for human approval before sending."
    )
    async def review_whatsapp_pending_drafts(self, limit: int = 5) -> str:
        """List AI-drafted WhatsApp replies waiting in review queue."""
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        t = AgentTask(task_type="review_drafts", payload={"status": "pending", "limit": limit})
        res = await wa_agent.handle(t)
        if not res.success:
            return f"Failed fetching WhatsApp drafts: {res.error}"

        drafts = res.result.get("drafts", [])
        if not drafts:
            return "No pending WhatsApp drafts waiting for approval."

        lines = [f"Found {len(drafts)} draft(s) awaiting approval:"]
        for d in drafts:
            lines.append(
                f"\n[Draft ID: {d.get('draft_id')} - Urgency: {d.get('urgency')}]\n"
                f"To: {d.get('contact')} ({d.get('recipient_phone') or 'Direct'})\n"
                f"Inbound Msg: \"{d.get('original_message')}\"\n"
                f"Drafted Reply: \"{d.get('drafted_reply')}\""
            )
        return "\n".join(lines)

    @llm.function_tool(
        description="Approve and send a pending AI-drafted WhatsApp message using its draft_id (e.g. draft_id='WA-DFT-A1B2C3D4')."
    )
    async def approve_and_send_whatsapp_draft(self, draft_id: str) -> str:
        """Approve and dispatch a WhatsApp draft."""
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        t = AgentTask(task_type="approve_and_send_draft", payload={"draft_id": draft_id, "approved_by": "voice_assistant"})
        res = await wa_agent.handle(t)
        if not res.success:
            return f"Failed sending WhatsApp draft '{draft_id}': {res.error}"

        return f"Successfully approved and sent WhatsApp draft '{draft_id}' to {res.result.get('recipient')}."

    @llm.function_tool(
        description="Schedule a WhatsApp commitment, promise, or SLA follow-up reminder (e.g. contact='Rahul', commitment='Send updated design', due_date='Tomorrow 10:00 AM')."
    )
    async def schedule_whatsapp_commitment(self, contact: str, commitment: str, due_date: str = "Tomorrow 10:00 AM") -> str:
        """Track outgoing promises or incoming SLA deadlines for WhatsApp."""
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        t = AgentTask(task_type="schedule_followup", payload={"contact": contact, "commitment_text": commitment, "due_date": due_date})
        res = await wa_agent.handle(t)
        if not res.success:
            return f"Failed scheduling WhatsApp follow-up: {res.error}"

        return f"Scheduled follow-up reminder for {contact}: '{commitment}' due by {due_date}."

    @llm.function_tool(
        description="Get an executive morning briefing of all WhatsApp activity: unread messages, pending drafts for review, and today's commitments."
    )
    async def get_whatsapp_morning_briefing(self) -> str:
        """Generate morning briefing for WhatsApp."""
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        t = AgentTask(task_type="morning_briefing", payload={})
        res = await wa_agent.handle(t)
        if not res.success:
            return f"Failed generating morning briefing: {res.error}"

        return res.result.get("briefing", "No updates available.")

    @llm.function_tool(
        description="Directly send a WhatsApp message to a contact or phone number without waiting in review queue (e.g. recipient='Rahul', message='Hey Rahul, here is the updated plan')."
    )
    async def send_whatsapp_direct_message(self, recipient: str, message: str) -> str:
        """Directly dispatch a WhatsApp message."""
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        t = AgentTask(task_type="send_message", payload={"platform": "whatsapp", "contact": recipient, "message": message, "to": recipient, "body": message})
        res = await agent.handle(t)
        if not res.success:
            return f"Failed sending WhatsApp message to {recipient}: {res.error}"
        return f"Successfully sent WhatsApp message to {recipient}."

    @llm.function_tool(
        description="Reply to a specific quoted message on WhatsApp (e.g. contact='Rahul', message='Sounds great!', quote_snippet='What time is the meeting?')."
    )
    async def reply_whatsapp_message(self, contact: str, message: str, quote_snippet: str = "") -> str:
        """Reply to a quoted message on WhatsApp."""
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        t = AgentTask(task_type="reply_message", payload={"platform": "whatsapp", "contact": contact, "to": contact, "body": message, "quote_text": quote_snippet})
        res = await agent.handle(t)
        if not res.success:
            return f"Failed replying to {contact} on WhatsApp: {res.error}"
        return f"Successfully replied to {contact} on WhatsApp."

    @llm.function_tool(
        description="React to a message with an emoji on WhatsApp (e.g. contact='Rahul', emoji='👍', message_snippet='See you tomorrow')."
    )
    async def react_whatsapp_message(self, contact: str, emoji: str = "👍", message_snippet: str = "") -> str:
        """Add emoji reaction to WhatsApp message."""
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        t = AgentTask(task_type="react_message", payload={"platform": "whatsapp", "contact": contact, "to": contact, "emoji": emoji, "message_snippet": message_snippet})
        res = await agent.handle(t)
        if not res.success:
            return f"Failed reacting to message: {res.error}"
        return f"Reacted with {emoji} to message from {contact}."

    @llm.function_tool(
        description="Forward a message from one contact/chat to another on WhatsApp (e.g. from_contact='Rahul', to_contact='Aditya')."
    )
    async def forward_whatsapp_message(self, from_contact: str, to_contact: str) -> str:
        """Forward a message between WhatsApp chats."""
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        t = AgentTask(task_type="forward_message", payload={"platform": "whatsapp", "from": from_contact, "to": to_contact, "recipient": to_contact})
        res = await agent.handle(t)
        if not res.success:
            return f"Failed forwarding message: {res.error}"
        return f"Forwarded message from {from_contact} to {to_contact} on WhatsApp."

    @llm.function_tool(
        description="Manage a WhatsApp chat: pin, unpin, archive, unarchive, mute, unmute, mark_read, mark_unread, or clear (e.g. contact='Rahul', action='pin')."
    )
    async def manage_whatsapp_chat(self, contact: str, action: str) -> str:
        """Perform chat management on WhatsApp."""
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        act = action.lower().strip()
        t = AgentTask(task_type=act, payload={"platform": "whatsapp", "contact": contact, "to": contact})
        res = await agent.handle(t)
        if not res.success:
            return f"Failed to {action} chat with {contact}: {res.error}"
        return f"Successfully performed '{action}' on chat with {contact}."

    @llm.function_tool(
        description="Send media, photos, documents, or PDFs to a contact on WhatsApp (e.g. contact='Rahul', file_path='C:/reports/invoice.pdf', caption='Here is your invoice')."
    )
    async def send_whatsapp_media(self, contact: str, file_path: str, caption: str = "") -> str:
        """Upload and send media to WhatsApp."""
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        t = AgentTask(task_type="send_media", payload={"platform": "whatsapp", "contact": contact, "to": contact, "file_path": file_path, "caption": caption})
        res = await agent.handle(t)
        if not res.success:
            return f"Failed sending media to {contact}: {res.error}"
        return f"Successfully sent attachment ({os.path.basename(file_path)}) to {contact} on WhatsApp."

    @llm.function_tool(
        description="Get group details, member list, and description for a WhatsApp group (e.g. group_name='Project Alpha Team')."
    )
    async def get_whatsapp_group_details(self, group_name: str) -> str:
        """Inspect WhatsApp group participants and info."""
        agent = self._get_agent()
        if not agent:
            return "Social Media Agent is not initialized."

        t = AgentTask(task_type="get_group_info", payload={"platform": "whatsapp", "contact": group_name, "to": group_name})
        res = await agent.handle(t)
        if not res.success:
            return f"Failed getting group details for '{group_name}': {res.error}"

        info = res.result.get("group_info", {})
        members = ", ".join(info.get("participants", [])) or "None visible"
        return (
            f"WhatsApp Group: {info.get('name', group_name)}\n"
            f"- Description: {info.get('description') or 'No description'}\n"
            f"- Participants ({info.get('participant_count', 0)}): {members}"
        )

    @llm.function_tool(
        description="Send a message to a WhatsApp group (e.g. group_name='College Group', message='Hey everyone!')."
    )
    async def send_whatsapp_group_message(self, group_name: str, message: str) -> str:
        """Send message to a WhatsApp group."""
        return await self.send_whatsapp_direct_message(recipient=group_name, message=message)

    @llm.function_tool(
        description="Schedule a WhatsApp message for future delivery (e.g. contact='Mom', message='Happy Birthday!', send_at='Tomorrow 8:00 AM')."
    )
    async def schedule_whatsapp_message(self, contact: str, message: str, send_at: str = "Tomorrow 9:00 AM") -> str:
        """Schedule a delayed WhatsApp message."""
        wa_agent = self._get_whatsapp_agent()
        if not wa_agent:
            return "WhatsApp AI Agent is not initialized."

        t = AgentTask(task_type="schedule_followup", payload={"contact": contact, "commitment_text": f"Send scheduled message: '{message}'", "due_date": send_at})
        res = await wa_agent.handle(t)
        if not res.success:
            return f"Failed scheduling message: {res.error}"
        return f"Scheduled WhatsApp message to {contact} for {send_at}: '{message}'."

    @llm.function_tool(
        description="Run an autonomous triage and intelligence scan across Gmail inbox. Identifies urgent/VIP emails, categorizes tasks, extracts meeting requests, and drafts replies for review."
    )
    async def triage_gmail_inbox(self, limit: int = 10, auto_archive_newsletters: bool = False) -> str:
        """Runs full autonomous triage across Gmail inbox."""
        gmail_agent = self._get_gmail_agent()
        if not gmail_agent:
            return "Gmail AI Agent is not initialized."

        t = AgentTask(task_type="triage_inbox", payload={"limit": limit, "auto_archive_newsletters": auto_archive_newsletters})
        res = await gmail_agent.handle(t)
        if not res.success:
            return f"Failed triaging Gmail inbox: {res.error}"

        data = res.result
        scanned = data.get("scanned_count", 0)
        drafts = data.get("drafts_generated", [])
        meetings = data.get("meetings_extracted", [])
        quarantined = data.get("quarantined_count", 0)
        archived = data.get("archived_count", 0)

        lines = [
            f"Gmail Inbox Triage Complete:",
            f"- Scanned emails: {scanned}",
            f"- Auto-generated draft replies: {len(drafts)}",
            f"- Meetings detected: {len(meetings)}",
            f"- Quarantined threats: {quarantined}",
            f"- Archived newsletters: {archived}"
        ]

        if drafts:
            lines.append("\nDrafts awaiting review:")
            for d in drafts[:3]:
                lines.append(f"  • To: {d.get('recipient')} | Subject: '{d.get('subject')}' (Draft ID: {d.get('draft_id')})")

        if meetings:
            lines.append("\nMeetings detected:")
            for m in meetings[:3]:
                lines.append(f"  • {m.get('title')} ({m.get('start_time')})")

        return "\n".join(lines)

    @llm.function_tool(
        description="Retrieve executive email analytics and inbox health metrics (total threads, urgent tasks, drafts in queue, pending follow-ups)."
    )
    async def get_email_analytics(self) -> str:
        """Inspect Gmail executive analytics and inbox health."""
        gmail_agent = self._get_gmail_agent()
        if not gmail_agent:
            return "Gmail AI Agent is not initialized."

        t = AgentTask(task_type="get_analytics", payload={})
        res = await gmail_agent.handle(t)
        if not res.success:
            return f"Failed fetching email analytics: {res.error}"

        m = res.result
        cats = m.get("categories", {})
        cat_str = ", ".join([f"{k}: {v}" for k, v in cats.items()]) if cats else "None"

        return (
            f"Gmail Intelligence Analytics:\n"
            f"- Total threads indexed: {m.get('total_threads_indexed', 0)}\n"
            f"- Urgent / High-Priority items: {m.get('urgent_threads_count', 0)}\n"
            f"- Quarantined threats (phishing/injection): {m.get('quarantined_threats_count', 0)}\n"
            f"- Draft replies pending review: {m.get('pending_drafts_count', 0)}\n"
            f"- Active SLA follow-ups / commitments: {m.get('pending_followups_count', 0)}\n"
            f"- Extracted meetings: {m.get('extracted_meetings_count', 0)}\n"
            f"- Categories: {cat_str}"
        )

    @llm.function_tool(
        description="Review AI-drafted email replies waiting in the queue for human approval before sending."
    )
    async def review_pending_drafts(self, limit: int = 5) -> str:
        """List AI-drafted email replies in the review queue."""
        gmail_agent = self._get_gmail_agent()
        if not gmail_agent:
            return "Gmail AI Agent is not initialized."

        t = AgentTask(task_type="review_drafts", payload={"limit": limit, "status": "pending"})
        res = await gmail_agent.handle(t)
        if not res.success:
            return f"Failed reviewing drafts: {res.error}"

        drafts = res.result.get("drafts", [])
        if not drafts:
            return "No pending email drafts waiting in review queue."

        lines = [f"Found {len(drafts)} draft(s) awaiting review:"]
        for d in drafts:
            snippet = d.get("body", "").replace("\n", " ")[:160]
            lines.append(
                f"\n[Draft ID: {d.get('draft_id')}]\n"
                f"To: {d.get('recipient')}\n"
                f"Subject: {d.get('subject')}\n"
                f"Preview: \"{snippet}...\""
            )
        return "\n".join(lines)

    @llm.function_tool(
        description="Approve and send a pending AI-drafted email using its draft_id (e.g. draft_id='DFT-A1B2C3D4')."
    )
    async def approve_and_send_email_draft(self, draft_id: str) -> str:
        """Approve and dispatch an email draft via Gmail."""
        gmail_agent = self._get_gmail_agent()
        if not gmail_agent:
            return "Gmail AI Agent is not initialized."

        t = AgentTask(task_type="approve_and_send_draft", payload={"draft_id": draft_id, "approved_by": "voice_assistant"})
        res = await gmail_agent.handle(t)
        if not res.success:
            return f"Failed sending draft '{draft_id}': {res.error}"

        return f"Successfully approved and sent email draft '{draft_id}' to {res.result.get('recipient')}."

    @llm.function_tool(
        description="Schedule a commitment, promise, or unanswered SLA follow-up reminder (e.g. recipient='client@acme.com', promise='Send Q3 revised pricing', due_date='Tomorrow 5 PM')."
    )
    async def schedule_email_followup(self, recipient: str, promise: str, due_date: str = "In 3 days") -> str:
        """Track outgoing promises or incoming SLA deadlines."""
        gmail_agent = self._get_gmail_agent()
        if not gmail_agent:
            return "Gmail AI Agent is not initialized."

        t = AgentTask(task_type="schedule_followup", payload={"recipient": recipient, "promise": promise, "due_date": due_date})
        res = await gmail_agent.handle(t)
        if not res.success:
            return f"Failed scheduling follow-up: {res.error}"

        return f"Scheduled follow-up reminder for {recipient}: '{promise}' due by {due_date}."

    @llm.function_tool(
        description="Enable or disable autonomous background triage for Gmail (e.g. enabled=True to let JARVIS triage inbox in background)."
    )
    async def toggle_gmail_auto_triage(self, enabled: bool) -> str:
        """Toggle autonomous background Gmail triage."""
        gmail_agent = self._get_gmail_agent()
        if not gmail_agent:
            return "Gmail AI Agent is not initialized."

        t = AgentTask(task_type="toggle_auto_triage", payload={"enabled": enabled})
        res = await gmail_agent.handle(t)
        state_str = "ENABLED" if enabled else "DISABLED"
        return f"Gmail autonomous triage is now {state_str}."

    # ── Autonomous Instagram Operator Tools ───────────────────────────────────

    @llm.function_tool(
        description="Research trending topics, viral hook patterns, and hashtag sets for Instagram (e.g. niche='UI/UX Design', topic='Portfolio Redesign')."
    )
    async def instagram_research_trends(self, niche: str = "UI/UX Design", topic: str = "") -> str:
        """Autonomous trend and competitor intelligence research for Instagram."""
        ig_agent = self._get_instagram_agent()
        if not ig_agent:
            return "Instagram AI Agent is not initialized."

        t = AgentTask(task_type="research_trends", payload={"niche": niche, "topic": topic})
        res = await ig_agent.handle(t)
        if not res.success:
            return f"Failed researching Instagram trends: {res.error}"

        data = res.result
        hooks = data.get("trending_hooks", [])[:3]
        formats = data.get("recommended_formats", [])[:2]
        
        hook_lines = "\n".join([f"- \"{h}\"" for h in hooks])
        format_lines = "\n".join([f"- {f.get('format')}: {f.get('archetype')} (Target: {f.get('avg_retention_target') or f.get('save_rate_target')})" for f in formats])

        return (
            f"Instagram Trend Intelligence for '{data.get('niche')}':\n\n"
            f"🔥 Top Viral Hooks:\n{hook_lines}\n\n"
            f"📐 Recommended Formats:\n{format_lines}\n\n"
            f"⏰ Optimal Window: {data.get('competitor_insights', {}).get('peak_engagement_window', '18:30-21:00')}"
        )

    @llm.function_tool(
        description="Generate an agile 30-day Instagram content calendar matrix tailored to a specific goal (e.g. goal='Gain 1,000 followers and 20 client leads', niche='UI/UX Design', days=30)."
    )
    async def instagram_generate_strategy(self, goal: str = "Grow engaged audience and gain client leads", niche: str = "UI/UX Design", days: int = 7) -> str:
        """Create a goal-weighted Instagram content strategy matrix."""
        ig_agent = self._get_instagram_agent()
        if not ig_agent:
            return "Instagram AI Agent is not initialized."

        t = AgentTask(task_type="generate_strategy", payload={"goal": goal, "niche": niche, "days": days})
        res = await ig_agent.handle(t)
        if not res.success:
            return f"Failed generating Instagram strategy: {res.error}"

        data = res.result
        matrix = data.get("calendar_matrix", [])
        lines = []
        for m in matrix[:min(days, 7)]:
            lines.append(f"• Day {m.get('day_number')} ({m.get('day_of_week')} @ {m.get('optimal_time')}): [{m.get('format')}] {m.get('content_theme')} (Goal: {m.get('target_kpi')})")

        return (
            f"Instagram Content Strategy [{data.get('goal_type')}]:\n"
            f"Primary KPI: {data.get('primary_kpi')}\n\n"
            f"Scheduled Calendar Plan (Next {len(matrix[:7])} Days):\n" + "\n".join(lines)
        )

    @llm.function_tool(
        description="Generate a complete multimodal Instagram content production brief (Hook, Script, Visual Safe-Zones, Caption, Hashtags, CTA) for a Reel or Carousel."
    )
    async def instagram_create_content_brief(self, topic: str, format_type: str = "Reel", goal: str = "reach", niche: str = "UI/UX") -> str:
        """Create a production brief for an Instagram Reel or Carousel."""
        ig_agent = self._get_instagram_agent()
        if not ig_agent:
            return "Instagram AI Agent is not initialized."

        t = AgentTask(task_type="create_content_brief", payload={"topic": topic, "format": format_type, "goal": goal, "niche": niche})
        res = await ig_agent.handle(t)
        if not res.success:
            return f"Failed creating content brief: {res.error}"

        data = res.result
        return (
            f"Instagram Content Production Brief [{data.get('format')}]:\n\n"
            f"🪝 Hook: \"{data.get('hook')}\"\n\n"
            f"📝 Caption Preview:\n{data.get('caption')[:250]}...\n\n"
            f"🎯 CTA: {data.get('cta')}\n"
            f"🏷️ Hashtags: {data.get('hashtags')}"
        )

    @llm.function_tool(
        description="Classify an Instagram comment (Lead, Question, Positive, Spam, Toxic) and generate an appropriate auto-response or moderation action."
    )
    async def instagram_triage_comment(self, username: str, comment_text: str) -> str:
        """Classify and triage incoming Instagram comments."""
        ig_agent = self._get_instagram_agent()
        if not ig_agent:
            return "Instagram AI Agent is not initialized."

        t = AgentTask(task_type="classify_comment", payload={"username": username, "text": comment_text})
        res = await ig_agent.handle(t)
        if not res.success:
            return f"Failed triaging comment: {res.error}"

        d = res.result
        reply_part = f"\nSuggested Reply: \"{d.get('suggested_reply')}\"" if d.get('suggested_reply') else ""
        return (
            f"Comment Triage for @{d.get('username')}:\n"
            f"- Category: {d.get('category')}\n"
            f"- Sentiment Score: {d.get('sentiment_score')}\n"
            f"- Recommended Action: {d.get('recommended_action')}"
            f"{reply_part}"
        )

    @llm.function_tool(
        description="Qualify an inbound Instagram DM into the CRM pipeline with BANT sales criteria (Service, Budget, Timeline) and suggest a response."
    )
    async def instagram_qualify_dm_lead(self, username: str, message: str) -> str:
        """Qualify an inbound Instagram DM into the CRM pipeline."""
        ig_agent = self._get_instagram_agent()
        if not ig_agent:
            return "Instagram AI Agent is not initialized."

        t = AgentTask(task_type="qualify_dm_lead", payload={"username": username, "message": message})
        res = await ig_agent.handle(t)
        if not res.success:
            return f"Failed qualifying DM lead: {res.error}"

        d = res.result
        return (
            f"Instagram Lead Qualification for {d.get('username')}:\n"
            f"- Status: {d.get('status')} (Qualified: {d.get('is_qualified')})\n"
            f"- Service Interest: {d.get('service_interest')}\n"
            f"- Budget Estimate: {d.get('budget')}\n"
            f"- Timeline: {d.get('timeline')}\n\n"
            f"Suggested DM Response:\n\"{d.get('suggested_dm_reply')}\""
        )

    @llm.function_tool(
        description="Run a deep causal post-mortem analysis on an Instagram post (views, likes, comments, shares, saves) explaining WHY it succeeded or underperformed."
    )
    async def instagram_analyze_post(self, views: int, likes: int, comments: int, shares: int, saves: int, post_type: str = "Reel", topic: str = "UI/UX") -> str:
        """Perform deep causal post-mortem analysis on Instagram post performance."""
        ig_agent = self._get_instagram_agent()
        if not ig_agent:
            return "Instagram AI Agent is not initialized."

        t = AgentTask(
            task_type="analyze_post_performance",
            payload={"views": views, "likes": likes, "comments": comments, "shares": shares, "saves": saves, "post_type": post_type, "topic": topic}
        )
        res = await ig_agent.handle(t)
        if not res.success:
            return f"Failed analyzing post: {res.error}"

        d = res.result
        metrics = d.get("metrics", {})
        factors = "\n".join([f"✓ {f}" for f in d.get("causal_factors", [])])
        lessons = "\n".join([f"! {l}" for l in d.get("actionable_lessons", [])]) if d.get("actionable_lessons") else "None"

        return (
            f"Post Performance Post-Mortem [{d.get('post_type')} - '{d.get('topic')}']:\n"
            f"Performance Rating: {d.get('performance_rating')}\n"
            f"Metrics: Views: {metrics.get('views'):,} | Saves: {metrics.get('saves')} ({metrics.get('save_rate')}) | Shares: {metrics.get('shares')} ({metrics.get('share_rate')})\n\n"
            f"Why It Worked:\n{factors}\n\n"
            f"Actionable Lessons:\n{lessons}\n\n"
            f"Self-Learning Directive: {d.get('self_learning_directive')}"
        )

    @llm.function_tool(
        description="Trigger the closed-loop self-learning cycle to calibrate future Instagram content strategies and schedule weights based on historical post data."
    )
    async def instagram_run_self_learning_cycle(self) -> str:
        """Calibrate and reweight upcoming Instagram strategies using historical post analytics."""
        ig_agent = self._get_instagram_agent()
        if not ig_agent:
            return "Instagram AI Agent is not initialized."

        t = AgentTask(task_type="trigger_self_learning_cycle", payload={})
        res = await ig_agent.handle(t)
        if not res.success:
            return f"Failed running self-learning cycle: {res.error}"

        d = res.result
        discoveries = "\n".join([f"• {x}" for x in d.get("core_discoveries", [])])
        return (
            f"Instagram Self-Learning Optimization Results ({d.get('status').upper()}):\n\n"
            f"Core Discoveries:\n{discoveries}\n\n"
            f"Strategic Adaptation:\n{d.get('action_directive')}"
        )


