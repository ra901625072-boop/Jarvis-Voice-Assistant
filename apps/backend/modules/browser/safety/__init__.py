"""
modules/browser/safety — Safety Guards, CAPTCHA Hand-off & Download Sandboxing.
"""

from modules.browser.safety.captcha_guard import CaptchaGuard, CaptchaDetectionResult
from modules.browser.safety.auth_guard import AuthGuard, AuthDetectionResult
from modules.browser.safety.download_guard import DownloadGuard

__all__ = [
    "CaptchaGuard",
    "CaptchaDetectionResult",
    "AuthGuard",
    "AuthDetectionResult",
    "DownloadGuard",
]
