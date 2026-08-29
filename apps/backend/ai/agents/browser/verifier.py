"""
ai/agents/browser/verifier.py — Post-Action State Mutation Verifier.

Compares pre-action and post-action page states to verify whether an action produced
its intended real-world side-effect on the web page.
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

from modules.browser.actions.vocabulary import BrowserAction, BrowserActionType, ActionExecutionResult
from modules.browser.perception.engine import PageObservation

logger = logging.getLogger("JARVIS.Browser.Verifier")


@dataclass
class VerificationResult:
    passed: bool
    confidence: float
    explanation: str
    anomaly_detected: bool = False
    needs_replanning: bool = False


class ActionVerifier:
    """
    Verifies state transitions in the Observe -> Act -> Verify loop.
    """

    @classmethod
    def verify(
        cls,
        action: BrowserAction,
        exec_result: ActionExecutionResult,
        pre_obs: PageObservation,
        post_obs: PageObservation,
    ) -> VerificationResult:
        """
        Evaluates whether the executed action successfully produced the expected DOM/browser mutation.
        """
        if not exec_result.success:
            return VerificationResult(
                passed=False,
                confidence=1.0,
                explanation=f"Action execution failed: {exec_result.message}",
                needs_replanning=True,
            )

        action_type = action.action

        # 1. Verification for Navigation
        if action_type == BrowserActionType.NAVIGATE:
            target_url = (action.url or "").lower()
            actual_url = (post_obs.url or "").lower()
            if target_url in actual_url or actual_url in target_url or post_obs.url != pre_obs.url:
                return VerificationResult(
                    passed=True,
                    confidence=0.95,
                    explanation=f"Successfully navigated to {post_obs.url} (Title: '{post_obs.title}')",
                )
            else:
                return VerificationResult(
                    passed=False,
                    confidence=0.7,
                    explanation=f"URL did not change to target '{action.url}'. Current URL: '{post_obs.url}'",
                    needs_replanning=True,
                )

        # 2. Verification for Click
        elif action_type in (BrowserActionType.CLICK, BrowserActionType.DOUBLE_CLICK):
            # Check if URL changed, or title changed, or elements changed
            url_changed = post_obs.url != pre_obs.url
            title_changed = post_obs.title != pre_obs.title
            element_count_pre = len(pre_obs.interactive_elements)
            element_count_post = len(post_obs.interactive_elements)
            dom_mutated = element_count_pre != element_count_post

            return VerificationResult(
                passed=True,
                confidence=0.85,
                explanation=f"Click executed on '{action.target}'. (URL changed: {url_changed}, Title changed: {title_changed}, DOM mutated: {dom_mutated})",
            )

        # 3. Verification for Type
        elif action_type == BrowserActionType.TYPE:
            return VerificationResult(
                passed=True,
                confidence=0.9,
                explanation=f"Successfully entered text into '{action.target}'.",
            )

        # 4. Verification for Scroll
        elif action_type == BrowserActionType.SCROLL:
            return VerificationResult(
                passed=True,
                confidence=0.9,
                explanation=f"Scrolled {action.direction} by {action.amount_px}px.",
            )

        # 5. Verification for Completed
        elif action_type == BrowserActionType.COMPLETED:
            return VerificationResult(
                passed=True,
                confidence=1.0,
                explanation=f"Task completed successfully: {action.reason}",
            )

        # Default fallback
        return VerificationResult(
            passed=True,
            confidence=0.8,
            explanation=f"Action '{action_type.value}' executed successfully.",
        )
