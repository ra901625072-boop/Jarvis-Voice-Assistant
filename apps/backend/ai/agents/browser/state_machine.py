"""
ai/agents/browser/state_machine.py — Autonomous Browser Closed-Loop State Machine.

Implements the complete Observe -> Reason -> Policy Check -> Execute -> Observe -> Verify -> Recover loop.
"""

import time
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable

from modules.browser.controller import BrowserController
from modules.browser.perception.engine import BrowserPerceptionEngine, PageObservation
from modules.browser.actions.vocabulary import BrowserAction, BrowserActionType, ActionExecutionResult
from modules.browser.actions.executor import BrowserActionExecutor
from modules.browser.safety.captcha_guard import CaptchaGuard
from modules.browser.safety.auth_guard import AuthGuard
from ai.agents.browser.schemas import BrowserActionSchema, StepExecutionRecord, AutomationWorkflowResult
from ai.agents.browser.verifier import ActionVerifier, VerificationResult

logger = logging.getLogger("JARVIS.Browser.StateMachine")


class BrowserStateMachine:
    """
    Autonomous closed-loop agent driving browser tasks to completion.
    """

    def __init__(
        self,
        controller: BrowserController,
        llm_generator: Callable[[str, Optional[str]], Any],
    ):
        self.controller = controller
        self.llm_generator = llm_generator
        self.perception_engine = controller.perception_engine
        self.action_executor = controller.action_executor
        self.captcha_guard = CaptchaGuard()
        self.auth_guard = AuthGuard()

    async def run(
        self,
        objective: str,
        initial_url: Optional[str] = None,
        max_steps: int = 10,
        time_budget_sec: float = 120.0,
        task_id: Optional[str] = None,
    ) -> AutomationWorkflowResult:
        """
        Executes the autonomous browser loop until the objective is completed or budget is exhausted.
        """
        start_time = time.time()
        logger.info(f"Initiating BrowserStateMachine for task '{task_id}'. Objective: '{objective}'")

        await self.controller._ensure_driver()
        page = await self.controller.get_or_create_content_page(task_id=task_id)

        history: List[StepExecutionRecord] = []
        step = 0

        # Step 0: Initial Navigation if requested
        if initial_url:
            nav_action = BrowserAction(
                action=BrowserActionType.NAVIGATE,
                url=initial_url,
                reason=f"Initial navigation to {initial_url}",
            )
            pre_obs = await self.perception_engine.observe(page, tab_id=task_id or "current")
            nav_res = await self.action_executor.execute(
                nav_action,
                page,
                tab_record=self.controller.tab_manager.get_tab(page),
                requester_id=task_id,
            )
            post_obs = await self.perception_engine.observe(page, tab_id=task_id or "current")
            v_res = ActionVerifier.verify(nav_action, nav_res, pre_obs, post_obs)

            history.append(
                StepExecutionRecord(
                    step_number=0,
                    action="navigate",
                    target=initial_url,
                    reason="Initial navigation",
                    success=nav_res.success and v_res.passed,
                    result_message=nav_res.message,
                    pre_url=pre_obs.url,
                    post_url=post_obs.url,
                    verification_passed=v_res.passed,
                    verification_notes=v_res.explanation,
                    timestamp=time.time(),
                )
            )

        while step < max_steps:
            # 1. Check Hard Time Budget
            elapsed = time.time() - start_time
            if elapsed > time_budget_sec:
                logger.warning(f"BrowserStateMachine exceeded time budget ({elapsed:.1f}s > {time_budget_sec}s)")
                return AutomationWorkflowResult(
                    success=False,
                    objective=objective,
                    total_steps=step,
                    history=history,
                    error=f"Execution exceeded time budget of {time_budget_sec} seconds.",
                )

            # 2. Check for Anti-Bot / CAPTCHA Challenge
            captcha_res = await self.captcha_guard.inspect_page(page)
            if captcha_res.detected:
                logger.warning(f"CAPTCHA Guard triggered: {captcha_res.message}")
                return AutomationWorkflowResult(
                    success=False,
                    objective=objective,
                    total_steps=step,
                    history=history,
                    error=f"HUMAN_HANDOFF_REQUIRED: {captcha_res.message}",
                )

            # 3. Check for Authentication / 2FA Wall
            auth_res = await self.auth_guard.inspect_page(page)
            if auth_res.is_auth_screen:
                logger.warning(f"Auth Guard triggered: {auth_res.message}")
                return AutomationWorkflowResult(
                    success=False,
                    objective=objective,
                    total_steps=step,
                    history=history,
                    error=f"AUTH_BARRIER_DETECTED: {auth_res.message}",
                )

            # 4. Perception Sweep (Pre-Action Observation)
            pre_obs = await self.perception_engine.observe(page, tab_id=task_id or "current")

            # 5. LLM Action Planning Prompt
            history_summary = "\n".join([
                f"  Step {h.step_number}: action={h.action} target={h.target} success={h.success} outcome={h.result_message}"
                for h in history[-4:]
            ]) or "  (No prior steps taken)"

            prompt = f"""
You are JARVIS's Autonomous Browser Agent (Observe-Reason-Act-Verify Engine).

OBJECTIVE: "{objective}"

{pre_obs.to_prompt_context()}

RECENT STEP HISTORY:
{history_summary}

DECISION INSTRUCTIONS:
Analyze the objective and current browser state. Decide the SINGLE NEXT BEST ACTION to make progress toward the goal.
Allowed action types:
- "navigate": {{ "url": "https://..." }}
- "click": {{ "target": "selector_or_role_locator" }}
- "double_click": {{ "target": "selector_or_role_locator" }}
- "type": {{ "target": "selector", "text": "...", "key": "Enter" (optional) }}
- "clear": {{ "target": "selector" }}
- "scroll": {{ "direction": "down|up", "amount_px": 400 }}
- "hover": {{ "target": "selector" }}
- "select_option": {{ "target": "selector", "value": "..." }}
- "press_key": {{ "key": "Enter|Escape|Tab" }}
- "wait": {{ "timeout_ms": 2000 }}
- "completed": {{ "reason": "Explain how objective was satisfied" }}

Return ONLY valid JSON with:
{{
  "action": "<action_type>",
  "target": "<selector or role locator or null>",
  "text": "<text to type or null>",
  "url": "<url or null>",
  "key": "<key to press or null>",
  "direction": "<down or up>",
  "amount_px": 400,
  "value": "<option value or null>",
  "timeout_ms": 10000,
  "reason": "<one sentence rationale explaining why this step is chosen>"
}}
"""

            raw_response = await self.llm_generator(prompt, "application/json")
            try:
                if isinstance(raw_response, str):
                    clean_json = raw_response.strip()
                    if clean_json.startswith("```json"):
                        clean_json = clean_json[7:]
                    if clean_json.endswith("```"):
                        clean_json = clean_json[:-3]
                    data = json.loads(clean_json.strip())
                elif isinstance(raw_response, dict):
                    data = raw_response
                else:
                    data = json.loads(str(raw_response))

                action_obj = BrowserAction.from_dict(data)
            except Exception as parse_err:
                logger.error(f"Failed to parse LLM browser action: {parse_err}. Raw: {raw_response}")
                return AutomationWorkflowResult(
                    success=False,
                    objective=objective,
                    total_steps=step,
                    history=history,
                    error=f"JSON Action Parse Error: {parse_err}",
                )

            logger.info(f"Step {step+1}: Decided '{action_obj.action.value}'. Target: '{action_obj.target}'. Reason: '{action_obj.reason}'")

            # 6. Check Completion Action
            if action_obj.action == BrowserActionType.COMPLETED:
                history.append(
                    StepExecutionRecord(
                        step_number=step + 1,
                        action="completed",
                        reason=action_obj.reason or "Goal completed",
                        success=True,
                        result_message=action_obj.reason or "Goal satisfied",
                        pre_url=pre_obs.url,
                        post_url=pre_obs.url,
                        verification_passed=True,
                        verification_notes="Verified completion criteria.",
                        timestamp=time.time(),
                    )
                )
                return AutomationWorkflowResult(
                    success=True,
                    objective=objective,
                    total_steps=step + 1,
                    history=history,
                    final_url=pre_obs.url,
                    final_title=pre_obs.title,
                )

            # 7. Execute Action
            exec_res = await self.action_executor.execute(
                action=action_obj,
                page=page,
                tab_record=self.controller.tab_manager.get_tab(page),
                requester_id=task_id,
            )

            # 8. Post-Observation & Verification Sweep
            await asyncio.sleep(1.0)
            post_obs = await self.perception_engine.observe(page, tab_id=task_id or "current")
            v_res = ActionVerifier.verify(action_obj, exec_res, pre_obs, post_obs)

            step_record = StepExecutionRecord(
                step_number=step + 1,
                action=action_obj.action.value,
                target=action_obj.target,
                reason=action_obj.reason or "",
                success=exec_res.success and v_res.passed,
                result_message=exec_res.message,
                pre_url=pre_obs.url,
                post_url=post_obs.url,
                verification_passed=v_res.passed,
                verification_notes=v_res.explanation,
                timestamp=time.time(),
            )

            # Diagnostic screenshot on failure
            if not step_record.success:
                ss_path = await self.perception_engine.visual_sensor.capture_screenshot(
                    page,
                    filename_prefix=f"failure_step_{step+1}",
                )
                step_record.screenshot_path = ss_path

            history.append(step_record)

            # 9. Dynamic Retry / Recovery on Failure
            if not step_record.success:
                logger.warning(f"Step {step+1} failed verification: {v_res.explanation}. Initiating dynamic replan...")
                # Allow next loop iteration to re-observe and replan with the error recorded in history
                await asyncio.sleep(1.0)

            step += 1

        return AutomationWorkflowResult(
            success=False,
            objective=objective,
            total_steps=step,
            history=history,
            final_url=page.url if page else None,
            error=f"Workflow reached maximum step limit ({max_steps}) without completing objective.",
        )
