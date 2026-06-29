import logging
import time
from urllib.parse import quote_plus, urlparse
from typing import Dict, List, Tuple

logger = logging.getLogger("JARVIS.GoogleSearch")

# --- Tunable constants -------------------------------------------------
ALLOWED_CRAWL_DOMAINS = ("google.com", "wikipedia.org")
CACHE_TTL_SECONDS = 300
SNIPPET_MAX_CHARS = 300
PAGE_CONTENT_MAX_CHARS = 2000
WIKI_DIRECT_MAX_CHARS = 3000
NAV_TIMEOUT_MS = 10_000
SELECTOR_WAIT_MS = 5_000


class GoogleSearch:
    """
    Performs web searches and scrapes results using an active Playwright
    browser session owned by BrowserController.

    `search_live()` tries Google first, falls back to Wikipedia if Google
    doesn't yield usable content, and only crawls full pages on whitelisted
    domains (Google/Wikipedia) -- everything else relies on the snippet
    already shown on the results page.
    """

    def __init__(self, browser_controller):
        self.browser_ctrl = browser_controller
        self._search_cache: Dict[str, float] = {}  # normalized query -> last search time

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------
    def _is_cached(self, query: str) -> bool:
        """
        Return True if `query` was searched within CACHE_TTL_SECONDS.
        As a side effect, records this query as "just searched" when it is
        not a cache hit, and prunes stale entries so the cache can't grow
        without bound over a long-running session.
        """
        key = query.lower().strip()
        last_time = self._search_cache.get(key)
        if last_time is not None and (time.time() - last_time) < CACHE_TTL_SECONDS:
            return True

        self._search_cache[key] = time.time()
        self._prune_cache()
        return False

    def _prune_cache(self) -> None:
        cutoff = time.time() - CACHE_TTL_SECONDS
        stale = [k for k, t in self._search_cache.items() if t < cutoff]
        for k in stale:
            del self._search_cache[k]

    # ------------------------------------------------------------------
    # Simple (non-scraping) search -- just navigates the active tab
    # ------------------------------------------------------------------
    async def search(self, query: str) -> str:
        if self._is_cached(query):
            logger.info(f"Google search for '{query}' is cached. Skipping reload.")
            return "Displayed cached search."

        url = f"https://www.google.com/search?q={quote_plus(query)}"
        return await self.browser_ctrl.open_url(url)

    # ------------------------------------------------------------------
    # Helpers shared by the Google and Wikipedia crawl paths
    # ------------------------------------------------------------------
    @staticmethod
    def _is_crawlable(url: str) -> bool:
        try:
            netloc = urlparse(url).netloc.lower()
        except Exception:
            return False
        return any(domain in netloc for domain in ALLOWED_CRAWL_DOMAINS)

    async def _extract_generic_links(self) -> List[Dict[str, str]]:
        """
        Extract {title, url, snippet} for each visible result heading on the
        current page.

        This runs as a single in-page `page.evaluate` call instead of doing
        per-heading round trips (evaluate_handle -> get_attribute -> evaluate
        -> dispose, repeated for every <h3>). For a typical results page with
        N headings that's roughly 4N Playwright IPC round trips collapsed
        into 1, which is the main latency win in this module.
        """
        js = """
            () => {
                const seen = new Set();
                const out = [];
                const snippetSelector = '.VwiC3b, .yXK7lf, .MUxGbd, .yDsyB, .kb0Gcb, .lEBKkf, [style*="-webkit-line-clamp"]';
                const containerClasses = ['g', 'tF2Cxc', 'MjjYud', 'Y6JuXb', 'kb0PBd'];

                for (const h of document.querySelectorAll('h3')) {
                    const title = (h.textContent || '').trim();
                    if (!title) continue;

                    const anchor = h.closest('a') || h.querySelector('a');
                    if (!anchor) continue;

                    const url = anchor.getAttribute('href');
                    if (!url || !url.startsWith('http') || seen.has(url)) continue;

                    let container = h.parentElement;
                    while (container && container.tagName !== 'BODY') {
                        if (containerClasses.some(c => container.classList.contains(c))) break;
                        container = container.parentElement;
                    }
                    if (!container || container.tagName === 'BODY') {
                        container = h.closest('div') || h.parentElement;
                    }

                    let snippet = '';
                    const descEl = container ? container.querySelector(snippetSelector) : null;
                    if (descEl) {
                        snippet = (descEl.innerText || '')
                            .split('\\n')
                            .map(l => l.trim())
                            .filter(Boolean)
                            .join(' ')
                            .split(title).join('')
                            .split(url).join('')
                            .trim()
                            .slice(0, %d);
                    }

                    seen.add(url);
                    out.push({ title, url, snippet });
                }
                return out;
            }
        """ % SNIPPET_MAX_CHARS

        try:
            raw = await self.browser_ctrl.page.evaluate(js)
            return raw or []
        except Exception as e:
            logger.error(f"Error parsing generic links: {e}")
            return []

    def _filter_results(self, results: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Prefer crawlable or snippet-bearing results; fall back to everything."""
        filtered = [r for r in results if self._is_crawlable(r["url"]) or r.get("snippet")]
        return filtered or results

    async def _crawl_result(self, result: Dict[str, str]) -> Tuple[str, bool]:
        """
        Get body text for one result. Only navigates to the page if its
        domain is on the crawl whitelist; otherwise reuses the snippet
        already scraped from the results page. Returns (content, success).
        """
        if not self._is_crawlable(result["url"]):
            snippet = result.get("snippet", "")
            if snippet:
                return snippet, True
            return "[Crawl restricted to Google and Wikipedia domains]", False

        pooled_page = None
        try:
            pooled_page = await self.browser_ctrl._get_pooled_page()
            await pooled_page.goto(result["url"], wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            page_text = await pooled_page.evaluate("document.body.innerText")
            cleaned = " ".join(line.strip() for line in page_text.split("\n") if line.strip())
            truncated = cleaned[:PAGE_CONTENT_MAX_CHARS] + ("..." if len(cleaned) > PAGE_CONTENT_MAX_CHARS else "")
            await self.browser_ctrl._return_pooled_page(pooled_page)
            return truncated, len(cleaned) > 100
        except Exception as e:
            if pooled_page is not None:
                try:
                    if not pooled_page.is_closed():
                        await pooled_page.close()
                except Exception:
                    pass
            return f"[Failed to extract page content: {e}]", False

    async def _build_aggregated_content(
        self, results: List[Dict[str, str]], num_results: int, header: str
    ) -> Tuple[str, int]:
        """Render up to `num_results` results into the report text format used by callers."""
        top_results = self._filter_results(results)[:num_results]
        lines = [header, ""]
        successful_crawls = 0

        for i, res in enumerate(top_results, 1):
            lines.append(f"[{i}] TITLE: {res['title']}")
            lines.append(f"    URL: {res['url']}")
            content, ok = await self._crawl_result(res)
            if ok:
                successful_crawls += 1
            lines.append(f"    CONTENT: {content}")
            lines.append("")

        return "\n".join(lines), successful_crawls

    async def _wait_for_results(self) -> None:
        """Best-effort wait for result headings instead of a fixed sleep."""
        try:
            await self.browser_ctrl.page.wait_for_selector("h3", timeout=SELECTOR_WAIT_MS)
        except Exception:
            pass  # page may genuinely have no h3 results; extraction will just return []

    # ------------------------------------------------------------------
    # Live search (navigates + scrapes + optionally crawls top results)
    # ------------------------------------------------------------------
    async def search_live(self, query: str, num_results: int = 3, engine: str = "google") -> str:
        logger.info(f"Performing live search via Playwright: {query} (engine: {engine})")
        await self.browser_ctrl._ensure_driver()
        if not self.browser_ctrl.page:
            return "Error: WebDriver is not initialized."

        if engine not in ("google", "wikipedia"):
            logger.warning(f"Unknown engine '{engine}' requested; defaulting to wikipedia fallback path.")

        if engine == "google":
            try:
                google_url = f"https://www.google.com/search?q={quote_plus(query)}"
                await self.browser_ctrl.page.goto(google_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                await self._wait_for_results()

                results = await self._extract_generic_links()
                if results:
                    content, successful = await self._build_aggregated_content(
                        results, num_results, f"Search Results for '{query}':"
                    )
                    if successful > 0:
                        await self.browser_ctrl.page.bring_to_front()
                        return content
                    logger.warning("Google search results had no satisfactory content. Trying Wikipedia fallback...")
                else:
                    logger.warning("Google search returned no results. Trying Wikipedia fallback...")
            except Exception as e:
                logger.error(f"Google search failed with error: {e}. Trying Wikipedia fallback...")

            engine = "wikipedia"

        try:
            wiki_url = f"https://en.wikipedia.org/w/index.php?search={quote_plus(query)}"
            await self.browser_ctrl.page.goto(wiki_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)

            current_url = self.browser_ctrl.page.url
            if "/wiki/" in current_url:
                page_text = await self.browser_ctrl.page.evaluate("document.body.innerText")
                cleaned = " ".join(line.strip() for line in page_text.split("\n") if line.strip())
                truncated = cleaned[:WIKI_DIRECT_MAX_CHARS] + ("..." if len(cleaned) > WIKI_DIRECT_MAX_CHARS else "")
                return (
                    f"Wikipedia direct page match content for '{query}':\n\n"
                    f"URL: {current_url}\nCONTENT: {truncated}"
                )

            await self._wait_for_results()
            results = await self._extract_generic_links()
            if not results:
                return "Failed to retrieve search results from Google and Wikipedia."

            content, _ = await self._build_aggregated_content(
                results, num_results, f"Wikipedia Search Results for '{query}':"
            )
            await self.browser_ctrl.page.bring_to_front()
            return content
        except Exception as e:
            return f"Search fallback error: {e}"

