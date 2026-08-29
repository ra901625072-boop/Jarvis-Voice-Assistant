"""
modules/browser/controller.py — Enterprise Playwright Browser Controller with Tab Ownership & Guardrails.

Provides unified browser session control, tab protection against closure, CDP remote debugging,
perception extraction, and action execution.
"""

import os
import socket
import logging
import threading
import asyncio
import tempfile
from typing import Optional, Dict, Any, List
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from modules.browser.tab_manager import TabManager, TabRecord
from modules.browser.policy import BrowserPolicyEngine, PolicyDecision, PermissionLevel
from modules.browser.perception.engine import BrowserPerceptionEngine, PageObservation
from modules.browser.actions.vocabulary import BrowserAction, BrowserActionType, ActionExecutionResult
from modules.browser.actions.executor import BrowserActionExecutor
from modules.browser.safety.captcha_guard import CaptchaGuard
from modules.browser.safety.auth_guard import AuthGuard
from modules.controls.google_search import GoogleSearch

logger = logging.getLogger("JARVIS.Browser.Controller")


class ActionResult(dict):
    @property
    def success(self) -> bool:
        return self.get("success", False)

    @property
    def message(self) -> str:
        return self.get("message", "")

    def __str__(self):
        return self.message


class BrowserController:
    """
    Core browser controller wrapping Playwright CDP with built-in tab ownership,
    safety guardrails, perception, and action execution.
    """

    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        # Subsystems
        self.tab_manager = TabManager()
        self.policy_engine = BrowserPolicyEngine(self.tab_manager)
        self.perception_engine = BrowserPerceptionEngine()
        self.action_executor = BrowserActionExecutor(self.tab_manager, self.policy_engine)
        self.google_search = GoogleSearch(self)
        
        self._lock = threading.Lock()
        self._page_pool = []
        self._pool_lock = None
        logger.info("BrowserController (Enterprise Subsystem) initialized.")

    def _is_port_open(self, port: int = 9222) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(('127.0.0.1', port)) == 0
        except Exception:
            return False

    def _is_cdp_ready(self, port: int = 9222) -> bool:
        import urllib.request
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.0) as res:
                return res.status == 200
        except Exception:
            return False

    def _kill_stale_profile_processes(self, user_data_dir: str):
        try:
            import psutil
            norm_dir = os.path.normpath(user_data_dir).lower()
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info.get('cmdline') or []
                    cmdline_str = " ".join(cmdline).lower()
                    if norm_dir in cmdline_str or "--remote-debugging-port=9222" in cmdline_str:
                        logger.info(f"Terminating stale browser process {proc.info['pid']} ({proc.info['name']})...")
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            logger.debug(f"Process cleanup note: {e}")

        # Clean stale lock files
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
            lock_path = os.path.join(user_data_dir, lock_name)
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                except Exception:
                    pass

    async def _ensure_driver(self):
        """Ensures Playwright CDP connection is active and synchronizes tabs."""
        if self.browser and self.context:
            try:
                if self.context.pages:
                    await self.context.pages[0].title()
                    return
            except Exception:
                logger.warning("Playwright connection lost. Reconnecting...")
                self.browser = None
                self.context = None
                self.page = None

        if not self.playwright:
            self.playwright = await async_playwright().start()

        # Load profile directory and browser type from settings
        try:
            from config.settings import JARVIS_BROWSER_PROFILE_DIR, JARVIS_BROWSER_TYPE, JARVIS_BROWSER_HEADLESS
            user_data_dir = JARVIS_BROWSER_PROFILE_DIR
            channel_name = JARVIS_BROWSER_TYPE if JARVIS_BROWSER_TYPE in ("chrome", "msedge") else "msedge"
            headless_mode = JARVIS_BROWSER_HEADLESS
        except Exception:
            user_data_dir = os.path.join(tempfile.gettempdir(), "JarvisBrowserProfile")
            channel_name = "msedge"
            headless_mode = False

        os.makedirs(user_data_dir, exist_ok=True)
        cmd_app = "chrome" if channel_name == "chrome" else "msedge"

        if not self._is_cdp_ready(9222):
            self._kill_stale_profile_processes(user_data_dir)
            logger.info(f"CDP port 9222 is not ready. Launching {cmd_app}...")
            import subprocess
            try:
                from modules.controls.app_controller import AppController
                app_ctrl = AppController()
                exe_path = app_ctrl._find_app_path(cmd_app)
                if not exe_path or not os.path.exists(exe_path):
                    exe_path = cmd_app

                await asyncio.to_thread(
                    subprocess.run,
                    [
                        "cmd", "/c", "start", "", exe_path,
                        "--remote-debugging-port=9222",
                        f"--user-data-dir={user_data_dir}",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "about:blank"
                    ],
                    shell=True
                )
            except Exception as launch_err:
                logger.error(f"Failed to launch browser: {launch_err}")

            # Wait for port to become active
            for _ in range(30):
                if self._is_cdp_ready(9222):
                    break
                await asyncio.sleep(0.3)

        # Connect via CDP
        try:
            self.browser = await self.playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
            contexts = self.browser.contexts
            self.context = contexts[0] if contexts else await self.browser.new_context()
            
            # Synchronize active pages with TabManager
            for p in self.context.pages:
                self.tab_manager.register_tab(p, owner="system")

            if self.context.pages:
                self.page = self.context.pages[-1]
            else:
                self.page = await self.context.new_page()
                self.tab_manager.register_tab(self.page, owner="system")

            logger.info("Successfully connected to Playwright browser via CDP.")
        except Exception as e:
            logger.error(f"CDP connection failed: {e}")
            raise RuntimeError(f"Could not connect to browser on port 9222: {e}")

    def is_server_tab(self, page_or_url) -> bool:
        """
        Determines if a page or URL belongs to the protected JARVIS Control Server.
        """
        if isinstance(page_or_url, str):
            return TabManager.is_server_url(page_or_url)
        return self.tab_manager.is_protected(page_or_url)

    async def get_or_create_content_page(self, task_id: Optional[str] = None) -> Page:
        """
        Returns an active, non-protected content page for research or automation.
        If current page is protected (e.g. server tab), creates a dedicated new tab.
        """
        await self._ensure_driver()

        # Check existing pages in context
        for p in self.context.pages:
            if not p.is_closed() and not self.is_server_tab(p):
                self.page = p
                self.tab_manager.register_tab(p, owner=task_id or "user")
                return p

        # Create new tab if all are protected or closed
        new_p = await self.context.new_page()
        self.tab_manager.register_tab(new_p, owner=task_id or "agent:task", parent_task_id=task_id)
        self.page = new_p
        return new_p

    async def create_new_tab(self, url: Optional[str] = None, owner: str = "agent", task_id: Optional[str] = None) -> str:
        """Creates a registered new tab and navigates optionally."""
        await self._ensure_driver()
        new_page = await self.context.new_page()
        record = self.tab_manager.register_tab(new_page, owner=owner, parent_task_id=task_id)
        self.page = new_page

        target_url = url or "about:blank"
        if target_url != "about:blank":
            await new_page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
            self.tab_manager.update_tab_state(new_page, url=new_page.url)

        await new_page.bring_to_front()
        self._focus_browser_window()
        return f"Created new tab {record.tab_id} with URL '{target_url}'"

    def _focus_browser_window(self):
        try:
            import pygetwindow as gw
            candidates = ["Edge", "Chrome", "Browser", "JARVIS"]
            for title in candidates:
                wins = gw.getWindowsWithTitle(title)
                if wins:
                    win = wins[0]
                    if win.isMinimized:
                        win.restore()
                    win.activate()
                    break
        except Exception:
            pass

    async def ensure_separate_browser(self, start_url: Optional[str] = None) -> bool:
        """Ensures dedicated browser window is open and focused."""
        try:
            page = await self.get_or_create_content_page()
            if start_url:
                await page.goto(start_url, wait_until="domcontentloaded", timeout=15000)
            await page.bring_to_front()
            self._focus_browser_window()
            return True
        except Exception as e:
            logger.error(f"ensure_separate_browser failed: {e}")
            return False

    async def open_url(self, url: str, timeout: int = 15000, task_id: Optional[str] = None) -> str:
        """Navigates to URL safely on a non-protected tab."""
        try:
            page = await self.get_or_create_content_page(task_id=task_id)
            
            # Policy check: ensure we don't navigate over server tab
            current_tab = self.tab_manager.get_tab(page)
            decision = self.policy_engine.validate_navigation(url, current_tab, requester_id=task_id)
            if not decision.allowed:
                # Spawn new tab instead
                page = await self.context.new_page()
                self.tab_manager.register_tab(page, owner=task_id or "agent")
                self.page = page

            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            self.tab_manager.update_tab_state(page, url=page.url)
            await page.bring_to_front()
            self._focus_browser_window()
            return f"Successfully opened {url} in separate browser."
        except Exception as e:
            logger.exception(f"open_url failed: {e}")
            return f"Failed to open URL '{url}': {e}"

    async def close_website(self, domain_or_title: str, requester_id: Optional[str] = None) -> bool:
        """
        Closes tabs matching domain/title while strictly enforcing tab protection.
        """
        try:
            await self._ensure_driver()
            kw = domain_or_title.lower().strip()
            closed_any = False

            if not self.context or not self.context.pages:
                return False

            for p in list(self.context.pages):
                if hasattr(p, "is_closed") and p.is_closed():
                    continue

                # Ensure tab is registered in tab_manager if not already
                tab_record = self.tab_manager.get_tab(p)
                if not tab_record:
                    tab_record = self.tab_manager.register_tab(p, owner="system")

                # Enforce Policy Engine check
                decision = self.policy_engine.validate_tab_close(tab_record, requester_id=requester_id)
                if not decision.allowed:
                    logger.info(f"Skipping tab close for {getattr(p, 'url', '')}: {decision.reason}")
                    continue

                url = (getattr(p, "url", "") or "").lower()
                title = ""
                try:
                    if hasattr(p, "title"):
                        res_title = p.title()
                        title = (await res_title if asyncio.iscoroutine(res_title) else res_title or "").lower()
                except Exception:
                    pass

                if kw in url or kw in title:
                    logger.info(f"Closing non-protected tab matching '{kw}': {url}")
                    self.tab_manager.unregister_tab(p)
                    await self._return_pooled_page(p)
                    closed_any = True

            return closed_any
        except Exception as e:
            logger.error(f"close_website failed: {e}")
            return False

    async def _return_pooled_page(self, page: Page):
        try:
            if not page.is_closed():
                await page.close()
        except Exception:
            pass

    async def close_browser(self, force: bool = False) -> bool:
        """Closes browser context and Playwright instance cleanly."""
        try:
            if self.context:
                # Check for protected tabs
                for p in list(self.context.pages):
                    if not force and self.is_server_tab(p):
                        logger.warning("close_browser refused without force: Protected server tab is open.")
                        return False
                    if not p.is_closed():
                        await p.close()

            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()

            self.browser = None
            self.context = None
            self.page = None
            self.playwright = None
            logger.info("Browser closed successfully.")
            return True
        except Exception as e:
            logger.error(f"close_browser error: {e}")
            return False

    async def list_tabs(self) -> List[Dict[str, Any]]:
        """Returns metadata list of all active tabs."""
        await self._ensure_driver()
        tabs = []
        for idx, p in enumerate(self.context.pages):
            if not p.is_closed():
                record = self.tab_manager.register_tab(p)
                url = p.url or "about:blank"
                title = ""
                try:
                    title = await p.title()
                except Exception:
                    pass
                tabs.append({
                    "index": idx,
                    "tab_id": record.tab_id,
                    "url": url,
                    "title": title,
                    "owner": record.owner,
                    "protected": record.protected,
                    "is_active": (p == self.page),
                })
        return tabs

    async def switch_tab(self, keyword_or_tab_id: str) -> bool:
        """Switches focus to matching tab."""
        await self._ensure_driver()
        kw = keyword_or_tab_id.lower().strip()
        for p in self.context.pages:
            if p.is_closed():
                continue
            tab = self.tab_manager.get_tab(p)
            if tab and tab.tab_id == kw:
                self.page = p
                await p.bring_to_front()
                self._focus_browser_window()
                return True
            
            url = (p.url or "").lower()
            title = ""
            try:
                title = (await p.title() or "").lower()
            except Exception:
                pass
            if kw in url or kw in title:
                self.page = p
                await p.bring_to_front()
                self._focus_browser_window()
                return True
        return False

    async def refresh_tab(self) -> bool:
        if self.page and not self.page.is_closed():
            await self.page.reload()
            return True
        return False

    async def go_back(self) -> bool:
        if self.page and not self.page.is_closed():
            await self.page.go_back()
            return True
        return False

    async def go_forward(self) -> bool:
        if self.page and not self.page.is_closed():
            await self.page.go_forward()
            return True
        return False

    async def get_current_page_info(self) -> Dict[str, Any]:
        await self._ensure_driver()
        if not self.page or self.page.is_closed():
            return {"title": "", "url": "", "is_protected": False}
        tab = self.tab_manager.get_tab(self.page)
        return {
            "tab_id": tab.tab_id if tab else "current",
            "title": await self.page.title() if self.page else "",
            "url": self.page.url if self.page else "",
            "is_protected": tab.protected if tab else self.is_server_tab(self.page),
        }

    async def extract_page_structure(self) -> List[Dict[str, Any]]:
        """Extracts interactive elements from current page."""
        await self._ensure_driver()
        if not self.page:
            return []
        elements = await self.perception_engine.observe(self.page)
        return [el.to_dict() for el in elements.interactive_elements]

    async def click_dom_element(self, selector: str, timeout: int = 10000) -> ActionResult:
        await self._ensure_driver()
        action = BrowserAction(action=BrowserActionType.CLICK, target=selector, timeout_ms=timeout)
        res = await self.action_executor.execute(action, self.page, self.tab_manager.get_tab(self.page))
        return ActionResult({"success": res.success, "message": res.message})

    async def fill_form(self, selector: str, text: str, timeout: int = 10000) -> ActionResult:
        await self._ensure_driver()
        action = BrowserAction(action=BrowserActionType.TYPE, target=selector, text=text, timeout_ms=timeout)
        res = await self.action_executor.execute(action, self.page, self.tab_manager.get_tab(self.page))
        return ActionResult({"success": res.success, "message": res.message})

    async def search(self, query: str):
        return await self.google_search.search(query)

    async def search_live(self, query: str, num_results: int = 3, engine: str = "google"):
        return await self.google_search.search_live(query, num_results=num_results, engine=engine)

    async def search_youtube(self, query: str):
        return await self.google_search.search_youtube(query)

    async def play_youtube(self, query: str):
        return await self.google_search.play_youtube(query)
