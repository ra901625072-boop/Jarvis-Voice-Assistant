"""
failure_patterns.py
--------------------
Single source of truth for clustering error text into a canonical pattern key.
Used by both the real-time learner and the nightly ExperienceReplay/AgentSelfReflector
so fast-loop and slow-loop lesson keys never drift apart.
"""
import re
from typing import Optional

# (regex, canonical_key) — ordered, first match wins.
# Superset of the previous ExperienceReplay._extract_failure_pattern and
# AgentSelfReflector._extract_failure_clusters keyword sets.
_PATTERNS = [
    (r"captcha", "captcha_triggered"),
    (r"timeout|timed out", "request_timeout"),
    (r"selenium.*fail|fail.*selenium", "selenium_failure"),
    (r"blocked|rate.?limit", "rate_limited"),
    (r"not found|404", "resource_not_found"),
    (r"permission.?denied|access.?denied", "permission_denied"),
    (r"connection.?refused|connect.?error", "connection_error"),
    (r"crash|exception|traceback", "crash_or_exception"),
    (r"google.*fail|fail.*google", "google_search_failure"),
    (r"download.?fail|failed.?download", "download_failure"),
]


def extract_pattern(error_text: Optional[str]) -> str:
    """Return a canonical failure-pattern key, or 'general_failure' if nothing matches."""
    if not error_text:
        return "unclassified_failure"
    text = error_text.lower()
    for regex, key in _PATTERNS:
        if re.search(regex, text):
            return key
    return "general_failure"
