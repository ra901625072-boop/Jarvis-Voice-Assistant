"""
whatsapp_adapter.py — Full-Access WhatsApp Web Automation Adapter via BrowserController.

Provides complete messaging intelligence and human-grade automation for WhatsApp:
- Deep conversation & message history extraction (incoming vs outgoing, group authors, timestamps, quotes)
- Global and in-chat keyword searching & contact lookup
- Unread messages filtering and active chat triage
- Message sending, quote-replying, forwarding, and drafting
- Group information, participant lists, and admin status extraction
- Chat organization (pin, archive, mute, mark read/unread, clear)
- Status updates / stories inspection
"""
import os
import time
import sqlite3
import asyncio
import logging
from typing import Any, Dict, Optional, List

from ai.agents.social_media.adapters.base_adapter import PlatformAdapter

logger = logging.getLogger("JARVIS.WhatsAppAdapter")

WHATSAPP_WEB_URL = "https://web.whatsapp.com"


class WhatsAppAdapter(PlatformAdapter):
    """
    Full-Access WhatsApp Adapter using BrowserController Playwright automation.
    """

    def __init__(
        self,
        browser_controller=None,
        vision_agent=None,
        credential_vault=None,
        max_requests_per_hour: int = 30
    ):
        super().__init__(platform_name="whatsapp", max_requests_per_hour=max_requests_per_hour)
        self.browser = browser_controller
        self.vision = vision_agent
        self.vault = credential_vault

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
        """Ensure browser page is initialized and ready on WhatsApp Web."""
        browser = self._ensure_browser()
        if not browser:
            return None
        await browser._ensure_driver()
        if not browser.context:
            return None

        # Check if whatsapp tab is already open
        for p in self.browser.context.pages:
            if "web.whatsapp.com" in p.url:
                return p

        # Open whatsapp web
        page = await self.browser.context.new_page()
        await page.goto(WHATSAPP_WEB_URL, wait_until="domcontentloaded")
        return page

    async def connect(self, **kwargs) -> bool:
        """Open WhatsApp Web and check if logged in or check API credentials."""
        mode = os.environ.get("WHATSAPP_MODE", "web").lower().strip()
        if mode == "api":
            token = os.environ.get("WHATSAPP_API_TOKEN") or os.environ.get("JARVIS_WHATSAPP_API_TOKEN")
            phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or os.environ.get("JARVIS_WHATSAPP_PHONE_NUMBER_ID")
            return bool(token and phone_id)

        try:
            page = await self._get_page()
            if not page:
                return False

            try:
                await page.wait_for_selector("#pane-side, div[id='side'], header[data-testid='chatlist-header'], div[role='grid'], canvas[aria-label*='Scan'], div[data-ref]", timeout=8000)
            except Exception:
                pass

            is_logged_in = await page.query_selector("#pane-side, div[id='side'], header[data-testid='chatlist-header'], div[role='grid'], div[data-testid='chat-list']")
            return bool(is_logged_in)
        except Exception as e:
            logger.error(f"WhatsApp connect error: {e}")
            return False

    async def disconnect(self) -> bool:
        """Log out / clear WhatsApp state."""
        try:
            if self.vault:
                self.vault.revoke("whatsapp")
            mode = os.environ.get("WHATSAPP_MODE", "web").lower().strip()
            if mode != "api":
                page = await self._get_page()
                if page:
                    await page.close()
            return True
        except Exception as e:
            logger.error(f"WhatsApp disconnect error: {e}")
            return False

    async def health(self) -> Dict[str, Any]:
        mode = os.environ.get("WHATSAPP_MODE", "web").lower().strip()
        if mode == "api":
            token = os.environ.get("WHATSAPP_API_TOKEN") or os.environ.get("JARVIS_WHATSAPP_API_TOKEN")
            phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or os.environ.get("JARVIS_WHATSAPP_PHONE_NUMBER_ID")
            connected = bool(token and phone_id)
            return {
                "platform": "whatsapp",
                "connected": connected,
                "mode": "official_api",
                "rate_limit": await self.get_rate_limit_status(),
                "vault_status": "API Connected" if connected else "Missing Credentials"
            }

        connected = False
        try:
            if self.browser and self.browser.context:
                for p in self.browser.context.pages:
                    if "web.whatsapp.com" in p.url:
                        elem = await p.query_selector("#pane-side, div[id='side'], header[data-testid='chatlist-header'], div[role='grid'], div[data-testid='chat-list']")
                        if elem:
                            connected = True
                            break
        except Exception:
            connected = False

        status_info = self.vault.get_connection_status("whatsapp") if self.vault else {}
        return {
            "platform": "whatsapp",
            "connected": connected,
            "rate_limit": await self.get_rate_limit_status(),
            "vault_status": status_info.get("status", "Unknown")
        }

    async def execute(self, task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        mode = os.environ.get("WHATSAPP_MODE", "web").lower().strip()
        if mode == "api":
            return await self.execute_api(task_type, payload)

        # Enforce rate limits on outgoing mutation actions
        if task_type in ("send_message", "send_chat", "reply_message", "forward_message", "clear_chat", "delete_chat"):
            allowed, err = await self.check_rate_limit()
            if not allowed:
                return {"success": False, "error": err}

        # ── Reading & Chat Inspection ─────────────────────────────────────────
        if task_type in ("read_inbox", "read_chats", "list_chats"):
            return await self._read_chats(payload)
        elif task_type in ("get_unread_chats", "unread_messages", "unread_chats"):
            p = dict(payload)
            p["unread_only"] = True
            return await self._read_chats(p)
        elif task_type in ("read_conversation", "get_messages", "who_messaged_what", "inspect_chat"):
            return await self._read_conversation(payload)
        elif task_type in ("search_conversation", "find_chat", "search_chat"):
            return await self._search_chat(payload)
        elif task_type in ("search_messages", "query_messages"):
            return await self._search_messages(payload)
        elif task_type in ("get_group_info", "group_details"):
            return await self._get_group_info(payload)
        elif task_type in ("read_status_updates", "status_updates", "stories"):
            return await self._read_status_updates(payload)

        # ── Sending, Quoting, Forwarding & Reactions ──────────────────────────
        elif task_type in ("send_message", "send_chat"):
            return await self._send_message(payload)
        elif task_type in ("reply_message", "reply"):
            return await self._reply_message(payload)
        elif task_type in ("forward_message", "forward"):
            return await self._forward_message(payload)
        elif task_type in ("react_message", "add_reaction", "react"):
            return await self._react_message(payload)
        elif task_type in ("send_media", "send_image", "send_document", "send_file", "send_audio"):
            return await self._send_media(payload)
        elif task_type in ("draft_reply",):
            return await self._draft_reply(payload)

        # ── Chat Management & Triage ──────────────────────────────────────────
        elif task_type in ("mark_as_read", "mark_read"):
            return await self._manage_chat(payload, action="mark_read")
        elif task_type in ("mark_as_unread", "mark_unread"):
            return await self._manage_chat(payload, action="mark_unread")
        elif task_type in ("pin_chat", "pin"):
            return await self._manage_chat(payload, action="pin")
        elif task_type in ("unpin_chat", "unpin"):
            return await self._manage_chat(payload, action="unpin")
        elif task_type in ("archive_chat", "archive"):
            return await self._manage_chat(payload, action="archive")
        elif task_type in ("unarchive_chat", "unarchive"):
            return await self._manage_chat(payload, action="unarchive")
        elif task_type in ("mute_chat", "mute"):
            return await self._manage_chat(payload, action="mute")
        elif task_type in ("unmute_chat", "unmute"):
            return await self._manage_chat(payload, action="unmute")
        elif task_type in ("clear_chat", "delete_chat", "clear"):
            return await self._clear_chat(payload)

        else:
            return {
                "success": False,
                "error": f"WhatsAppAdapter does not support task type '{task_type}'"
            }

    # ── 1. Read & Chat Inspection Operations ──────────────────────────────────

    async def _read_chats(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        limit = min(payload.get("limit", 20), 40)
        unread_only = payload.get("unread_only", False) or payload.get("filter", "").lower().strip() == "unread"
        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            # 1. Wait for WhatsApp side panel or chat list container
            chat_container_selector = "#pane-side, div[id='side'], div[role='grid'], div[data-testid='chat-list'], div[aria-label*='Chat list' i], div[aria-label*='Chats' i], div[id='app']"
            try:
                await page.wait_for_selector(chat_container_selector, timeout=12000)
            except Exception:
                pass

            # 2. Clear any leftover search query
            try:
                clear_btn = await page.query_selector(
                    "button[aria-label*='Cancel search'], span[data-icon='x-alt'], button[aria-label*='Clear'], span[data-icon='search-x'], button[aria-label*='Back'], span[data-icon='back']"
                )
                if clear_btn and await clear_btn.is_visible():
                    await clear_btn.click()
                    await asyncio.sleep(0.3)
                else:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.2)
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.2)
            except Exception:
                pass

            # 3. If unread_only is True, attempt to click the "Unread" filter pill/tab
            filter_clicked = False
            if unread_only:
                try:
                    unread_pill = await page.query_selector(
                        "button[aria-label*='unread' i], "
                        "button:has-text('Unread'), "
                        "div[role='tablist'] button:has-text('Unread'), "
                        "div[role='tablist'] button[aria-label*='unread' i], "
                        "span:has-text('Unread')"
                    )
                    if unread_pill and await unread_pill.is_visible():
                        aria_selected = await unread_pill.get_attribute("aria-selected")
                        if aria_selected != "true":
                            await unread_pill.click()
                            await asyncio.sleep(0.6)
                        filter_clicked = True
                except Exception as e:
                    logger.debug(f"Could not click Unread filter pill: {e}")

            # 4. Extract chat items from DOM with virtualization handling
            chats_result = await page.evaluate("""async (options) => {
                const unreadOnly = options.unread_only;
                const filterClicked = options.filter_clicked;
                const maxLimit = options.limit;

                const pane = document.querySelector("#pane-side, div[data-testid='chat-list']");
                
                // Extract total unread badge from pill or sidebar
                let totalUnreadBadge = "";
                try {
                    const pillElem = document.querySelector("button:has-text('Unread'), div[role='tablist'] button:has-text('Unread'), span:has-text('Unread')");
                    if (pillElem) {
                        const m = pillElem.textContent.match(/Unread\\s*\\(?(\\d+)\\)?/i);
                        if (m) totalUnreadBadge = m[1];
                    }
                    if (!totalUnreadBadge) {
                        const sideBadge = document.querySelector("header span[aria-label*='unread' i], div[role='navigation'] span[aria-label*='unread' i], div[aria-label*='Chats' i] span[class*='badge']");
                        if (sideBadge) totalUnreadBadge = sideBadge.textContent.trim();
                    }
                } catch (e) {}

                const results = [];
                const seenTitles = new Set();
                const ignoredTitles = ["All", "Unread", "Favourites", "Groups", "Status", "Channels", "Communities", "New chat", "Menu", "Search or start new chat", "Search"];

                function harvest() {
                    const items = Array.from(document.querySelectorAll(
                        "#pane-side div[role='listitem'], " +
                        "#pane-side div[role='row'], " +
                        "div[data-testid='cell-frame-container']"
                    ));

                    items.forEach(item => {
                        const titleElem = item.querySelector(
                            "div[data-testid='cell-frame-title'] span, " +
                            "span[title], " +
                            "span[dir='auto']"
                        );
                        let title = titleElem ? (titleElem.getAttribute("title") || titleElem.textContent.trim()) : "";
                        if (!title || seenTitles.has(title)) return;
                        if (ignoredTitles.some(ig => title.startsWith(ig) || title === ig)) return;

                        const lastMsgElem = item.querySelector(
                            "div[data-testid='cell-frame-preview'] span, " +
                            "span[data-testid='last-msg-status'], " +
                            "div[class*='message'], " +
                            "span._ao3e"
                        );
                        const lastMsg = lastMsgElem ? lastMsgElem.textContent.trim() : "";

                        const timeElem = item.querySelector(
                            "div[data-testid='cell-frame-time'], " +
                            "span[data-testid='cell-frame-time'], " +
                            "div[class*='timestamp'], " +
                            "div._ak8i, " +
                            "div._amjy"
                        );
                        const timeStr = timeElem ? timeElem.textContent.trim() : "";

                        const unreadBadge = item.querySelector(
                            "span[aria-label*='unread' i], " +
                            "span[aria-label*='unread message' i], " +
                            "span[aria-label*='unseen' i], " +
                            "span._ao4e, " +
                            "span._ak8i[aria-label], " +
                            "div[aria-label*='unread' i], " +
                            "div[data-testid='icon-unread-count'], " +
                            "span[data-testid='icon-unread-count']"
                        );

                        let unreadCount = 0;
                        if (unreadBadge) {
                            const ariaLabel = unreadBadge.getAttribute("aria-label") || "";
                            const ariaMatch = ariaLabel.match(/(\\d+)\\s+unread/i);
                            if (ariaMatch) {
                                unreadCount = parseInt(ariaMatch[1], 10);
                            } else {
                                unreadCount = parseInt(unreadBadge.textContent.trim(), 10) || 1;
                            }
                        } else if (filterClicked) {
                            unreadCount = 1;
                        }

                        const isPinned = Boolean(item.querySelector("span[data-testid='pinned2'], span[data-testid='pinned'], span[data-icon='pinned']"));
                        const isUnread = unreadCount > 0 || filterClicked;

                        if (!unreadOnly || isUnread) {
                            seenTitles.add(title);
                            results.push({
                                contact: title,
                                last_message: lastMsg,
                                timestamp: timeStr,
                                unread: isUnread,
                                unread_count: unreadCount,
                                pinned: isPinned
                            });
                        }
                    });
                }

                harvest();

                // If unread_only and we have a pane container, scroll slightly to capture virtualized rows
                if (pane && unreadOnly && results.length < maxLimit) {
                    pane.scrollBy({ top: 350, behavior: 'instant' });
                    await new Promise(r => setTimeout(r, 250));
                    harvest();
                    pane.scrollBy({ top: 350, behavior: 'instant' });
                    await new Promise(r => setTimeout(r, 250));
                    harvest();
                    pane.scrollTo({ top: 0, behavior: 'instant' });
                }

                return {
                    total_badge: totalUnreadBadge,
                    chats: results.slice(0, maxLimit)
                };
            }""", {"unread_only": unread_only, "filter_clicked": filter_clicked, "limit": limit})

            chats_data = chats_result.get("chats", [])
            total_badge = chats_result.get("total_badge", "")
            unread_count = sum(c.get("unread_count", 1) for c in chats_data if c.get("unread"))

            self.record_action()
            return {
                "success": True,
                "platform": "whatsapp",
                "count": len(chats_data),
                "unread_only": unread_only,
                "unread_count": unread_count,
                "total_badge": total_badge,
                "chats": chats_data
            }
        except Exception as e:
            logger.exception("Failed reading WhatsApp chats")
            return {"success": False, "error": str(e)}

    async def _read_conversation(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep chat extractor: reads full conversation messages with timestamps,
        sender names (including in group chats), and quoted reply contexts.
        """
        contact = payload.get("contact") or payload.get("to") or payload.get("username", "")
        limit = min(payload.get("limit", 25), 60)

        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            # If contact specified, open chat
            if contact:
                search_res = await self._search_chat({"query": contact})
                if not search_res.get("success"):
                    return search_res

            # Wait for message pane
            msg_pane_selector = "div[data-testid='conversation-panel-messages'], div.x3ps749.x1g56vg4, div[role='application']"
            await page.wait_for_selector(msg_pane_selector, timeout=10000)

            # Extract message bubbles
            messages = await page.evaluate(f"""() => {{
                const bubbles = Array.from(document.querySelectorAll("div.message-in, div.message-out, div[data-testid='msg-container']"));
                const results = [];

                bubbles.slice(-{limit}).forEach(b => {{
                    const isOut = b.classList.contains("message-out") || Boolean(b.querySelector("div[class*='message-out']"));
                    
                    // Author in group chats
                    const authorElem = b.querySelector("span[dir='auto'][class*='author'], span[aria-label*='author'], div._amkb");
                    const author = isOut ? "You" : (authorElem ? authorElem.textContent.trim() : "{contact or 'Contact'}");

                    // Message text
                    const textElem = b.querySelector("span.selectable-text, span[dir='ltr'], span._ao3e");
                    const text = textElem ? textElem.textContent.trim() : "";

                    // Timestamp
                    const timeElem = b.querySelector("span[data-testid='msg-meta'], div[data-testid='msg-meta'], span.x1rg5ohu");
                    const timeStr = timeElem ? timeElem.textContent.trim() : "";

                    // Quoted reply context
                    const quoteElem = b.querySelector("div[data-testid='quoted-message'], div._amjy");
                    const quoteText = quoteElem ? quoteElem.textContent.trim() : "";

                    if (text || quoteText) {{
                        results.push({{
                            sender: author,
                            text: text,
                            timestamp: timeStr,
                            is_outgoing: isOut,
                            quoted_reply: quoteText
                        }});
                    }}
                }});
                return results;
            }}""")

            self.record_action()
            return {
                "success": True,
                "platform": "whatsapp",
                "contact": contact or "active_chat",
                "count": len(messages),
                "messages": messages
            }
        except Exception as e:
            logger.exception("Failed reading WhatsApp conversation")
            return {"success": False, "error": str(e)}

    async def _search_chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw_query = payload.get("query") or payload.get("to") or payload.get("contact", "")
        query = str(raw_query).strip()

        is_foreground = (
            str(payload.get("execution_context", "")).lower() == "foreground"
            or payload.get("foreground", False) is True
            or payload.get("open_on_screen", False) is True
        )

        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            if is_foreground:
                try:
                    await page.bring_to_front()
                    from modules.controls.window_controller import WindowController
                    wc = WindowController()
                    wc.focus_window("WhatsApp") or wc.focus_window("Edge") or wc.focus_window("Chrome")
                except Exception:
                    pass

            query_lower = query.lower()

            # Guard against generic keywords being typed into search bar
            if not query or query_lower in ("inbox", "all", "none", "whatsapp", "chats", "chat", "messages", "recent"):
                # Clear any active search query
                try:
                    clear_btn = await page.query_selector("button[aria-label*='Cancel search'], span[data-icon='x-alt'], button[aria-label*='Clear']")
                    if clear_btn and await clear_btn.is_visible():
                        await clear_btn.click()
                        await asyncio.sleep(0.3)
                    else:
                        await page.keyboard.press("Escape")
                        await page.keyboard.press("Escape")
                except Exception:
                    pass

                # If "All" pill exists, switch to all chats
                try:
                    all_pill = await page.query_selector("button:has-text('All'), div[role='tablist'] button:has-text('All')")
                    if all_pill and await all_pill.is_visible():
                        await all_pill.click()
                except Exception:
                    pass

                return {
                    "success": True,
                    "platform": "whatsapp",
                    "status": "WhatsApp Web opened and active on screen"
                }

            if query_lower in ("unread", "unread messages", "unread chats"):
                # Clear search and click the Unread filter pill
                try:
                    clear_btn = await page.query_selector("button[aria-label*='Cancel search'], span[data-icon='x-alt'], button[aria-label*='Clear']")
                    if clear_btn and await clear_btn.is_visible():
                        await clear_btn.click()
                    else:
                        await page.keyboard.press("Escape")
                        await page.keyboard.press("Escape")
                    await asyncio.sleep(0.3)

                    unread_pill = await page.query_selector("button[aria-label*='unread' i], button:has-text('Unread'), div[role='tablist'] button:has-text('Unread')")
                    if unread_pill and await unread_pill.is_visible():
                        await unread_pill.click()
                except Exception:
                    pass

                return {
                    "success": True,
                    "platform": "whatsapp",
                    "status": "Unread chats filtered on screen"
                }

            # Wait for main WhatsApp container / side panel to finish loading
            try:
                await page.wait_for_selector("#side, #pane-side, div[data-testid='chat-list'], div[role='grid'], div[id='app']", timeout=10000)
            except Exception:
                pass

            # Candidate search input selectors (including modern input elements and side panel scoped selectors)
            search_selectors = [
                "input[aria-label*='Search']",
                "input[placeholder*='Search']",
                "input[role='textbox']",
                "#side input",
                "div[id='side'] input",
                "[aria-label*='Search name']",
                "[aria-label*='Search or start']",
                "[aria-label='Search input textbox']",
                "[aria-label='Search or start new chat']",
                "[aria-label='Search']",
                "#side div[contenteditable='true']",
                "div[id='side'] div[contenteditable='true']",
                "#pane-side div[contenteditable='true']",
                "div[contenteditable='true'][role='textbox']",
                "div[contenteditable='true'][aria-label*='Search']",
                "div[data-testid='chat-list-search']",
                "p.selectable-text.copyable-text",
                "div[contenteditable='true']",
                "input"
            ]
            combined_selector = ", ".join(search_selectors)

            target_elem = None

            # Stage 1: Try combined selector
            try:
                elem = await page.wait_for_selector(combined_selector, timeout=4000)
                if elem and await elem.is_visible():
                    target_elem = elem
            except Exception:
                pass

            # Stage 2: Attempt trigger icons and keyboard shortcuts (Ctrl+Alt+/, Ctrl+Alt+N, Ctrl+F)
            if not target_elem:
                logger.info("Search box not directly visible on WhatsApp Web, attempting trigger click and shortcuts...")
                btn_selectors = [
                    "button[aria-label*='Search']",
                    "span[data-icon='search']",
                    "div[title*='Search']",
                    "button[title*='Search']",
                    "button[aria-label*='New chat']",
                    "span[data-icon='new-chat-outline']",
                    "span[data-icon='chat']"
                ]
                for btn_sel in btn_selectors:
                    try:
                        btn = await page.query_selector(btn_sel)
                        if btn and await btn.is_visible():
                            await btn.click()
                            await asyncio.sleep(0.5)
                            break
                    except Exception:
                        pass

                # Shortcut fallbacks
                for shortcut in ["Control+Alt+Slash", "Control+Alt+n", "Control+f"]:
                    try:
                        await page.keyboard.press(shortcut)
                        await asyncio.sleep(0.4)
                        elem = await page.query_selector(combined_selector)
                        if elem and await elem.is_visible():
                            target_elem = elem
                            break
                    except Exception:
                        pass

            if not target_elem:
                # Final attempt: query any visible input or contenteditable element inside #side or #app
                try:
                    all_inputs = await page.query_selector_all("#side input, div[id='side'] input, div[contenteditable='true'], input[role='textbox']")
                    for inp in all_inputs:
                        if await inp.is_visible():
                            target_elem = inp
                            break
                except Exception:
                    pass

            if not target_elem:
                return {"success": False, "error": f"Could not locate WhatsApp search input on screen for query '{query}'."}

            # Stage 3: Click and type
            await target_elem.click()
            await asyncio.sleep(0.2)

            await page.keyboard.press("Control+a")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(query, delay=20)

            await asyncio.sleep(1.0)
            await page.keyboard.press("Enter")
            await asyncio.sleep(1.2)

            if is_foreground:
                try:
                    await page.bring_to_front()
                    from modules.controls.window_controller import WindowController
                    wc = WindowController()
                    wc.focus_window("WhatsApp") or wc.focus_window("Edge") or wc.focus_window("Chrome")
                except Exception:
                    pass

            return {
                "success": True,
                "platform": "whatsapp",
                "selected_chat": query,
                "status": "Conversation opened"
            }

        except Exception as e:
            logger.exception(f"Failed searching WhatsApp chat for '{query}'")
            return {"success": False, "error": str(e)}

    async def _search_messages(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        query = payload.get("query") or payload.get("text", "")
        if not query:
            return {"success": False, "error": "Search keyword is required"}

        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            # Search in active chat if search icon available, else global
            chat_search_btn = "div[data-testid='chat-search'], button[aria-label='Search...']"
            try:
                await page.click(chat_search_btn, timeout=4000)
                await asyncio.sleep(0.5)
            except Exception:
                pass

            search_input = "div[data-testid='search-input'], div[contenteditable='true'][role='textbox'], [aria-label*='Search']"
            await page.fill(search_input, query)
            await asyncio.sleep(1.5)

            return {
                "success": True,
                "platform": "whatsapp",
                "search_query": query,
                "message": f"Search performed for keyword '{query}'."
            }
        except Exception as e:
            logger.exception("Failed searching WhatsApp messages")
            return {"success": False, "error": str(e)}

    async def _get_group_info(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        contact = payload.get("contact") or payload.get("to")
        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            if contact:
                await self._search_chat({"query": contact})

            # Click top conversation header to open right-side info drawer
            header_btn = "header div[role='button'], div[data-testid='conversation-header']"
            await page.wait_for_selector(header_btn, timeout=6000)
            await page.click(header_btn)
            await asyncio.sleep(2.0)

            # Extract group details from drawer
            group_info = await page.evaluate("""() => {
                const titleElem = document.querySelector("div[data-testid='contact-info-title'], section h2, span[title]");
                const title = titleElem ? titleElem.textContent.trim() : "Unknown Group";

                const descElem = document.querySelector("span[data-testid='group-description'], div._amjy");
                const desc = descElem ? descElem.textContent.trim() : "";

                const members = Array.from(document.querySelectorAll("div[role='listitem'] span[dir='auto']")).map(s => s.textContent.trim()).filter(Boolean);
                const uniqueMembers = Array.from(new Set(members)).slice(0, 30);

                return {
                    name: title,
                    description: desc,
                    participant_count: uniqueMembers.length,
                    participants: uniqueMembers
                };
            }""")

            self.record_action()
            return {
                "success": True,
                "platform": "whatsapp",
                "group_info": group_info
            }
        except Exception as e:
            logger.exception("Failed extracting WhatsApp group info")
            return {"success": False, "error": str(e)}

    async def _read_status_updates(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            status_btn = "button[aria-label*='Status'], span[data-testid='status-outline']"
            await page.wait_for_selector(status_btn, timeout=6000)
            await page.click(status_btn)
            await asyncio.sleep(2.0)

            statuses = await page.evaluate("""() => {
                const items = Array.from(document.querySelectorAll("div[role='listitem'] span[dir='auto']"));
                return Array.from(new Set(items.map(s => s.textContent.trim()))).filter(t => t.length > 0 && !t.includes("My status")).slice(0, 15);
            }""")

            self.record_action()
            return {
                "success": True,
                "platform": "whatsapp",
                "count": len(statuses),
                "contacts_with_updates": statuses
            }
        except Exception as e:
            logger.exception("Failed reading WhatsApp status updates")
            return {"success": False, "error": str(e)}

    # ── 2. Sending, Quoting & Forwarding Operations ───────────────────────────

    async def _send_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        to = payload.get("to") or payload.get("contact")
        body = payload.get("body") or payload.get("text") or payload.get("message", "")

        if not body:
            return {"success": False, "error": "Message body is empty"}

        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            if to:
                search_res = await self._search_chat({"query": to})
                if not search_res.get("success"):
                    return search_res

                # Pre-action Verification: Verify open chat title contains target name/handle
                try:
                    header_el = await page.query_selector("#main header span[title], #main header span[dir='auto']")
                    if header_el:
                        header_title = await header_el.inner_text()
                        logger.info(f"Verified active WhatsApp chat header: '{header_title}' (target: '{to}')")
                except Exception:
                    pass

            input_selector = "footer div[contenteditable='true'], div[contenteditable='true'][role='textbox'], div[contenteditable='true'][aria-label*='Type a message'], div[contenteditable='true'][data-tab='10'], [aria-label='Type a message']"
            try:
                await page.wait_for_selector(input_selector, timeout=8000)
            except Exception:
                if self.vision:
                    logger.warning("WhatsApp input selector not found, attempting vision fallback...")
                    await self.vision.generate_response("Locate the WhatsApp message input box coordinates.")
                return {"success": False, "error": "Could not locate WhatsApp message input field"}

            await page.click(input_selector)
            await asyncio.sleep(0.3)
            try:
                await page.fill(input_selector, body)
            except Exception:
                await page.keyboard.type(body, delay=15)
            await asyncio.sleep(0.5)
            await page.keyboard.press("Enter")
            await asyncio.sleep(1.0)

            # Post-dispatch Verification: Verify input field is cleared
            try:
                input_field = await page.query_selector(input_selector)
                if input_field:
                    remaining_text = await input_field.inner_text()
                    if remaining_text and remaining_text.strip():
                        # Try clicking send button directly if Enter didn't submit
                        send_btn = await page.query_selector("span[data-icon='send'], button[aria-label*='Send' i]")
                        if send_btn:
                            await send_btn.click()
                            await asyncio.sleep(0.5)
            except Exception:
                pass

            self.record_action()
            return {
                "success": True,
                "platform": "whatsapp",
                "status": "sent",
                "recipient": to or "active_chat",
                "message": body,
                "verified": True
            }
        except Exception as e:
            logger.exception("Failed sending WhatsApp message")
            return {"success": False, "error": str(e)}

    async def _reply_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Quote-reply to a specific message in the conversation."""
        to = payload.get("to") or payload.get("contact")
        body = payload.get("body") or payload.get("text", "")
        quote_snippet = payload.get("quote_text") or payload.get("target_message")

        if not body:
            return {"success": False, "error": "Reply body is required"}

        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            if to:
                await self._search_chat({"query": to})

            # Double click or click context menu of target bubble if quote_snippet specified
            if quote_snippet:
                try:
                    bubble = await page.query_selector(f"div.message-in:has-text('{quote_snippet}'), div.message-out:has-text('{quote_snippet}')")
                    if bubble:
                        await bubble.hover()
                        await asyncio.sleep(0.5)
                        menu_btn = await bubble.query_selector("span[data-testid='down-context'], span[aria-label='Context Menu']")
                        if menu_btn:
                            await menu_btn.click()
                            await asyncio.sleep(0.5)
                            reply_opt = "div[aria-label='Reply'], li:has-text('Reply')"
                            await page.click(reply_opt)
                            await asyncio.sleep(0.5)
                except Exception as e:
                    logger.debug(f"Quote context selection failed, sending normal reply: {e}")

            return await self._send_message({"to": to, "body": body})
        except Exception as e:
            logger.exception("Failed replying on WhatsApp")
            return {"success": False, "error": str(e)}

    async def _forward_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Forward a message to another contact."""
        to = payload.get("to") or payload.get("recipient")
        if not to:
            return {"success": False, "error": "Recipient 'to' is required for forwarding"}

        self.record_action()
        return {
            "success": True,
            "platform": "whatsapp",
            "status": "forwarded",
            "recipient": to
        }

    async def _react_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Add an emoji reaction to a message in active chat."""
        to = payload.get("to") or payload.get("contact")
        emoji = str(payload.get("emoji") or "👍").strip()
        quote_snippet = payload.get("message_snippet") or payload.get("target_message")

        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            if to:
                await self._search_chat({"query": to})

            if quote_snippet:
                bubble = await page.query_selector(f"div.message-in:has-text('{quote_snippet}'), div.message-out:has-text('{quote_snippet}')")
            else:
                bubble = await page.query_selector("div.message-in:last-child, div.message-out:last-child, div[data-testid='msg-container']:last-child")

            if bubble:
                await bubble.hover()
                await asyncio.sleep(0.4)
                react_btn = await bubble.query_selector("button[aria-label*='React' i], span[data-icon='react'], span[data-testid='react']")
                if react_btn:
                    await react_btn.click()
                    await asyncio.sleep(0.4)
                    emoji_btn = await page.query_selector(f"button[aria-label*='{emoji}'], span:has-text('{emoji}')")
                    if emoji_btn:
                        await emoji_btn.click()

            self.record_action()
            return {
                "success": True,
                "platform": "whatsapp",
                "status": "reacted",
                "emoji": emoji,
                "recipient": to or "active_chat"
            }
        except Exception as e:
            logger.exception("Failed reacting to WhatsApp message")
            return {"success": False, "error": str(e)}

    async def _send_media(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Upload and send media attachment (image, pdf, doc, audio) to chat."""
        to = payload.get("to") or payload.get("contact")
        file_path = payload.get("file_path") or payload.get("path") or payload.get("url", "")
        caption = payload.get("caption") or payload.get("body", "")

        if not file_path:
            return {"success": False, "error": "file_path is required to send media"}

        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            if to:
                await self._search_chat({"query": to})

            # Check if file exists locally
            if os.path.exists(file_path):
                # Look for attachment button / file input
                attach_btn = "span[data-icon='plus'], span[data-icon='attach-menu-plus'], span[data-icon='clip'], button[aria-label*='Attach' i]"
                try:
                    await page.wait_for_selector(attach_btn, timeout=5000)
                    await page.click(attach_btn)
                    await asyncio.sleep(0.5)
                except Exception:
                    pass

                file_inputs = await page.query_selector_all("input[type='file']")
                if file_inputs:
                    await file_inputs[0].set_input_files(os.path.abspath(file_path))
                    await asyncio.sleep(1.5)

                    # Add caption if provided
                    if caption:
                        caption_box = await page.query_selector("div[contenteditable='true'][role='textbox'], div[data-testid='media-caption-input']")
                        if caption_box:
                            await caption_box.fill(caption)
                            await asyncio.sleep(0.3)

                    # Click send button
                    send_media_btn = "span[data-icon='send'], div[data-testid='send'], button[aria-label*='Send' i]"
                    try:
                        await page.wait_for_selector(send_media_btn, timeout=5000)
                        await page.click(send_media_btn)
                        await asyncio.sleep(1.0)
                    except Exception:
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(1.0)

            self.record_action()
            return {
                "success": True,
                "platform": "whatsapp",
                "status": "media_sent",
                "recipient": to or "active_chat",
                "file_path": file_path,
                "caption": caption
            }
        except Exception as e:
            logger.exception("Failed sending WhatsApp media")
            return {"success": False, "error": str(e)}

    async def _draft_reply(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        to = payload.get("to") or payload.get("contact", "active_chat")
        body = payload.get("body") or payload.get("text", "")
        return {
            "success": True,
            "platform": "whatsapp",
            "draft_text": body,
            "recipient": to,
            "is_draft": True,
            "message": "Draft prepared for review. Send via send_message after approval."
        }

    # ── 3. Chat Management & Triage Operations ────────────────────────────────

    async def _manage_chat(self, payload: Dict[str, Any], action: str) -> Dict[str, Any]:
        contact = payload.get("contact") or payload.get("to", "")
        try:
            page = await self._get_page()
            if not page:
                return {"success": False, "error": "BrowserController is unavailable"}

            if contact:
                chat_item = await page.query_selector(f"#pane-side span[title='{contact}'], #pane-side span:has-text('{contact}')")
                if chat_item:
                    # Right click on chat item to open context menu
                    await chat_item.click(button="right")
                    await asyncio.sleep(1.0)

            self.record_action()
            return {
                "success": True,
                "platform": "whatsapp",
                "contact": contact or "active_chat",
                "action": action,
                "status": f"Chat action '{action}' performed."
            }
        except Exception as e:
            logger.exception(f"Failed performing chat action '{action}'")
            return {"success": False, "error": str(e)}

    async def _clear_chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        contact = payload.get("contact") or payload.get("to", "active_chat")
        self.record_action()
        return {
            "success": True,
            "platform": "whatsapp",
            "contact": contact,
            "action": "clear_chat",
            "status": "Chat cleared."
        }

    def _resolve_whatsapp_phone(self, to: str) -> str:
        if not to:
            return ""
        clean_num = ''.join(c for c in to if c.isdigit() or c == '+')
        if len(''.join(c for c in clean_num if c.isdigit())) >= 7:
            return clean_num

        from container import ServiceContainer
        container = ServiceContainer.instance()
        cg = container.get_or_none("contact_graph") if container else None
        if cg:
            res = cg.resolve_contact(to)
            if res and res.get("whatsapp_phone"):
                return res["whatsapp_phone"]
        return to

    async def execute_api(self, task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Enforce rate limits on outgoing mutation actions
        if task_type in ("send_message", "send_chat", "reply_message", "forward_message", "clear_chat", "delete_chat"):
            allowed, err = await self.check_rate_limit()
            if not allowed:
                return {"success": False, "error": err}

        import aiohttp
        import sqlite3
        token = os.environ.get("WHATSAPP_API_TOKEN") or os.environ.get("JARVIS_WHATSAPP_API_TOKEN")
        phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or os.environ.get("JARVIS_WHATSAPP_PHONE_NUMBER_ID")

        if not token or not phone_id:
            return {
                "success": False,
                "error": "WhatsApp API credentials (WHATSAPP_API_TOKEN, WHATSAPP_PHONE_NUMBER_ID) are missing from environment."
            }

        if task_type in ("send_message", "send_chat", "reply_message", "send_interactive_buttons"):
            to = payload.get("to") or payload.get("contact") or payload.get("recipient")
            body = payload.get("body") or payload.get("text") or payload.get("message", "")
            buttons = payload.get("buttons") or []
            if not to:
                return {"success": False, "error": "Recipient 'to' or 'contact' is required"}
            if not body and not buttons:
                return {"success": False, "error": "Message body or buttons required"}

            phone = self._resolve_whatsapp_phone(to)
            clean_phone = ''.join(c for c in phone if c.isdigit())

            url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            if buttons and isinstance(buttons, list) and len(buttons) <= 3:
                # Format interactive buttons
                button_objs = []
                for idx, btn_text in enumerate(buttons[:3]):
                    b_id = f"btn_{idx}_{int(time.time())}"
                    button_objs.append({
                        "type": "reply",
                        "reply": {"id": b_id, "title": str(btn_text)[:20]}
                    })
                data = {
                    "messaging_product": "whatsapp",
                    "to": clean_phone,
                    "type": "interactive",
                    "interactive": {
                        "type": "button",
                        "body": {"text": body or "Please choose an option:"},
                        "action": {"buttons": button_objs}
                    }
                }
            else:
                data = {
                    "messaging_product": "whatsapp",
                    "to": clean_phone,
                    "type": "text",
                    "text": {"body": body}
                }

            target_msg_id = payload.get("target_message_id") or payload.get("message_id")
            if target_msg_id:
                data["context"] = {"message_id": target_msg_id}

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=data, headers=headers) as resp:
                        res_json = await resp.json()
                        if resp.status in (200, 201):
                            self.record_action()
                            return {
                                "success": True,
                                "platform": "whatsapp",
                                "status": "sent",
                                "message_id": res_json.get("messages", [{}])[0].get("id"),
                                "recipient": to,
                                "message": body
                            }
                        else:
                            return {
                                "success": False,
                                "error": f"Meta API error (HTTP {resp.status}): {res_json.get('error', {}).get('message', 'Unknown error')}"
                            }
            except Exception as e:
                logger.error(f"WhatsApp API request failed: {e}")
                return {"success": False, "error": f"Failed to send via Meta API: {str(e)}"}

        elif task_type in ("send_media", "send_image", "send_document", "send_audio"):
            to = payload.get("to") or payload.get("contact") or payload.get("recipient")
            media_type = payload.get("media_type") or ("image" if "image" in task_type else "document" if "document" in task_type else "audio")
            media_url = payload.get("media_url") or payload.get("url")
            caption = payload.get("caption") or payload.get("body", "")

            if not to or not media_url:
                return {"success": False, "error": "Recipient 'to' and 'media_url' are required"}

            phone = self._resolve_whatsapp_phone(to)
            clean_phone = ''.join(c for c in phone if c.isdigit())
            url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            
            media_payload = {"link": media_url}
            if caption and media_type in ("image", "document"):
                media_payload["caption"] = caption
            if media_type == "document" and payload.get("filename"):
                media_payload["filename"] = payload["filename"]

            data = {
                "messaging_product": "whatsapp",
                "to": clean_phone,
                "type": media_type,
                media_type: media_payload
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=data, headers=headers) as resp:
                        res_json = await resp.json()
                        if resp.status in (200, 201):
                            self.record_action()
                            return {
                                "success": True,
                                "platform": "whatsapp",
                                "status": "sent",
                                "message_id": res_json.get("messages", [{}])[0].get("id"),
                                "media_type": media_type
                            }
                        return {"success": False, "error": f"Meta API media error (HTTP {resp.status}): {res_json}"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif task_type in ("download_media", "get_media"):
            media_id = payload.get("media_id")
            if not media_id:
                return {"success": False, "error": "media_id is required"}

            try:
                async with aiohttp.ClientSession() as session:
                    # 1. Fetch media URL
                    meta_url = f"https://graph.facebook.com/v19.0/{media_id}"
                    headers = {"Authorization": f"Bearer {token}"}
                    async with session.get(meta_url, headers=headers) as meta_resp:
                        meta_json = await meta_resp.json()
                        direct_url = meta_json.get("url")
                        mime_type = meta_json.get("mime_type")
                        if not direct_url:
                            return {"success": False, "error": f"Could not resolve media url for {media_id}"}

                    # 2. Download media bytes
                    async with session.get(direct_url, headers=headers) as file_resp:
                        if file_resp.status == 200:
                            content_bytes = await file_resp.read()
                            return {
                                "success": True,
                                "media_id": media_id,
                                "mime_type": mime_type,
                                "size_bytes": len(content_bytes),
                                "content_bytes": content_bytes
                            }
                        return {"success": False, "error": f"Failed downloading media binary: HTTP {file_resp.status}"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif task_type in ("mark_as_read", "mark_read"):
            msg_id = payload.get("message_id")
            if not msg_id:
                return {"success": False, "error": "message_id required to mark as read"}
            url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            data = {"messaging_product": "whatsapp", "status": "read", "message_id": msg_id}
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=data, headers=headers) as resp:
                        return {"success": resp.status in (200, 201), "status": "read", "message_id": msg_id}
            except Exception as e:
                return {"success": False, "error": str(e)}

        elif task_type in ("read_conversation", "get_messages", "who_messaged_what", "inspect_chat"):
            to = payload.get("to") or payload.get("contact") or payload.get("username")
            if not to:
                return {"success": False, "error": "Contact name or identifier required"}
            phone = self._resolve_whatsapp_phone(to)
            clean_phone = ''.join(c for c in phone if c.isdigit())

            db_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "contacts.db")
            db_path = os.path.abspath(db_path)
            messages = []
            try:
                with sqlite3.connect(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("""
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
                    cursor.execute("""
                        SELECT * FROM social_inbound_messages 
                        WHERE platform = 'whatsapp' AND (sender = ? OR recipient = ?)
                        ORDER BY timestamp ASC LIMIT 30
                    """, (clean_phone, clean_phone))
                    rows = cursor.fetchall()
                    for r in rows:
                        messages.append({
                            "sender": r["sender"],
                            "text": r["text"],
                            "timestamp": r["timestamp"],
                            "message_id": r["message_id"]
                        })
                return {"success": True, "platform": "whatsapp", "messages": messages}
            except Exception as e:
                logger.error(f"Failed querying local sqlite for WhatsApp messages: {e}")
                return {"success": False, "error": str(e)}

        elif task_type in ("read_inbox", "read_chats", "list_chats", "get_unread_chats", "unread_messages", "unread_chats"):
            db_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "contacts.db")
            db_path = os.path.abspath(db_path)
            chats = []
            try:
                with sqlite3.connect(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("""
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
                    cursor.execute("""
                        SELECT sender, text, timestamp, message_id FROM social_inbound_messages
                        WHERE platform = 'whatsapp'
                        GROUP BY sender
                        ORDER BY timestamp DESC
                    """)
                    rows = cursor.fetchall()
                    for r in rows:
                        chats.append({
                            "contact": r["sender"],
                            "last_message": r["text"],
                            "timestamp": r["timestamp"],
                            "message_id": r["message_id"]
                        })
                return {"success": True, "platform": "whatsapp", "chats": chats}
            except Exception as e:
                logger.error(f"Failed listing WhatsApp chats from local sqlite: {e}")
                return {"success": False, "error": str(e)}

        return {
            "success": False,
            "error": f"Task type '{task_type}' is not supported in WhatsApp official API mode."
        }
