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

logger = logging.getLogger("JARVIS.Browser")

class BrowserController:
    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._search_cache = {}
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
                subprocess.Popen([
                    "cmd", "/c", "start", "msedge",
                    "--remote-debugging-port=9222",
                    f"--user-data-dir={user_data_dir}"
                ])
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
        if not self.page:
            return "Error: Browser not ready."
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
            logger.info(f"Opened URL: {url}")
            return f"Successfully opened {url}."
        except Exception as e:
            logger.error(f"Failed to open URL: {e}")
            return f"Error opening URL: {e}"

    async def close_browser(self):
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
                self.context = None
                self.page = None
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
                await p.close()
                closed = True
                
            if self.context.pages:
                self.page = self.context.pages[-1]
                await self.page.bring_to_front()
            else:
                self.page = None
                
            if closed:
                logger.info(f"Closed tab matching: {domain_or_title}")
            else:
                logger.warning(f"Could not find tab matching: {domain_or_title}")
        except Exception as e:
            logger.error(f"Failed to close website: {e}")
            
        return closed

    async def search(self, query: str):
        query_key = f"google:{query.lower().strip()}"
        now = time.time()
        
        if query_key in self._search_cache:
            last_time = self._search_cache[query_key]
            if now - last_time < 300:
                logger.info(f"Google search for '{query}' is cached. Skipping reload.")
                return "Displayed cached search."
                
        self._search_cache[query_key] = now
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        return await self.open_url(url)

    async def _extract_generic_links(self) -> list:
        results = []
        try:
            headings = await self.page.query_selector_all("h3")
            for h in headings:
                try:
                    title = await h.text_content()
                    if not title: continue
                    
                    # Find closest anchor
                    anchor = await h.evaluate_handle("(node) => node.closest('a') || node.querySelector('a')")
                    if anchor:
                        try:
                            url = await anchor.get_attribute("href")
                            if url and url.startswith("http"):
                                if not any(r["url"] == url for r in results):
                                    results.append({
                                        "title": title,
                                        "url": url,
                                        "snippet": ""  # Snippet extraction simplified for brevity
                                    })
                        finally:
                            await anchor.dispose()  # Release JS heap reference
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Error parsing generic links: {e}")
        finally:
            if 'headings' in locals():
                for h in headings:
                    try:
                        await h.dispose()
                    except Exception:
                        pass
        return results

    async def search_live(self, query: str, num_results: int = 3, engine: str = "google"):
        logger.info(f"Performing live search via Playwright: {query}")
        await self._ensure_driver()
        if not self.page:
            return "Error: WebDriver is not initialized."
            
        try:
            if engine == "wikipedia":
                url = f"https://en.wikipedia.org/w/index.php?search={quote_plus(query)}"
            else:
                url = f"https://www.google.com/search?q={quote_plus(query)}"
            await self.page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(1) # wait for dynamic content
            
            results = await self._extract_generic_links()
            if not results:
                return "Failed to retrieve search results."
                
            top_results = results[:num_results]
            aggregated_content = f"Search Results for '{query}':\n\n"
            
            for i, res in enumerate(top_results, 1):
                aggregated_content += f"[{i}] TITLE: {res['title']}\n    URL: {res['url']}\n"
                
                try:
                    # Use a pooled page to avoid new_page() context overhead
                    pooled_page = await self._get_pooled_page()
                    await pooled_page.goto(res['url'], wait_until="domcontentloaded", timeout=10000)
                    
                    # Extract main text
                    page_text = await pooled_page.evaluate("document.body.innerText")
                    cleaned_text = " ".join([l.strip() for l in page_text.split("\n") if l.strip()])
                    truncated_text = cleaned_text[:2000] + ("..." if len(cleaned_text) > 2000 else "")
                    aggregated_content += f"    CONTENT: {truncated_text}\n\n"
                    
                    await self._return_pooled_page(pooled_page)
                except Exception as e:
                    aggregated_content += f"    CONTENT: [Failed to extract page content: {e}]\n\n"
                    if 'pooled_page' in locals() and not pooled_page.is_closed():
                        await pooled_page.close()
            
            await self.page.bring_to_front()
            return aggregated_content
        except Exception as e:
            return f"Search error: {e}"

    async def search_youtube(self, query: str):
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        return await self.open_url(url)

    async def play_youtube(self, query: str):
        await self.search_youtube(query)
        await asyncio.sleep(2)
        try:
            video = await self.page.query_selector("#video-title")
            if video:
                try:
                    await video.click()
                    logger.info(f"Playing YouTube video for query: {query}")
                    return f"Playing first result for {query}"
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
