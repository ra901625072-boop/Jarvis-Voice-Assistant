"""
modules/browser/safety/captcha_guard.py — Anti-Bot & CAPTCHA Detection with Human Handoff.

Monitors browser pages for Cloudflare Turnstile, Google reCAPTCHA, hCaptcha, and AWS WAF challenges.
Pauses agent automation and triggers a Human-in-the-Loop handoff.
"""

import logging
import re
from typing import Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("JARVIS.Browser.CaptchaGuard")


@dataclass
class CaptchaDetectionResult:
    detected: bool
    captcha_type: Optional[str] = None
    confidence: float = 0.0
    message: str = ""
    requires_human_handoff: bool = False


class CaptchaGuard:
    """
    Detects CAPTCHAs, bot challenges, and security verification pages.
    """

    CAPTCHA_SELECTORS = [
        ("cloudflare", "iframe[src*='challenges.cloudflare.com']"),
        ("cloudflare", "#challenge-stage"),
        ("cloudflare", "#cf-challenge-running"),
        ("cloudflare", "div.cf-turnstile"),
        ("recaptcha", "iframe[src*='google.com/recaptcha']"),
        ("recaptcha", ".g-recaptcha"),
        ("hcaptcha", "iframe[src*='hcaptcha.com']"),
        ("hcaptcha", ".h-captcha"),
        ("arkose", "iframe[src*='arkoselabs.com']"),
        ("arkose", "#funcaptcha"),
        ("perimeterx", "#px-captcha"),
        ("datadome", "iframe[src*='datadome.co']"),
    ]

    TITLE_TEXT_PATTERNS = [
        (r"just a moment\.\.\.", "cloudflare"),
        (r"attention required!\s*\|\s*cloudflare", "cloudflare"),
        (r"security check to access", "generic_captcha"),
        (r"verify you are human", "generic_captcha"),
        (r"robot or human\?", "generic_captcha"),
        (r"please verify you are a human", "generic_captcha"),
        (r"confirm you are not a robot", "generic_captcha"),
    ]

    @classmethod
    async def inspect_page(cls, page: Any) -> CaptchaDetectionResult:
        """
        Scans the active page for anti-bot / CAPTCHA challenge markers.
        """
        if not page:
            return CaptchaDetectionResult(detected=False)

        try:
            # 1. Check Page Title
            title = ""
            try:
                title = (await page.title() or "").lower()
            except Exception:
                pass

            for pattern, ctype in cls.TITLE_TEXT_PATTERNS:
                if re.search(pattern, title):
                    logger.warning(f"CAPTCHA Detected in title: '{title}' ({ctype})")
                    return CaptchaDetectionResult(
                        detected=True,
                        captcha_type=ctype,
                        confidence=0.95,
                        message=f"Human verification challenge detected: '{title}'. Please complete the verification in browser.",
                        requires_human_handoff=True,
                    )

            # 2. Check DOM Selectors for known CAPTCHA elements/iframes
            for ctype, selector in cls.CAPTCHA_SELECTORS:
                try:
                    if hasattr(page, "locator"):
                        loc_call = page.locator(selector)
                        loc = await loc_call if asyncio.iscoroutine(loc_call) else loc_call
                        if hasattr(loc, "count"):
                            count_call = loc.count()
                            count = await count_call if asyncio.iscoroutine(count_call) else count_call
                            if count and count > 0:
                                logger.warning(f"CAPTCHA Detected via DOM selector: '{selector}' ({ctype})")
                                return CaptchaDetectionResult(
                                    detected=True,
                                    captcha_type=ctype,
                                    confidence=0.9,
                                    message=f"CAPTCHA ({ctype}) detected on page. Human interaction required.",
                                    requires_human_handoff=True,
                                )
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"Captcha guard check error: {e}")

        return CaptchaDetectionResult(detected=False)
