"""
tests/unit/test_browser_policy.py — Unit Tests for Policy Engine, Permission Tiers, and Invariants.
"""

import pytest
from unittest.mock import MagicMock

from modules.browser.tab_manager import TabManager, TabRecord
from modules.browser.policy import BrowserPolicyEngine, PermissionLevel, PolicyDecision


class TestBrowserPolicyEngine:
    def test_close_protected_tab_is_strictly_denied(self):
        manager = TabManager()
        engine = BrowserPolicyEngine(tab_manager=manager)

        protected_tab = TabRecord(
            tab_id="tab_server",
            page_ref=MagicMock(),
            url="http://localhost:8000",
            owner="system",
            protected=True,
        )

        decision = engine.validate_tab_close(protected_tab, requester_id="agent:task_1")
        assert decision.allowed is False
        assert "Protected system tab" in decision.reason
        assert decision.requires_user_confirmation is True

    def test_close_unowned_user_tab_requires_confirmation(self):
        engine = BrowserPolicyEngine()

        user_tab = TabRecord(
            tab_id="tab_user_docs",
            page_ref=MagicMock(),
            url="https://docs.python.org",
            owner="user",
            protected=False,
        )

        decision = engine.validate_tab_close(user_tab, requester_id="agent:research_task")
        assert decision.allowed is False
        assert "belongs to the user" in decision.reason

    def test_close_owned_agent_tab_is_allowed(self):
        engine = BrowserPolicyEngine()

        agent_tab = TabRecord(
            tab_id="tab_research",
            page_ref=MagicMock(),
            url="https://nasa.gov",
            owner="agent:task_1",
            parent_task_id="task_1",
            protected=False,
        )

        decision = engine.validate_tab_close(agent_tab, requester_id="task_1")
        assert decision.allowed is True
        assert decision.permission_level == PermissionLevel.LEVEL_1_INTERACT

    def test_validate_navigation_prevents_navigating_away_from_server(self):
        engine = BrowserPolicyEngine()

        server_tab = TabRecord(
            tab_id="tab_server",
            page_ref=MagicMock(),
            url="http://localhost:8000",
            protected=True,
        )

        # Attempt to navigate server tab to google
        decision = engine.validate_navigation("https://www.google.com", server_tab, requester_id="task_1")
        assert decision.allowed is False
        assert "Cannot navigate away from protected" in decision.reason

        # Navigation on regular tab is allowed
        regular_tab = TabRecord(
            tab_id="tab_reg",
            page_ref=MagicMock(),
            url="https://wikipedia.org",
            protected=False,
        )
        decision_ok = engine.validate_navigation("https://www.google.com", regular_tab, requester_id="task_1")
        assert decision_ok.allowed is True

    def test_sensitive_action_keyword_detection(self):
        engine = BrowserPolicyEngine()

        # High-risk financial click
        decision = engine.validate_action(
            action_name="click",
            action_payload={"selector": "#buy-now-button"},
        )
        assert decision.allowed is False
        assert decision.permission_level == PermissionLevel.LEVEL_3_SENSITIVE
        assert decision.requires_user_confirmation is True

        # Normal click
        decision_normal = engine.validate_action(
            action_name="click",
            action_payload={"selector": "#next-page-link"},
        )
        assert decision_normal.allowed is True
        assert decision_normal.permission_level == PermissionLevel.LEVEL_1_INTERACT
