"""
modules/browser/policy.py — Execution Policy Engine & Guardrails for Autonomous Browser.

Enforces strict non-bypassable invariants regarding:
1. Protected tab closure and navigation (JARVIS Control Server tabs are strictly immutable).
2. Tab ownership boundaries (agents cannot close user tabs or tabs owned by other tasks).
3. Risk-tiered action validation (Level 0 Read to Level 3 Sensitive).
"""

import logging
import re
from enum import IntEnum
from typing import Optional, Dict, Any
from dataclasses import dataclass

from modules.browser.tab_manager import TabRecord, TabManager

logger = logging.getLogger("JARVIS.Browser.Policy")


class PermissionLevel(IntEnum):
    LEVEL_0_READ = 0          # Search, read, scrape, scroll, screenshot, extract
    LEVEL_1_INTERACT = 1      # Navigate, click, type text, new tab, close owned tab, switch tab
    LEVEL_2_SIDE_EFFECT = 2   # Form submission, download file, upload file, send messages
    LEVEL_3_SENSITIVE = 3     # Financial checkout, credential entry, delete operations


@dataclass
class PolicyDecision:
    """Represents the verdict of a policy evaluation."""
    allowed: bool
    reason: str
    permission_level: PermissionLevel = PermissionLevel.LEVEL_0_READ
    requires_user_confirmation: bool = False
    details: Optional[Dict[str, Any]] = None

    def __bool__(self) -> bool:
        return self.allowed


