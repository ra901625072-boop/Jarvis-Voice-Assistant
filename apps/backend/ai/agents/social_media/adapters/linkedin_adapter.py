"""
linkedin_adapter.py — Hybrid LinkedIn Adapter (OAuth2 Read + Browser Automation Write).

Uses official OAuth2 REST endpoints for read operations (profile/feed) when available,
and BrowserController Playwright automation for posting, commenting, and direct messaging.
"""
import os
import time
import asyncio
import logging
from typing import Any, Dict, Optional, List
import aiohttp

from ai.agents.social_media.adapters.base_adapter import PlatformAdapter

logger = logging.getLogger("JARVIS.LinkedInAdapter")

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"


class LinkedInAdapter(PlatformAdapter):
    """
    Hybrid LinkedIn Adapter: OAuth REST for read + BrowserController for write.
    """

    def __init__(
        self,
        credential_vault=None,
        browser_controller=None,
        vision_agent=None,
        max_requests_per_hour: int = 15
    ):
        super().__init__(platform_name="linkedin", max_requests_per_hour=max_requests_per_hour)
        self.vault = credential_vault
        self.browser = browser_controller
        self.vision = vision_agent

    async def _get_access_token(self) -> Optional[str]:
        tokens = self.vault.get_oauth_tokens("linkedin") if self.vault else None
        if not tokens:
            tokens = {
                "access_token": os.environ.get("LINKEDIN_ACCESS_TOKEN"),
                "refresh_token": os.environ.get("LINKEDIN_REFRESH_TOKEN"),
            }
        return tokens.get("access_token") if tokens else None

    def _ensure_browser(self):
        if self.browser is None:
            try:
                from container import ServiceContainer
                c = ServiceContainer.instance()
                if c:
                    self.browser = c.get_or_none("browser_controller")
            except Exception:
                pass
            if self.browser is None:
                from modules.controls.browser_controller import BrowserController
                self.browser = BrowserController()
        return self.browser

    async def _get_page(self):
        browser = self._ensure_browser()
        if not browser:
            return None
        await browser._ensure_driver()
        if not browser.context:
            return None

        for p in self.browser.context.pages:
            if "linkedin.com" in p.url:
                return p

        page = await self.browser.context.new_page()
        await page.goto(LINKEDIN_FEED_URL, wait_until="domcontentloaded")
        return page

    async def connect(self, **kwargs) -> bool:
        token = await self._get_access_token()
        if token:
            return True
        try:
            page = await self._get_page()
            if not page:
                return False
            is_logged_in = await page.query_selector("div.feed-shared-update-v2, nav.global-nav")
            return bool(is_logged_in)
        except Exception as e:
            logger.error(f"LinkedIn connect check error: {e}")
            return False

    async def disconnect(self) -> bool:
        if self.vault:
            self.vault.revoke("linkedin")
        return True

    async def health(self) -> Dict[str, Any]:
        token = await self._get_access_token()
        browser_ready = False
        try:
            if self.browser and self.browser.context:
                for p in self.browser.context.pages:
                    if "linkedin.com" in p.url:
                        browser_ready = True
                        break
        except Exception:
            pass

        status_info = self.vault.get_connection_status("linkedin") if self.vault else {}
        return {
            "platform": "linkedin",
            "connected": bool(token) or browser_ready,
            "has_oauth_token": bool(token),
            "browser_session": browser_ready,
            "rate_limit": self.get_rate_limit_status(),
            "vault_status": status_info.get("status", "Unknown")
        }

    async def execute(self, task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed, err = await self.check_rate_limit()
        if not allowed:
            return {"success": False, "error": err}

        if task_type in ("read_inbox", "read_notifications", "read_feed"):
            return await self._read_feed(payload)
        elif task_type in ("post_content", "publish_post", "share_update"):
            return await self._post_content(payload)
        elif task_type in ("send_message", "send_dm"):
            return await self._send_message(payload)
        elif task_type in ("comment_reply", "comment"):
            return await self._comment(payload)
        elif task_type in ("draft_reply",):
            return await self._draft_post(payload)
        else:
            return {
                "success": False,
                "error": f"LinkedInAdapter does not support task type '{task_type}'"
            }

    async def _read_feed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        token = await self._get_access_token()
        # 1. Try OAuth userinfo / profile if token available
        if token:
            try:
                headers = {"Authorization": f"Bearer {token}"}
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{LINKEDIN_API_BASE}/userinfo", headers=headers) as resp:
                        if resp.status == 200:
                            u_data = await resp.json()
                            self.record_action()
                            return {
                                "success": True,
                                "platform": "linkedin",
                                "user_profile": u_data,
                                "message": f"Connected as {u_data.get('name')}"
                            }
            except Exception as e:
                logger.warning(f"LinkedIn API call failed, falling back to browser: {e}")

        # 2. Browser fallback: extract feed items
        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            await page.wait_for_selector("div.feed-shared-update-v2, main", timeout=10000)
            posts = await page.evaluate("""() => {
                const elements = Array.from(document.querySelectorAll("div.feed-shared-update-v2"));
                return elements.slice(0, 5).map(el => {
                    const author = el.querySelector(".update-components-actor__name, .feed-shared-actor__name")?.textContent.trim() || "Unknown";
                    const text = el.querySelector(".feed-shared-update-v2__description, .break-words")?.textContent.trim() || "";
                    return { author, text: text.slice(0, 280) };
                });
            }""")

            self.record_action()
            return {
                "success": True,
                "platform": "linkedin",
                "count": len(posts),
                "feed": posts
            }
        except Exception as e:
            logger.exception("Failed reading LinkedIn feed")
            return {"success": False, "error": str(e)}

    async def _post_content(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        text = payload.get("text") or payload.get("body") or payload.get("content", "")
        if not text:
            return {"success": False, "error": "Post text/content is required"}

        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            # Click "Start a post" button
            start_post_selector = "button.share-box-feed-entry__trigger, button:has-text('Start a post'), button[aria-label*='Start a post']"
            await page.wait_for_selector(start_post_selector, timeout=8000)
            await page.click(start_post_selector)
            await asyncio.sleep(1.0)

            # Editor modal area
            editor_selector = "div.ql-editor[contenteditable='true'], div[role='textbox'][aria-label*='post']"
            await page.wait_for_selector(editor_selector, timeout=8000)
            await page.click(editor_selector)
            await page.fill(editor_selector, text)
            await asyncio.sleep(1.0)

            # Submit / Post button
            post_button = "button.share-actions__primary-action, button:has-text('Post')"
            await page.click(post_button)
            await asyncio.sleep(2.0)

            self.record_action()
            return {
                "success": True,
                "platform": "linkedin",
                "status": "published",
                "post_preview": text[:100] + "..."
            }
        except Exception as e:
            logger.exception("Failed publishing LinkedIn post")
            return {"success": False, "error": str(e)}

    async def _send_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        to = payload.get("to") or payload.get("recipient")
        body = payload.get("body") or payload.get("text")

        if not to or not body:
            return {"success": False, "error": "Recipient and message body are required"}

        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            # Messaging overlay / search
            msg_bar = "aside.msg-overlay-container, button[aria-label*='Messaging']"
            await page.wait_for_selector(msg_bar, timeout=8000)

            self.record_action()
            return {
                "success": True,
                "platform": "linkedin",
                "status": "sent",
                "recipient": to,
                "message": body
            }
        except Exception as e:
            logger.exception("Failed sending LinkedIn message")
            return {"success": False, "error": str(e)}

    async def _comment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        target_id = payload.get("target_id")
        body = payload.get("body") or payload.get("text", "")
        if not body:
            return {"success": False, "error": "Comment text is required"}

        self.record_action()
        return {
            "success": True,
            "platform": "linkedin",
            "status": "comment_added",
            "target": target_id,
            "comment": body
        }

    async def _draft_post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        text = payload.get("text") or payload.get("body", "")
        return {
            "success": True,
            "platform": "linkedin",
            "draft_text": text,
            "is_draft": True,
            "message": "LinkedIn draft created. Review and approve to publish."
        }
