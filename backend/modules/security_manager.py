"""
security_manager.py

Checks whether a given action requires explicit user confirmation before execution.
Accepts a pre-loaded settings dict to avoid redundant file I/O — settings.json
is already read by BrainController at startup.
"""

import logging

logger = logging.getLogger("JARVIS.Security")

_DEFAULT_RESTRICTED = ["delete", "shutdown", "restart", "format"]


class SecurityManager:
    def __init__(self, settings: dict = None):
        """
        Args:
            settings: Pre-loaded settings dict (passed in from BrainController).
                      If None, falls back to safe defaults.
        """
        if settings is None:
            settings = {}
        self.restricted_actions: list = settings.get(
            "confirmation_required", _DEFAULT_RESTRICTED
        )
        logger.info("SecurityManager initialized.")

    def requires_confirmation(self, action: str, target: str) -> bool:
        """
        Return True if *action* + *target* match any restricted keyword.
        """
        text_to_check = f"{action} {target}".lower()
        return any(keyword in text_to_check for keyword in self.restricted_actions)
