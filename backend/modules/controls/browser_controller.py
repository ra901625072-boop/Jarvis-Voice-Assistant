import logging
import time
import threading
import os
import socket
import tempfile
import asyncio
from typing import Optional
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from modules.controls.google_search import GoogleSearch

logger = logging.getLogger("JARVIS.Browser")

class BrowserController:
    """
    BrowserController interacts with the web browser (Edge) using Playwright.

    SYSTEM PROMPT:
    Use BrowserController to open URLs, perform searches, manage tabs, and extract details from web pages. Make sure to ensure Edge CDP port 9222 debugging is active before attempting browser actions.

    SHORT DESCRIPTION:
    Provides programmatic controls for Microsoft Edge via Playwright CDP integration.

    PROCESS:
    1. Ensures Edge is running with remote debugging active on port 9222.
    2. Connects to Edge over Chrome DevTools Protocol (CDP).
    3. Exposes methods to open links, close tabs, run web searches, scrape web contents, switch tabs, control history navigation, click elements, fill forms, and parse page DOM.

    FLOW:
    Caller -> open_url()/search_live() -> _ensure_driver() -> Chromium connect_over_cdp -> Playwright Page navigation -> DOM/HTML scraping & parsing -> Caller
    """
    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.google_search = GoogleSearch(self)
        self._lock = threading.Lock()
        self._page_pool = []
        self._pool_lock = asyncio.Lock()
        
        # We run playwright in a background asyncio loop for synchronous API exposure if needed,
        # but since JARVIS uses async tools, we'll initialize it lazily.
        logger.info("BrowserController initialized (Playwright migration).")

    def _is_port_open(self, port=9222):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex(('127.0.0.1', port)) == 0
        except Exception:
            return False

    async def _ensure_driver(self):
        if self.browser and self.context:
            try:
                # Test connection
                await self.context.pages[0].title()
                return
            except Exception:
                logger.warning("Playwright session is dead. Re-initializing...")
                self.browser = None
                self.context = None

        if not self._is_port_open(9222):
            logger.info("Edge remote debugging port 9222 is closed. Launching Edge...")
            import subprocess
            user_data_dir = os.path.join(tempfile.gettempdir(), "EdgeCDP")
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    [
                        "cmd", "/c", "start", "msedge",
                        "--remote-debugging-port=9222",
                        f"--user-data-dir={user_data_dir}"
                    ],
                    check=False
                )
                await asyncio.sleep(2.0)
            except Exception as e:
                logger.error(f"Failed to auto-launch Edge: {e}")

        try:
            if not self.playwright:
                self.playwright = await async_playwright().start()
            
            self.browser = await self.playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
            self.context = self.browser.contexts[0]
            if self.context.pages:
                self.page = self.context.pages[0]
            else:
                self.page = await self.context.new_page()
            logger.info("Playwright bound to Edge remote debugging port 9222 successfully.")
        except Exception as e:
            logger.error(f"Failed to connect Playwright to Edge: {e}")


    async def _get_pooled_page(self):
        async with self._pool_lock:
            if self._page_pool:
                for p in self._page_pool:
                    if not p.is_closed():
                        self._page_pool.remove(p)
                        return p
        return await self.context.new_page()

    async def _return_pooled_page(self, page):
        try:
            if page.is_closed():
                return
            async with self._pool_lock:
                if len(self._page_pool) < 3:
                    self._page_pool.append(page)
                else:
                    await page.close()
        except Exception:
            pass

    def normalize_url(self, url: str) -> str:
        if "." not in url:
            return f"https://www.google.com/search?q={quote_plus(url)}"
        if not url.startswith(("http://", "https://")):
            return "https://" + url
        return url

    async def open_url(self, url: str):
        url = self.normalize_url(url)
        await self._ensure_driver()
        
        # Acquire page from browser pool
        page = await self._get_pooled_page()
        if not page:
            return "Error: Browser not ready."
        
        try:
            self.page = page
            await page.bring_to_front()
            await page.goto(url, wait_until="domcontentloaded")
            logger.info(f"Opened URL using pooled page: {url}")
            return f"Successfully opened {url}."
        except Exception as e:
            logger.error(f"Failed to open URL: {e}")
            await self._return_pooled_page(page)
            return f"Error opening URL: {e}"

    async def close_browser(self):
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
                self.context = None
                self.page = None
                async with self._pool_lock:
                    self._page_pool.clear()
                logger.info("Browser closed.")
        except Exception as e:
            logger.error(f"Failed to close browser: {e}")

    async def close_website(self, domain_or_title: str):
        await self._ensure_driver()
        if not self.context:
            return False
            
        target = domain_or_title.lower()
        closed = False
        
        try:
            pages_to_close = []
            for p in self.context.pages:
                url = p.url.lower()
                title = await p.title()
                title = title.lower()
                if target in url or target in title:
                    pages_to_close.append(p)
                    
            for p in pages_to_close:
                await self._return_pooled_page(p)
                closed = True
                
            if self.context.pages:
                # Filter out closed or pooled blank pages to focus the active user tab
                visible_pages = [p for p in self.context.pages if p.url != "about:blank" and not p.is_closed()]
                if visible_pages:
                    self.page = visible_pages[-1]
                    await self.page.bring_to_front()
                else:
                    self.page = self.context.pages[-1]
                    await self.page.bring_to_front()
            else:
                self.page = None
                
            if closed:
                logger.info(f"Closed and returned tab matching: {domain_or_title}")
            else:
                logger.warning(f"Could not find tab matching: {domain_or_title}")
        except Exception as e:
            logger.error(f"Failed to close website: {e}")
            
        return closed

    async def search(self, query: str):
        return await self.google_search.search(query)

    async def search_live(self, query: str, num_results: int = 3, engine: str = "google"):
        return await self.google_search.search_live(query, num_results, engine)

    async def search_youtube(self, query: str):
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        return await self.open_url(url)

    async def _youtube_ad_watcher(self, page):
        logger.info("Starting YouTube ad watcher background task...")
        # Monitor the video for up to 10 minutes (300 iterations * 2s)
        for _ in range(300):
            try:
                if page.is_closed():
                    break
                if "youtube.com" not in page.url:
                    break
                
                # Check standard selectors for Skip Ad button on YouTube
                skip_selectors = [
                    ".ytp-ad-skip-button",
                    ".ytp-ad-skip-button-modern",
                    ".ytp-ad-skip-button-text",
                    ".ytp-ad-skip-button-container",
                    ".ytp-skip-ad-button",
                    "button.ytp-ad-skip-button"
                ]
                
                for selector in skip_selectors:
                    btn = await page.query_selector(selector)
                    if btn:
                        is_visible = await btn.is_visible()
                        if is_visible:
                            logger.info(f"YouTube Ad Watcher: Found skip button using selector '{selector}'. Clicking it!")
                            await btn.click()
                            await asyncio.sleep(1)
                            break
                        await btn.dispose()
            except Exception as e:
                # Page closed or navigation occurred, break or ignore safely
                logger.debug(f"YouTube Ad Watcher update check failed/ignored: {e}")
            await asyncio.sleep(2)
        logger.info("YouTube ad watcher background task finished.")

    async def play_youtube(self, query: str):
        await self.search_youtube(query)
        await asyncio.sleep(2)
        try:
            video = await self.page.query_selector("#video-title")
            if video:
                try:
                    await video.click()
                    logger.info(f"Playing YouTube video for query: {query}")
                    # Launch ad watcher in background context
                    asyncio.create_task(self._youtube_ad_watcher(self.page))
                    return f"Playing first result for {query} and auto-skipping ads in the background."
                finally:
                    await video.dispose()
            return "Could not find video title to click."
        except Exception as e:
            logger.error(f"Failed to play YouTube video: {e}")
            return f"Error: {e}"

    async def switch_tab(self, keyword: str):
        await self._ensure_driver()
        if not self.context:
            return False
            
        keyword = keyword.lower()
        try:
            for p in self.context.pages:
                url = p.url.lower()
                title = await p.title()
                if keyword in title.lower() or keyword in url:
                    self.page = p
                    await self.page.bring_to_front()
                    logger.info(f"Switched to tab matching: {keyword}")
                    return True
        except Exception as e:
            logger.error(f"Failed to switch tab: {e}")
        return False

    async def list_tabs(self):
        await self._ensure_driver()
        tabs = []
        if not self.context:
            return tabs
            
        try:
            for p in self.context.pages:
                title = await p.title()
                tabs.append({
                    "title": title,
                    "url": p.url
                })
        except Exception as e:
            logger.error(f"Failed to list tabs: {e}")
            
        return tabs

    async def refresh_tab(self):
        if self.page:
            try:
                await self.page.reload()
                logger.info("Tab refreshed.")
                return "Refreshed."
            except Exception as e:
                return f"Failed to refresh tab: {e}"

    async def go_back(self):
        if self.page:
            try:
                await self.page.go_back()
                logger.info("Navigated back.")
                return "Went back."
            except Exception as e:
                return f"Failed to go back: {e}"

    async def go_forward(self):
        if self.page:
            try:
                await self.page.go_forward()
                logger.info("Navigated forward.")
                return "Went forward."
            except Exception as e:
                return f"Failed to go forward: {e}"

    async def get_current_page_info(self):
        info = {"title": "", "url": ""}
        if self.page:
            try:
                info["title"] = await self.page.title()
                info["url"] = self.page.url
            except Exception as e:
                logger.error(f"Failed to get current page info: {e}")
        return info

    async def click_dom_element(self, selector: str):
        await self._ensure_driver()
        if not self.page: return "Browser not ready."
        try:
            await self.page.click(selector)
            return f"Clicked element matching {selector}"
        except Exception as e:
            return f"Failed to click element: {e}"
            
    async def fill_form(self, selector: str, text: str):
        await self._ensure_driver()
        if not self.page: return "Browser not ready."
        try:
            await self.page.fill(selector, text)
            return f"Filled text in {selector}"
        except Exception as e:
            return f"Failed to fill form: {e}"

    async def extract_page_structure(self):
        await self._ensure_driver()
        if not self.page: return "Browser not ready."
        try:
            # Simple JS to extract interactive elements
            js = """() => {
                const elements = document.querySelectorAll('a, button, input, select, textarea');
                return Array.from(elements).map(e => ({
                    tag: e.tagName,
                    text: e.innerText || e.value || e.placeholder || '',
                    id: e.id,
                    className: e.className
                })).filter(e => e.text || e.id);
            }"""
            structure = await self.page.evaluate(js)
            return structure
        except Exception as e:
            return f"Failed to extract structure: {e}"
