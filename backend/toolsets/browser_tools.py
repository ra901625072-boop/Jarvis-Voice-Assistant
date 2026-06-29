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
from toolsets.base import JarvisToolset, async_ttl_cache
from modules.controls.browser_controller import BrowserController
from modules.core.security_manager import SecurityManager

_logger = logging.getLogger("JARVIS.BrowserTools")


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
        self._browser_ctrl = BrowserController()

    @property
    def browser_ctrl(self) -> BrowserController:
        return self._browser_ctrl

    @llm.function_tool(description="Open a specific URL in the browser")
    async def open_url(self, url: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"]:
            return "Error: Invalid URL scheme. Only http and https are allowed."
        return await self.safe_execute(
            self.browser_ctrl.open_url, url, success_msg=f"Opened {url} in the browser."
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
            "Search Google and physically show the search results page to the user in their "
            "browser window. Use this ONLY when the user asks to 'show' the search results or "
            "query (e.g., 'show me...')."
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
        """Use Gemini to split a compound query into individual search queries."""
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
                "Determine if it asks for multiple distinct items of information that would be better "
                "searched separately in individual, simplified search queries.\n"
                "Return ONLY a raw JSON list of strings. Do not include markdown code block wrappers."
            )

            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )

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
                    return queries
        except Exception as e:
            _logger.warning(f"Decomposing query failed: {e}. Using original query.")

        return [query]

    async def _execute_single_search(self, query: str, engine: str = "google") -> str:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                from duckduckgo_search import DDGS

            def _do_ddg_search():
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    with DDGS() as ddgs:
                        return list(ddgs.text(query, max_results=5))

            results = await asyncio.to_thread(_do_ddg_search)
            if results:
                aggregated = f"Fast API Search Results for '{query}':\n\n"
                for i, res in enumerate(results, 1):
                    aggregated += (
                        f"[{i}] TITLE: {res.get('title')}\n"
                        f"    URL: {res.get('href')}\n"
                        f"    CONTENT: {res.get('body')}\n\n"
                    )
                return aggregated
            else:
                return f"No results found for '{query}'."
        except Exception as e:
            _logger.warning(f"Fast-path DDG search failed for '{query}': {e}.")
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
