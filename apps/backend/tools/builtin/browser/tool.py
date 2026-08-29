"""
toolsets/browser_tools.py — BrowserTools toolset.

Extracted from agent.py. Uses the fixed async_ttl_cache from toolsets/base.py.
"""
import asyncio
import os
import json
import warnings
import logging
from livekit.agents import llm
from tools.builtin.base import JarvisToolset, async_ttl_cache
from modules.controls.browser_controller import BrowserController
from modules.security.manager import SecurityManager

_logger = logging.getLogger("JARVIS.BrowserTools")


def _fetch_web_page_content(url: str, timeout: float = 5.0) -> str:
    """Fetch body text from a webpage URL natively with a strict timeout."""
    import urllib.request
    import re
    if not url or not url.startswith("http"):
        return ""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="ignore")
            html = re.sub(r'<script.*?>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<style.*?>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', html)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:1500] if text else ""
    except Exception:
        return ""


class BrowserTools(JarvisToolset):
    """
    BrowserTools handles browser operations including navigating pages,
    listing/closing tabs, searching, and scraping web pages.

    SYSTEM PROMPT:
    Use BrowserTools to read web resources, perform online research, play videos,
    and inspect page DOM elements. Use google search or search_live depending on
    requirements.

    SHORT DESCRIPTION:
    Exposes browser control tools including tab management, web page scraping,
    form inputs, and live Google/YouTube queries.

    PROCESS:
    1. Lazily instantiates BrowserController.
    2. Dispatches navigation, tab manipulation, and interactive page actions
       using Playwright browser interface.
    3. Handles fallback paths for API search versus live scrapers.

    FLOW:
    Agent -> Tool call -> BrowserController -> Playwright CDP session
          -> Microsoft Edge -> Agent
    """

    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self._browser_ctrl = None

    @property
    def browser_ctrl(self) -> BrowserController:
        if self._browser_ctrl is None:
            try:
                from container import ServiceContainer
                c = ServiceContainer.instance()
                self._browser_ctrl = c.get_or_none("browser_controller") if c else None
            except Exception:
                self._browser_ctrl = None
            if self._browser_ctrl is None:
                self._browser_ctrl = BrowserController()
        return self._browser_ctrl

    @llm.function_tool(description="Open or launch JARVIS's dedicated separate browser window on screen")
    async def open_separate_browser(self, start_url: str = "") -> str:
        url_arg = start_url.strip() if start_url and start_url.strip() else None
        res = await self.safe_execute(self.browser_ctrl.ensure_separate_browser, url_arg)
        if res is True or (isinstance(res, str) and not res.startswith("Error:")):
            return "JARVIS separate dedicated browser is opened, focused, and ready for operations."
        return f"Could not launch separate browser: {res}"

    @llm.function_tool(description="Open a specific URL in the separate browser")
    async def open_url(self, url: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"]:
            return "Error: Invalid URL scheme. Only http and https are allowed."
        return await self.safe_execute(
            self.browser_ctrl.open_url, url, success_msg=f"Opened {url} in the separate browser."
        )

    @llm.function_tool(
        description="Create a new browser tab without closing or navigating away from existing tabs, optionally navigating to a URL."
    )
    async def create_new_tab(self, url: str = "") -> str:
        url_arg = url.strip() if url and url.strip() else None
        return await self.safe_execute(
            self.browser_ctrl.create_new_tab,
            url_arg,
            success_msg="Created new browser tab."
        )

    @llm.function_tool(description="Click on an interactive DOM element using a CSS selector")
    async def click_browser_element(self, selector: str) -> str:
        return await self.safe_execute(self.browser_ctrl.click_dom_element, selector)

    @llm.function_tool(description="Fill text into a form input element matching a CSS selector")
    async def fill_browser_form(self, selector: str, text: str) -> str:
        return await self.safe_execute(self.browser_ctrl.fill_form, selector, text)

    @llm.function_tool(description="Extract interactive elements structure from the current page DOM")
    async def get_browser_page_structure(self) -> str:
        res = await self.safe_execute(self.browser_ctrl.extract_page_structure)
        if isinstance(res, list):
            return json.dumps(res, indent=2)
        return str(res)

    @llm.function_tool(description="Close a specific website tab by domain or title")
    async def close_website(self, domain_or_title: str) -> str:
        return await self.safe_execute(
            self.browser_ctrl.close_website,
            domain_or_title,
            success_msg=f"Closed website tab matching '{domain_or_title}'.",
            error_msg=f"Could not find or close website tab matching '{domain_or_title}'.",
        )

    @llm.function_tool(
        description=(
            "Search Google and physically open/show the search results page to the user in their "
            "browser window. Use this when the user asks to search on browser, open the browser to search, "
            "or show search results on screen."
        )
    )
    @async_ttl_cache(ttl=300)
    async def search_google(self, query: str) -> str:
        return await self.safe_execute(
            self.browser_ctrl.search,
            query,
            success_msg=f"Opened Google search results for '{query}'.",
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _decompose_query(self, query: str) -> list:
        """Use Gemini to split a compound query into individual search queries, ensuring entities are preserved."""
        if len(query.split()) <= 3 and "," not in query and " and " not in query and " aur " not in query:
            return [query]

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return [query]

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            prompt = (
                f'You are a search query optimizer. Analyze the following search query: "{query}"\n\n'
                "CRITICAL RULE: DO NOT split proper nouns, entity names, fictional/pop-culture names (e.g. 'Cockroach Janta Party'), "
                "or brand names into separate individual words or separate queries. Keep proper noun phrases intact as single search queries.\n"
                "Determine if the query asks for multiple distinct topics that should be searched in simplified queries.\n"
                "Return ONLY a raw JSON list of strings. Do not include markdown code block wrappers."
            )

            from config.settings import GEMINI_FALLBACK_CHAIN
            response = None
            for model_name in GEMINI_FALLBACK_CHAIN:
                try:
                    response = await client.aio.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.1,
                            response_mime_type="application/json",
                        ),
                    )
                    if response and response.text:
                        break
                except Exception as g_err:
                    _logger.debug(f"Query optimizer model {model_name} failed: {g_err}")
                    continue

            if response and response.text:
                text = response.text.strip()
                if text.startswith("```"):
                    first_nl = text.find("\n")
                    if first_nl != -1:
                        text = text[first_nl:].strip()
                    if text.endswith("```"):
                        text = text[:-3].strip()
                if text.startswith("json\n"):
                    text = text[5:].strip()

                queries = json.loads(text)
                if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                    if query not in queries:
                        queries.insert(0, query)
                    return queries
        except Exception as e:
            _logger.warning(f"Decomposing query failed: {e}. Using original query.")

        return [query]

    async def _execute_single_search(self, query: str, engine: str = "google") -> str:
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=RuntimeWarning)
                warnings.filterwarnings("ignore", category=UserWarning)
                warnings.simplefilter("ignore")
                try:
                    from duckduckgo_search import DDGS
                except ImportError:
                    from ddgs import DDGS  # type: ignore

            def _do_ddg_search():
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=RuntimeWarning)
                    warnings.filterwarnings("ignore", category=UserWarning)
                    warnings.simplefilter("ignore")
                    with DDGS(timeout=5) as ddgs:
                        return list(ddgs.text(query, max_results=5))

            results = await asyncio.to_thread(_do_ddg_search)
            if results:
                aggregated = f"Fast API Search Results for '{query}':\n\n"

                # Deep crawl top 3-4 website URLs to analyze full page contents
                async def _crawl_one(res):
                    url = res.get('href', '')
                    if url:
                        content = await asyncio.to_thread(_fetch_web_page_content, url, 5.0)
                        return url, content
                    return url, ""

                top_urls = results[:4]
                crawled_pages = await asyncio.gather(*[_crawl_one(r) for r in top_urls])
                page_content_map = {url: content for url, content in crawled_pages if content}

                for i, res in enumerate(results, 1):
                    url = res.get('href', '')
                    snippet = res.get('body', '')
                    deep_text = page_content_map.get(url, '')
                    
                    aggregated += f"[{i}] TITLE: {res.get('title')}\n"
                    aggregated += f"    URL: {url}\n"
                    aggregated += f"    SNIPPET: {snippet}\n"
                    if deep_text:
                        aggregated += f"    DEEP PAGE CONTENT: {deep_text}\n"
                    aggregated += "\n"
                return aggregated
            else:
                raise ValueError("DuckDuckGo returned empty results")
        except Exception as e:
            _logger.warning(f"Fast-path DDG search failed for '{query}': {e}. Falling back to Browser Search.")
            try:
                # Fallback 1: Try Playwright-based search_live first
                browser_res = await self.browser_ctrl.search_live(query, num_results=3)
                if browser_res and not browser_res.startswith("Failed to retrieve") and not browser_res.startswith("Error:"):
                    return f"Browser Search Results for '{query}':\n\n{browser_res}"
                _logger.warning("Browser search failed or returned empty. Falling back to Gemini search.")
            except Exception as browser_e:
                _logger.warning(f"Browser search fallback failed: {browser_e}. Falling back to Gemini search.")

            # Fallback 2: Gemini Google Search tool
            try:
                from google import genai
                from google.genai import types
                api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
                if not api_key:
                    return f"Search failed for '{query}': {e} (No API key for fallback)"

                client = genai.Client(api_key=api_key)
                prompt = f"Search the web for the following query, analyze the information, and provide a clear answer:\nQuery: {query}"
                config = types.GenerateContentConfig(tools=[{"google_search": {}}])
                
                from config.settings import GEMINI_FALLBACK_CHAIN
                response = None
                for model_name in GEMINI_FALLBACK_CHAIN:
                    try:
                        response = await client.aio.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=config,
                        )
                        if response and response.text:
                            return f"Google Search Fallback Answer for '{query}':\n\n{response.text.strip()}"
                    except Exception as s_err:
                        _logger.debug(f"Search fallback model {model_name} failed: {s_err}")
                        continue
                return f"Google Search Fallback returned empty for '{query}'."
            except Exception as fallback_e:
                _logger.warning(f"Google Search fallback failed: {fallback_e}")
                return f"Search failed for '{query}': {e}"

    @llm.function_tool(
        description=(
            "Search live for a query, scrape/parse the results, extract contents, and return the "
            "answer text directly. Use this when the user asks to 'tell' them the result or answer "
            "a query directly (e.g., 'tell me...'). This automatically falls back to Wikipedia if "
            "Google search is unsatisfactory or blocked."
        )
    )
    @async_ttl_cache(ttl=300)
    async def search_google_live(self, query: str, engine: str = "google") -> str:
        queries = await self._decompose_query(query)
        if not queries:
            queries = [query]
        if len(queries) <= 1:
            return await self._execute_single_search(queries[0], engine)

        _logger.info(f"Decomposed query '{query}' into: {queries}. Running searches concurrently...")
        tasks = [self._execute_single_search(q, engine) for q in queries]
        results = await asyncio.gather(*tasks)

        aggregated = "Decomposed Search Results (searched one by one):\n\n"
        for q, res in zip(queries, results):
            aggregated += f"### Search results for '{q}':\n{res}\n\n"
        return aggregated

    @llm.function_tool(description="Search YouTube for a specific query")
    @async_ttl_cache(ttl=300)
    async def search_youtube(self, query: str) -> str:
        return await self.safe_execute(
            self.browser_ctrl.search_youtube,
            query,
            success_msg=f"Performed YouTube search for {query}.",
        )

    @llm.function_tool(
        description="Search YouTube, automatically play the first video result, and monitor the page in the background to auto-skip ads."
    )
    async def play_youtube(self, query: str) -> str:
        return await self.safe_execute(
            self.browser_ctrl.play_youtube,
            query,
            success_msg=f"Playing YouTube video for {query} and monitoring to auto-skip ads.",
        )

    @llm.function_tool(description="Switch to a browser tab matching a keyword")
    async def switch_tab(self, keyword: str) -> str:
        return await self.safe_execute(
            self.browser_ctrl.switch_tab,
            keyword,
            success_msg=f"Switched to tab matching {keyword}.",
            error_msg=f"No tab found matching {keyword}.",
        )

    @llm.function_tool(description="List all open browser tabs")
    async def list_tabs(self) -> str:
        tabs = await self.safe_execute(self.browser_ctrl.list_tabs)
        if str(tabs).startswith("Error:"):
            return str(tabs)
        if not tabs:
            return "No tabs are open or browser is not running."
        return "Open tabs:\n" + "\n".join(
            [f"- {t['title']} ({t['url']})" for t in tabs]
        )

    @llm.function_tool(description="Refresh the current browser tab")
    async def refresh_tab(self) -> str:
        return await self.safe_execute(
            self.browser_ctrl.refresh_tab, success_msg="Refreshed the current tab."
        )

    @llm.function_tool(description="Go back to the previous page in the browser")
    async def browser_go_back(self) -> str:
        return await self.safe_execute(self.browser_ctrl.go_back, success_msg="Navigated back.")

    @llm.function_tool(description="Go forward to the next page in the browser")
    async def browser_go_forward(self) -> str:
        return await self.safe_execute(
            self.browser_ctrl.go_forward, success_msg="Navigated forward."
        )

    @llm.function_tool(description="Get the title and URL of the current browser page")
    async def get_current_page_info(self) -> str:
        info = await self.safe_execute(self.browser_ctrl.get_current_page_info)
        if str(info).startswith("Error:"):
            return str(info)
        return f"Currently viewing: {info.get('title')} at {info.get('url')}."

    @llm.function_tool(description="Get status and directory of Jarvis's dedicated browser profile and account storage")
    async def get_browser_profile_status(self) -> str:
        info = self.browser_ctrl.get_profile_info()
        return (
            f"JARVIS Dedicated Browser Profile Status:\n"
            f"- Browser Channel: {info.get('browser_type')}\n"
            f"- Profile Directory: {info.get('profile_dir')}\n"
            f"- Active Session: {info.get('active')}"
        )
