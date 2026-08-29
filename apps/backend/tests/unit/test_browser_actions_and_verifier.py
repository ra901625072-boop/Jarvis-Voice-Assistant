"""
tests/unit/test_browser_actions_and_verifier.py — Unit Tests for Action Vocabulary, Verification & Guards.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from modules.browser.actions.vocabulary import (
    BrowserAction,
    BrowserActionType,
    ActionExecutionResult,
)
from modules.browser.actions.executor import BrowserActionExecutor
from modules.browser.perception.engine import PageObservation
from modules.browser.safety.captcha_guard import CaptchaGuard
from modules.browser.safety.auth_guard import AuthGuard
from ai.agents.browser.verifier import ActionVerifier


class TestBrowserActionsAndVerifier:
    def test_browser_action_normalization(self):
        # Alias 'goto' -> NAVIGATE
        action1 = BrowserAction.from_dict({"action": "goto", "url": "https://example.com"})
        assert action1.action == BrowserActionType.NAVIGATE
        assert action1.url == "https://example.com"

        # Alias 'fill' -> TYPE
        action2 = BrowserAction.from_dict({"action": "fill", "selector": "#name", "text": "Jarvis"})
        assert action2.action == BrowserActionType.TYPE
        assert action2.target == "#name"
        assert action2.text == "Jarvis"

        # Alias 'done' -> COMPLETED
        action3 = BrowserAction.from_dict({"action": "done", "reason": "Extracted all data"})
        assert action3.action == BrowserActionType.COMPLETED
        assert action3.reason == "Extracted all data"

    @pytest.mark.anyio
    async def test_action_executor_navigate(self):
        executor = BrowserActionExecutor()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()

        action = BrowserAction(action=BrowserActionType.NAVIGATE, url="https://wikipedia.org")
        res = await executor.execute(action, page=mock_page)

        assert res.success is True
        mock_page.goto.assert_awaited_once_with("https://wikipedia.org", wait_until="domcontentloaded", timeout=10000)

    def test_action_verifier_navigation(self):
        nav_action = BrowserAction(action=BrowserActionType.NAVIGATE, url="https://wikipedia.org")
        exec_ok = ActionExecutionResult(action=BrowserActionType.NAVIGATE, success=True, message="Navigated")

        pre_obs = PageObservation(tab_id="tab_1", url="about:blank", title="")
        post_obs = PageObservation(tab_id="tab_1", url="https://wikipedia.org", title="Wikipedia")

        v_res = ActionVerifier.verify(nav_action, exec_ok, pre_obs, post_obs)
        assert v_res.passed is True
        assert "Successfully navigated" in v_res.explanation

    @pytest.mark.anyio
    async def test_captcha_guard_detection(self):
        mock_page = AsyncMock()
        mock_page.title = AsyncMock(return_value="Just a moment... | Cloudflare")

        res = await CaptchaGuard.inspect_page(mock_page)
        assert res.detected is True
        assert res.captcha_type == "cloudflare"
        assert res.requires_human_handoff is True

    @pytest.mark.anyio
    async def test_auth_guard_2fa_detection(self):
        mock_page = AsyncMock()
        mock_page.title = AsyncMock(return_value="Two-Factor Authentication Required")
        mock_page.url = "https://github.com/sessions/two-factor"

        res = await AuthGuard.inspect_page(mock_page)
        assert res.is_auth_screen is True
        assert res.auth_type == "2fa"
        assert res.requires_user_login is True
