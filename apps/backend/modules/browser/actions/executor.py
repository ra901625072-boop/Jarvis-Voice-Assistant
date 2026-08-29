"""
modules/browser/actions/executor.py — Atomic Browser Action Execution Engine.

Dispatches structured BrowserActions against Playwright pages with robust locator resolution,
visibility waiting, scrolling, and error recovery.
"""

import time
import asyncio
import logging
import re
from typing import Any, Optional, Tuple

from modules.browser.actions.vocabulary import (
    BrowserAction,
    BrowserActionType,
    ActionExecutionResult,
)
from modules.browser.policy import BrowserPolicyEngine, PolicyDecision
from modules.browser.tab_manager import TabManager, TabRecord

logger = logging.getLogger("JARVIS.Browser.ActionExecutor")


class BrowserActionExecutor:
    """
    Executes controlled atomic browser actions against active Playwright pages.
    """

    def __init__(
        self,
        tab_manager: Optional[TabManager] = None,
        policy_engine: Optional[BrowserPolicyEngine] = None,
    ):
        self.tab_manager = tab_manager or TabManager()
        self.policy_engine = policy_engine or BrowserPolicyEngine(self.tab_manager)

    def _resolve_locator(self, page: Any, target: str) -> Any:
        """
        Resolves Playwright locator from CSS selector, XPath, or semantic role hint.
        """
        if not target or not page:
            return None

        target = target.strip()

        # Check for role=... hint (e.g., role=button[name="Search"])
        role_match = re.match(r'role=(\w+)(?:\[name="([^"]+)"\])?', target)
        if role_match:
            role_name = role_match.group(1)
            accessible_name = role_match.group(2)
            try:
                if accessible_name:
                    return page.get_by_role(role_name, name=accessible_name)
                return page.get_by_role(role_name)
            except Exception:
                pass

        # Text selector: text="Something"
        if target.startswith('text=') or target.startswith('"'):
            clean_text = target.replace('text=', '').strip('"\'' )
            try:
                return page.get_by_text(clean_text)
            except Exception:
                pass

        # Default CSS / XPath locator
        return page.locator(target).first

    async def execute(
        self,
        action: BrowserAction,
        page: Any,
        tab_record: Optional[TabRecord] = None,
        requester_id: Optional[str] = None,
    ) -> ActionExecutionResult:
        """
        Validates action against PolicyEngine and executes it safely on the page.
        """
        start_time = time.time()
        action_name = action.action.value

        # 1. Policy & Invariant Check
        payload_dict = action.model_dump() if hasattr(action, "model_dump") else action.dict()
        policy_check: PolicyDecision = self.policy_engine.validate_action(
            action_name=action_name,
            action_payload=payload_dict,
            current_tab=tab_record,
            requester_id=requester_id,
        )

        if not policy_check.allowed:
            logger.warning(f"Action '{action_name}' blocked by Policy Engine: {policy_check.reason}")
            return ActionExecutionResult(
                action=action.action,
                success=False,
                message=policy_check.reason,
                target=action.target,
                error="POLICY_DENIED",
                duration_ms=(time.time() - start_time) * 1000,
            )

        if not page and action.action not in (BrowserActionType.WAIT, BrowserActionType.COMPLETED):
            return ActionExecutionResult(
                action=action.action,
                success=False,
                message="Execution failed: No active browser page found.",
                error="NO_ACTIVE_PAGE",
                duration_ms=(time.time() - start_time) * 1000,
            )

        try:
            # 2. Dispatch Action Handlers
            if action.action == BrowserActionType.NAVIGATE:
                return await self._handle_navigate(action, page, start_time)

            elif action.action == BrowserActionType.CLICK:
                return await self._handle_click(action, page, start_time, double=False)

            elif action.action == BrowserActionType.DOUBLE_CLICK:
                return await self._handle_click(action, page, start_time, double=True)

            elif action.action == BrowserActionType.TYPE:
                return await self._handle_type(action, page, start_time)

            elif action.action == BrowserActionType.CLEAR:
                return await self._handle_clear(action, page, start_time)

            elif action.action == BrowserActionType.SCROLL:
                return await self._handle_scroll(action, page, start_time)

            elif action.action == BrowserActionType.HOVER:
                return await self._handle_hover(action, page, start_time)

            elif action.action == BrowserActionType.SELECT_OPTION:
                return await self._handle_select_option(action, page, start_time)

            elif action.action == BrowserActionType.PRESS_KEY:
                return await self._handle_press_key(action, page, start_time)

            elif action.action == BrowserActionType.WAIT:
                ms = action.timeout_ms or 1000
                await asyncio.sleep(ms / 1000.0)
                return ActionExecutionResult(
                    action=action.action,
                    success=True,
                    message=f"Waited for {ms}ms.",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            elif action.action == BrowserActionType.GO_BACK:
                await page.go_back(wait_until="domcontentloaded", timeout=action.timeout_ms)
                return ActionExecutionResult(
                    action=action.action,
                    success=True,
                    message="Navigated back.",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            elif action.action == BrowserActionType.GO_FORWARD:
                await page.go_forward(wait_until="domcontentloaded", timeout=action.timeout_ms)
                return ActionExecutionResult(
                    action=action.action,
                    success=True,
                    message="Navigated forward.",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            elif action.action == BrowserActionType.RELOAD:
                await page.reload(wait_until="domcontentloaded", timeout=action.timeout_ms)
                return ActionExecutionResult(
                    action=action.action,
                    success=True,
                    message="Page reloaded.",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            elif action.action == BrowserActionType.COMPLETED:
                return ActionExecutionResult(
                    action=action.action,
                    success=True,
                    message=action.reason or "Task marked completed.",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            else:
                return ActionExecutionResult(
                    action=action.action,
                    success=False,
                    message=f"Unsupported action '{action_name}'.",
                    error="UNSUPPORTED_ACTION",
                    duration_ms=(time.time() - start_time) * 1000,
                )

        except Exception as e:
            logger.exception(f"Execution error for action '{action_name}' on target '{action.target}': {e}")
            return ActionExecutionResult(
                action=action.action,
                success=False,
                message=f"Execution exception: {str(e)}",
                target=action.target,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    async def _handle_navigate(self, action: BrowserAction, page: Any, start_time: float) -> ActionExecutionResult:
        url = action.url
        if not url:
            return ActionExecutionResult(
                action=action.action,
                success=False,
                message="Missing URL for navigate action.",
                error="MISSING_URL",
                duration_ms=(time.time() - start_time) * 1000,
            )

        if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("about:"):
            url = f"https://{url}"

        await page.goto(url, wait_until="domcontentloaded", timeout=action.timeout_ms)
        return ActionExecutionResult(
            action=action.action,
            success=True,
            message=f"Successfully navigated to {url}",
            target=url,
            duration_ms=(time.time() - start_time) * 1000,
        )

    async def _handle_click(self, action: BrowserAction, page: Any, start_time: float, double: bool = False) -> ActionExecutionResult:
        locator = self._resolve_locator(page, action.target)
        if locator is None:
            return ActionExecutionResult(
                action=action.action,
                success=False,
                message=f"Locator for target '{action.target}' could not be resolved.",
                target=action.target,
                error="LOCATOR_NOT_FOUND",
                duration_ms=(time.time() - start_time) * 1000,
            )

        await locator.scroll_into_view_if_needed(timeout=3000)
        if double:
            await locator.dblclick(timeout=action.timeout_ms)
        else:
            await locator.click(timeout=action.timeout_ms)

        return ActionExecutionResult(
            action=action.action,
            success=True,
            message=f"Clicked element '{action.target}'",
            target=action.target,
            duration_ms=(time.time() - start_time) * 1000,
        )

    async def _handle_type(self, action: BrowserAction, page: Any, start_time: float) -> ActionExecutionResult:
        locator = self._resolve_locator(page, action.target)
        if locator is None:
            return ActionExecutionResult(
                action=action.action,
                success=False,
                message=f"Locator for target '{action.target}' could not be resolved.",
                target=action.target,
                error="LOCATOR_NOT_FOUND",
                duration_ms=(time.time() - start_time) * 1000,
            )

        await locator.scroll_into_view_if_needed(timeout=3000)
        await locator.fill(action.text or "", timeout=action.timeout_ms)

        # Optional Enter press if specified in metadata or key
        if action.key == "Enter" or action.metadata.get("press_enter"):
            await locator.press("Enter")

        return ActionExecutionResult(
            action=action.action,
            success=True,
            message=f"Typed text into '{action.target}'",
            target=action.target,
            data={"text": action.text},
            duration_ms=(time.time() - start_time) * 1000,
        )

    async def _handle_clear(self, action: BrowserAction, page: Any, start_time: float) -> ActionExecutionResult:
        locator = self._resolve_locator(page, action.target)
        if locator is None:
            return ActionExecutionResult(
                action=action.action,
                success=False,
                message=f"Locator for target '{action.target}' could not be resolved.",
                target=action.target,
                error="LOCATOR_NOT_FOUND",
                duration_ms=(time.time() - start_time) * 1000,
            )

        await locator.clear(timeout=action.timeout_ms)
        return ActionExecutionResult(
            action=action.action,
            success=True,
            message=f"Cleared input field '{action.target}'",
            target=action.target,
            duration_ms=(time.time() - start_time) * 1000,
        )

    async def _handle_scroll(self, action: BrowserAction, page: Any, start_time: float) -> ActionExecutionResult:
        direction = action.direction or "down"
        amount = action.amount_px or 400

        if direction == "down":
            await page.evaluate(f"window.scrollBy(0, {amount});")
        elif direction == "up":
            await page.evaluate(f"window.scrollBy(0, -{amount});")
        elif direction == "top":
            await page.evaluate("window.scrollTo(0, 0);")
        elif direction == "bottom":
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")

        return ActionExecutionResult(
            action=action.action,
            success=True,
            message=f"Scrolled {direction} by {amount}px",
            duration_ms=(time.time() - start_time) * 1000,
        )

    async def _handle_hover(self, action: BrowserAction, page: Any, start_time: float) -> ActionExecutionResult:
        locator = self._resolve_locator(page, action.target)
        if locator is None:
            return ActionExecutionResult(
                action=action.action,
                success=False,
                message=f"Locator for target '{action.target}' could not be resolved.",
                target=action.target,
                error="LOCATOR_NOT_FOUND",
                duration_ms=(time.time() - start_time) * 1000,
            )

        await locator.hover(timeout=action.timeout_ms)
        return ActionExecutionResult(
            action=action.action,
            success=True,
            message=f"Hovered over '{action.target}'",
            target=action.target,
            duration_ms=(time.time() - start_time) * 1000,
        )

    async def _handle_select_option(self, action: BrowserAction, page: Any, start_time: float) -> ActionExecutionResult:
        locator = self._resolve_locator(page, action.target)
        if locator is None:
            return ActionExecutionResult(
                action=action.action,
                success=False,
                message=f"Locator for target '{action.target}' could not be resolved.",
                target=action.target,
                error="LOCATOR_NOT_FOUND",
                duration_ms=(time.time() - start_time) * 1000,
            )

        await locator.select_option(value=action.value, timeout=action.timeout_ms)
        return ActionExecutionResult(
            action=action.action,
            success=True,
            message=f"Selected option '{action.value}' on '{action.target}'",
            target=action.target,
            duration_ms=(time.time() - start_time) * 1000,
        )

    async def _handle_press_key(self, action: BrowserAction, page: Any, start_time: float) -> ActionExecutionResult:
        key = action.key or "Enter"
        if action.target:
            locator = self._resolve_locator(page, action.target)
            if locator:
                await locator.press(key)
            else:
                await page.keyboard.press(key)
        else:
            await page.keyboard.press(key)

        return ActionExecutionResult(
            action=action.action,
            success=True,
            message=f"Pressed key '{key}'",
            data={"key": key},
            duration_ms=(time.time() - start_time) * 1000,
        )
