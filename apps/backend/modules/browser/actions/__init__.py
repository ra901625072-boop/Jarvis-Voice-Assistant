"""
modules/browser/actions — Controlled Action Vocabulary & Execution Engine for JARVIS.
"""

from modules.browser.actions.vocabulary import (
    BrowserActionType,
    BrowserAction,
    ActionExecutionResult,
)
from modules.browser.actions.executor import BrowserActionExecutor

__all__ = [
    "BrowserActionType",
    "BrowserAction",
    "ActionExecutionResult",
    "BrowserActionExecutor",
]
