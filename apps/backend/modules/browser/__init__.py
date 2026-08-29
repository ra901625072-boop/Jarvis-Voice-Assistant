"""
modules/browser — Autonomous Browser Subsystem for JARVIS.
Provides Playwright controller, tab ownership manager, perception triad, action executor, and policy guardrails.
"""

from modules.browser.tab_manager import TabManager, TabRecord
from modules.browser.policy import BrowserPolicyEngine, PermissionLevel, PolicyDecision

__all__ = [
    "TabManager",
    "TabRecord",
    "BrowserPolicyEngine",
    "PermissionLevel",
    "PolicyDecision",
]
