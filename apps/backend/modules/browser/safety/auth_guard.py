"""
modules/browser/safety/auth_guard.py — Authentication & 2FA Boundary Detector.

Identifies login barriers, password forms, OAuth consent screens, and 2FA verification prompts
to maintain security boundaries without exposing user credentials or attempting unauthorized bypass.
"""

import logging
import re
from typing import Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("JARVIS.Browser.AuthGuard")


@dataclass
class AuthDetectionResult:
    is_auth_screen: bool
    auth_type: Optional[str] = None  # "login", "2fa", "oauth", "passkey"
    requires_user_login: bool = False
    message: str = ""


class AuthGuard:
    """
    Detects login walls and two-factor authentication prompts.
    """

    TWO_FACTOR_PATTERNS = [
        r"\b(two-factor|2-step|2fa|mfa|verification\s*code|security\s*code|authenticator\s*app|one-time\s*password|otp)\b",
    ]

    LOGIN_URL_PATTERNS = [
        r"/login", r"/signin", r"/auth", r"/oauth", r"/session/new", r"/accounts\.google\.com",
        r"/github\.com/login", r"/appleid\.apple\.com"
    ]

    @classmethod
    async def inspect_page(cls, page: Any) -> AuthDetectionResult:
        """
        Evaluates whether the current page is an authentication or 2FA barrier.
        """
        if not page:
            return AuthDetectionResult(is_auth_screen=False)

        try:
            url = ""
            title = ""
            try:
                url = (page.url or "").lower()
                title = (await page.title() or "").lower()
            except Exception:
                pass

            # 1. Check for 2FA / OTP prompts
            for pattern in cls.TWO_FACTOR_PATTERNS:
                if re.search(pattern, title) or re.search(pattern, url):
                    return AuthDetectionResult(
                        is_auth_screen=True,
                        auth_type="2fa",
                        requires_user_login=True,
                        message="2-Factor Authentication prompt detected. Please complete verification in browser.",
                    )

            # 2. Check for password fields in DOM
            try:
                if hasattr(page, "locator"):
                    pwd_call = page.locator("input[type='password']")
                    pwd_loc = await pwd_call if asyncio.iscoroutine(pwd_call) else pwd_call
                    if hasattr(pwd_loc, "count"):
                        count_call = pwd_loc.count()
                        pwd_count = await count_call if asyncio.iscoroutine(count_call) else count_call
                        if pwd_count and pwd_count > 0:
                            return AuthDetectionResult(
                                is_auth_screen=True,
                                auth_type="login",
                                requires_user_login=True,
                                message="Login / Password entry required. Please sign in to continue.",
                            )
            except Exception:
                pass

            # 3. Check for login URL patterns
            for pattern in cls.LOGIN_URL_PATTERNS:
                if re.search(pattern, url):
                    return AuthDetectionResult(
                        is_auth_screen=True,
                        auth_type="login",
                        requires_user_login=True,
                        message=f"Authentication page detected at '{url}'. Please sign in.",
                    )

        except Exception as e:
            logger.debug(f"Auth guard inspection note: {e}")

        return AuthDetectionResult(is_auth_screen=False)
