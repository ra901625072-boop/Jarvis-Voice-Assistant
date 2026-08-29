"""
apps/backend/ai/agents/research/tools/web_search.py
Multi-Engine Search Discovery for Deep Research (DuckDuckGo, Playwright Browser Search, Gemini Search Fallback).
Includes domain noise filtering to exclude dictionary definitions and weather scrapers from academic research.
"""
import asyncio
import os
import re
import json
import warnings
import logging
from urllib.parse import urlparse
from typing import List, Dict, Any

logger = logging.getLogger("JARVIS.ResearchTools.WebSearch")

# Domains that pollute scientific/academic research queries
NOISY_DOMAINS = {
    "wiktionary.org",
    "dictionary.cambridge.org",
    "merriam-webster.com",
    "vocabulary.com",
    "accuweather.com",
    "weather.com",
    "dictionary.com",
    "thesaurus.com",
    "collinsdictionary.com",
}


class ResearchSearchEngine:
    """
    Executes resilient web searches across DuckDuckGo, BrowserTools, or Gemini Google Search fallback.
    """

    @classmethod
    async def search_queries_parallel(
        cls,
        queries: List[str],
        max_results_per_query: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Executes multiple search queries concurrently and aggregates distinct candidate items.
        """
        if not queries:
            return []

        async def _run_single(q: str):
            try:
                return await cls.search_single_query(q, limit=max_results_per_query)
            except Exception as e:
                logger.warning(f"Search failed for query '{q}': {e}")
                return []

        tasks = [_run_single(q) for q in queries[:6]]
        grouped_results = await asyncio.gather(*tasks)

        flattened = []
        for res_list in grouped_results:
            flattened.extend(res_list)

        return flattened

    @classmethod
    async def search_single_query(cls, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Runs a single query trying DuckDuckGo first, then BrowserTools, then Gemini Search.
        Filters out dictionary and weather domain pollution.
        """
        results: List[Dict[str, Any]] = []

        def _is_clean_url(url_str: str) -> bool:
            if not url_str or not url_str.startswith("http"):
                return False
            domain = urlparse(url_str.lower()).netloc
            return not any(noisy in domain for noisy in NOISY_DOMAINS)

        # 1. DuckDuckGo Search
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    from duckduckgo_search import DDGS
                except ImportError:
                    from ddgs import DDGS  # type: ignore

            def _do_ddg():
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    with DDGS(timeout=6) as ddgs:
                        return list(ddgs.text(query, max_results=limit * 2))

            ddg_items = await asyncio.to_thread(_do_ddg)
            if ddg_items:
                for item in ddg_items:
                    url = item.get("href", "") or item.get("url", "")
                    title = item.get("title", "")
                    snippet = item.get("body", "") or item.get("snippet", "")
                    if _is_clean_url(url):
                        results.append({
                            "title": title,
                            "url": url,
                            "snippet": snippet,
                            "query": query,
                            "engine": "duckduckgo",
                        })
                    if len(results) >= limit:
                        break
                if results:
                    return results
        except Exception as e:
            logger.debug(f"DuckDuckGo search error for '{query}': {e}")

        # 2. BrowserTools Live Search Fallback
        try:
            from container import ServiceContainer
            container = ServiceContainer.instance()
            tools_list = container.get_or_none("tools") if container else []
            browser_tools = None
            if tools_list:
                for t in tools_list:
                    if t.__class__.__name__ == "BrowserTools":
                        browser_tools = t
                        break

            if browser_tools and hasattr(browser_tools, "_execute_single_search"):
                res_str = await browser_tools._execute_single_search(query)
                blocks = res_str.split("\n\n")
                for b in blocks:
                    if "TITLE:" in b and "URL:" in b:
                        title_m = re.search(r"TITLE:\s*(.+)", b)
                        url_m = re.search(r"URL:\s*(.+)", b)
                        snippet_m = re.search(r"SNIPPET:\s*(.+)", b)
                        title = title_m.group(1).strip() if title_m else ""
                        url = url_m.group(1).strip() if url_m else ""
                        snippet = snippet_m.group(1).strip() if snippet_m else ""
                        if _is_clean_url(url):
                            results.append({
                                "title": title,
                                "url": url,
                                "snippet": snippet,
                                "query": query,
                                "engine": "browsertools",
                            })
                        if len(results) >= limit:
                            break
                if results:
                    return results
        except Exception as e:
            logger.debug(f"BrowserTools search fallback failed: {e}")

        # 3. Gemini Google Search API Fallback
        try:
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if api_key:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=api_key)
                prompt = (
                    f"You are a scientific research assistant. Search the web and provide key empirical facts and authoritative source URLs for:\n"
                    f"Query: {query}\n"
                    "Focus on peer-reviewed research, NIST/IEEE standards, official lab results, and reputable academic reviews."
                )
                config = types.GenerateContentConfig(tools=[{"google_search": {}}])
                res = await asyncio.to_thread(
                    client.models.generate_content,
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=config
                )
                if res and res.text:
                    results.append({
                        "title": f"Google Scientific Search Synthesis: {query}",
                        "url": "https://www.google.com/search?q=" + query.replace(" ", "+"),
                        "snippet": res.text[:400],
                        "deep_content": res.text[:2500],
                        "query": query,
                        "engine": "gemini_google_search",
                    })
                    return results
        except Exception as e:
            logger.debug(f"Gemini search fallback failed: {e}")

        return results