class BrowserPolicyEngine:
    """
    Independent Policy Engine running outside the LLM reasoning loop.
    Enforces programmatic rules and cannot be overridden by model prompt instructions.
    """

    SENSITIVE_KEYWORD_PATTERNS = [
        r"\b(buy[-_\s]*now|checkout|place[-_\s]*order|pay[-_\s]*now|confirm[-_\s]*payment|purchase)\b",
        r"\b(delete[-_\s]*account|remove[-_\s]*all|purge|format|wipe)\b",
        r"\b(password|passcode|secret[-_\s]*key|api[-_\s]*key|private[-_\s]*key)\b",
    ]

    def __init__(self, tab_manager: Optional[TabManager] = None):
        self.tab_manager = tab_manager or TabManager()
        logger.info("BrowserPolicyEngine initialized.")

    def validate_tab_close(
        self,
        tab_record: Optional[TabRecord],
        requester_id: Optional[str] = None,
        force: bool = False,
    ) -> PolicyDecision:
        """
        Validates whether a tab may be closed.
        
        INVARIANTS:
        - Protected tabs (e.g., localhost:8000 server) CANNOT be closed by any agent under any circumstances.
        - User-owned tabs cannot be closed without explicit confirmation.
        - Agents may only close tabs they own.
        """
        if tab_record is None:
            return PolicyDecision(
                allowed=False,
                reason="Target tab does not exist or has already been closed.",
                permission_level=PermissionLevel.LEVEL_1_INTERACT,
            )

        # 1. HARD INVARIANT: System Protected Tabs (Control Server / Dashboard)
        if tab_record.protected or TabManager.is_server_url(tab_record.url):
            logger.warning(f"POLICY VIOLATION PREVENTED: Attempted to close protected tab {tab_record.tab_id} ({tab_record.url})")
            return PolicyDecision(
                allowed=False,
                reason="ACTION DENIED: Protected system tab (JARVIS Server/Dashboard). This tab cannot be closed by automated agents.",
                permission_level=PermissionLevel.LEVEL_3_SENSITIVE,
                requires_user_confirmation=True,
            )

        # 2. Force flag allows system-level teardown (excluding protected tabs, handled above)
        if force:
            return PolicyDecision(
                allowed=True,
                reason="Force flag supplied for non-protected tab.",
                permission_level=PermissionLevel.LEVEL_1_INTERACT,
            )

        # 3. User Ownership Check
        if tab_record.owner == "user":
            if requester_id != "user":
                return PolicyDecision(
                    allowed=False,
                    reason="ACTION DENIED: Tab belongs to the user. Automated agents cannot close user-opened tabs.",
                    permission_level=PermissionLevel.LEVEL_2_SIDE_EFFECT,
                    requires_user_confirmation=True,
                )

        # 4. Agent Task Ownership Check
        if requester_id:
            if not tab_record.is_owned_by(requester_id) and tab_record.owner != "system":
                return PolicyDecision(
                    allowed=False,
                    reason=f"ACTION DENIED: Tab {tab_record.tab_id} is owned by '{tab_record.owner}', not requester '{requester_id}'.",
                    permission_level=PermissionLevel.LEVEL_2_SIDE_EFFECT,
                    requires_user_confirmation=True,
                )

        return PolicyDecision(
            allowed=True,
            reason="Tab is non-protected and owned by the requester.",
            permission_level=PermissionLevel.LEVEL_1_INTERACT,
        )

    def validate_navigation(
        self,
        target_url: str,
        current_tab: Optional[TabRecord],
        requester_id: Optional[str] = None,
    ) -> PolicyDecision:
        """
        Validates URL navigation.
        
        INVARIANT:
        If current_tab is a protected server tab, navigation in that tab is DENIED.
        A new tab must be spawned instead.
        """
        if not target_url:
            return PolicyDecision(
                allowed=False,
                reason="Target URL is empty or invalid.",
                permission_level=PermissionLevel.LEVEL_0_READ,
            )

        if current_tab and (current_tab.protected or TabManager.is_server_url(current_tab.url)):
            # If target URL is also the server URL, it's fine, otherwise block navigation over server tab
            if not TabManager.is_server_url(target_url):
                return PolicyDecision(
                    allowed=False,
                    reason="ACTION DENIED: Cannot navigate away from protected JARVIS server tab. Open a new tab for research/automation.",
                    permission_level=PermissionLevel.LEVEL_1_INTERACT,
                    details={"recommendation": "create_new_tab"},
                )

        return PolicyDecision(
            allowed=True,
            reason="Navigation allowed.",
            permission_level=PermissionLevel.LEVEL_0_READ,
        )

    def validate_action(
        self,
        action_name: str,
        action_payload: Dict[str, Any],
        current_tab: Optional[TabRecord] = None,
        requester_id: Optional[str] = None,
    ) -> PolicyDecision:
        """
        Evaluates risk tier and potential dangerous side-effects of an atomic action.
        """
        action_name = str(action_name).lower().strip()

        # Read-only actions (Level 0)
        if action_name in ("observe", "extract", "screenshot", "scroll", "wait", "search"):
            return PolicyDecision(
                allowed=True,
                reason="Read-only action allowed.",
                permission_level=PermissionLevel.LEVEL_0_READ,
            )

        # Tab close action
        if action_name == "close_tab":
            return self.validate_tab_close(current_tab, requester_id)

        # Navigate action
        if action_name == "navigate":
            target_url = action_payload.get("url", "")
            return self.validate_navigation(target_url, current_tab, requester_id)

        # Interaction actions: check for sensitive keywords in text / selectors / target
        text_content = str(action_payload.get("text", "")).lower()
        selector = str(action_payload.get("selector") or action_payload.get("target") or "").lower()
        combined_text = f"{text_content} {selector}"
        clean_text = re.sub(r'[-_#.]', ' ', combined_text)

        for pattern in self.SENSITIVE_KEYWORD_PATTERNS:
            if re.search(pattern, combined_text) or re.search(pattern, clean_text):
                return PolicyDecision(
                    allowed=False,
                    reason=f"High-risk action detected matching pattern '{pattern}'. Human confirmation required.",
                    permission_level=PermissionLevel.LEVEL_3_SENSITIVE,
                    requires_user_confirmation=True,
                )

        return PolicyDecision(
            allowed=True,
            reason=f"Action '{action_name}' permitted under standard interaction policy.",
            permission_level=PermissionLevel.LEVEL_1_INTERACT,
        )
