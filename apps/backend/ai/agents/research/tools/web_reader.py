"""
apps/backend/ai/agents/research/tools/web_reader.py
Web Page Reader & Content Extractor (Playwright -> Trafilatura -> PDF Reader -> Prompt Injection Sanitizer).
Guards against binary stream corruption, PDF raw parsing, and bot-challenge screen pollution.
"""
import asyncio
import io
import re
import urllib.request
import logging
from typing import Optional

from ai.agents.research.safety.prompt_injection import WebPromptInjectionDetector
from ai.agents.research.safety.source_validation import SourceValidator

logger = logging.getLogger("JARVIS.ResearchTools.WebReader")

CHALLENGE_PATTERNS = [
    "client challenge javascript is disabled",
    "please enable javascript to proceed",
    "a required part of this site couldn't load",
    "just a moment... enable javascript",
    "cloudflare ray id",
]


class ResearchWebReader:
    """
    Safely reads, extracts clean readable body text, and sanitizes web content against prompt injection.
    """

    @classmethod
    async def extract_clean_text(cls, url: str, timeout: float = 8.0) -> str:
        """
        Extracts clean body text from a webpage or PDF using multi-stage fallback.
        """
        is_safe, reason = SourceValidator.is_safe_url(url)
        if not is_safe:
            logger.warning(f"Refusing to read unsafe URL '{url}': {reason}")
            return ""

        raw_text = ""

        # 0. Check if URL is a direct PDF link
        if url.lower().endswith(".pdf"):
            try:
                from ai.agents.research.tools.pdf_reader import ResearchPDFReader
                pdf_res = await ResearchPDFReader.extract_pdf_sections(url)
                if pdf_res and pdf_res.get("full_text"):
                    raw_text = pdf_res["full_text"]
            except Exception as e:
                logger.debug(f"PDF extraction error for {url}: {e}")

        # 1. Try Trafilatura (best for clean article extraction without boilerplate)
        if not raw_text:
            try:
                import trafilatura
                downloaded = await asyncio.to_thread(trafilatura.fetch_url, url)
                if downloaded:
                    # Check if downloaded stream is PDF binary
                    if downloaded.startswith(b"%PDF-"):
                        try:
                            import pypdf
                            reader = pypdf.PdfReader(io.BytesIO(downloaded))
                            text_pages = [p.extract_text() or "" for p in reader.pages[:10]]
                            extracted_pdf = "\n".join(text_pages).strip()
                            if extracted_pdf and len(extracted_pdf) > 100:
                                raw_text = extracted_pdf
                        except Exception as pe:
                            logger.debug(f"pypdf extraction failed: {pe}")
                    else:
                        extracted = await asyncio.to_thread(trafilatura.extract, downloaded)
                        if extracted and len(extracted.strip()) > 100:
                            raw_text = extracted
            except Exception as e:
                logger.debug(f"Trafilatura extraction error for {url}: {e}")

        # 2. Try Playwright Browser Controller if available
        if not raw_text:
            try:
                from container import ServiceContainer
                c = ServiceContainer.instance()
                tools_list = c.get_or_none("tools") if c else []
                browser_tools = None
                if tools_list:
                    for t in tools_list:
                        if t.__class__.__name__ == "BrowserTools":
                            browser_tools = t
                            break

                if browser_tools and hasattr(browser_tools, "browser_ctrl"):
                    ctrl = browser_tools.browser_ctrl
                    await ctrl._ensure_driver()
                    page = await ctrl.context.new_page()
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
                        text = await page.evaluate("() => document.body.innerText")
                        clean = re.sub(r"\s+", " ", text).strip()
                        if clean and len(clean) > 100:
                            raw_text = clean
                    finally:
                        await page.close()
            except Exception as e:
                logger.debug(f"Playwright extraction error for {url}: {e}")

        # 3. Fallback: urllib native request + regex HTML strip
        if not raw_text:
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                )
                def _fetch():
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        raw_bytes = resp.read()
                        if raw_bytes.startswith(b"%PDF-"):
                            try:
                                import pypdf
                                reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
                                text_pages = [p.extract_text() or "" for p in reader.pages[:10]]
                                return "\n".join(text_pages).strip()
                            except Exception:
                                return ""
                        html = raw_bytes.decode("utf-8", errors="ignore")
                        html = re.sub(r"<script.*?>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
                        html = re.sub(r"<style.*?>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
                        text = re.sub(r"<[^>]+>", " ", html)
                        text = re.sub(r"\s+", " ", text).strip()
                        return text

                clean = await asyncio.to_thread(_fetch)
                if clean:
                    raw_text = clean
            except Exception as e:
                logger.debug(f"urllib extraction error for {url}: {e}")

        if not raw_text:
            return ""

        # Reject challenge screens or binary corruptions
        raw_lower = raw_text[:300].lower()
        if any(chal in raw_lower for chal in CHALLENGE_PATTERNS):
            logger.debug(f"Discarding bot-challenge page for {url}")
            return ""
        if raw_text.startswith("%PDF-") or "JFIF" in raw_text[:200]:
            logger.debug(f"Discarding raw unparsed binary PDF string for {url}")
            return ""

        # Scan and sanitize untrusted content
        sanitized = WebPromptInjectionDetector.sanitize_untrusted_content(raw_text, max_chars=4000)
        return sanitized
