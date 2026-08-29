import logging
import asyncio
import uuid
import json
import time
from typing import Dict, Any, Optional, List
from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.InteractionAgent")

class GroundedActionSchema:
    ALLOWED_ACTIONS = {"scroll", "click", "type", "wait", "done"}
    
    @classmethod
    def validate_and_normalize(cls, data: dict) -> dict:
        if not isinstance(data, dict):
            raise TypeError("Action decision must be a dictionary.")
            
        action = data.get("action")
        if not action or action not in cls.ALLOWED_ACTIONS:
            raise ValueError(f"Invalid or missing action. Must be one of: {cls.ALLOWED_ACTIONS}")
            
        args = data.get("args", {})
        if not isinstance(args, dict):
            raise TypeError("Action 'args' must be a dictionary.")
            
        normalized_args = {}
        
        if action == "scroll":
            amount = args.get("amount")
            if amount is None:
                amount = -500
            try:
                normalized_args["amount"] = int(amount)
            except (ValueError, TypeError):
                raise ValueError("Scroll action requires an integer 'amount'.")
                
        elif action == "click":
            x = args.get("x")
            y = args.get("y")
            if x is None or y is None:
                raise ValueError("Click action requires both 'x' and 'y' coordinates.")
            try:
                normalized_args["x"] = int(float(x))
                normalized_args["y"] = int(float(y))
            except (ValueError, TypeError):
                raise ValueError("Click coordinates 'x' and 'y' must be numeric.")
                
        elif action == "type":
            text = args.get("text")
            if text is None:
                text = ""
            normalized_args["text"] = str(text)
            
            # Allow optional target coordinates if type triggers automated target click
            x = args.get("x")
            y = args.get("y")
            if x is not None and y is not None:
                try:
                    normalized_args["x"] = int(float(x))
                    normalized_args["y"] = int(float(y))
                except (ValueError, TypeError):
                    pass
            selector = args.get("selector")
            if selector is not None:
                normalized_args["selector"] = str(selector).strip()
                
        elif action == "wait":
            ms = args.get("ms")
            if ms is None:
                ms = 1000
            try:
                normalized_args["ms"] = min(max(int(ms), 0), 5000)
            except (ValueError, TypeError):
                raise ValueError("Wait action requires an integer 'ms'.")
                
        elif action == "done":
            success = args.get("success")
            if success is None:
                success = False
            normalized_args["success"] = bool(success)
            if success:
                normalized_args["summary"] = str(args.get("summary", "Goal completed."))
            else:
                normalized_args["error"] = str(args.get("error", "Failed to complete grounded task."))
                
        return {"action": action, "args": normalized_args, "reasoning": str(data.get("reasoning", ""))}

class InteractionAgent(BaseAgent):
    """
    InteractionAgent conducts turn-by-turn grounded perception-action loops.
    Cooperates with VisionAgent (observe), planning-lite LLM (decide), and Mouse/Keyboard via ExecutionAgent (act).
    """
    def __init__(self, bus):
        super().__init__(agent_id="interaction_agent")
        self.bus = bus
        self.bus.register(self.agent_id, self.handle)
        
        # Shared world state manager singleton instance resolved once
        from modules.execution.world_state import WorldStateManager
        self.ws = WorldStateManager()
        
        logger.info("InteractionAgent registered on AgentBus.")

    async def _publish_status(self, message: str) -> None:
        try:
            from container import ServiceContainer
            c = ServiceContainer.instance()
            room = c.get_or_none("room") if c else None
            if room:
                payload = json.dumps({"type": "status", "message": message})
                await room.local_participant.publish_data(payload.encode("utf-8"))
                logger.info(f"Published status to room: {message}")
        except Exception as e:
            logger.warning(f"Failed to publish status '{message}': {e}")

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        if task_type != "run_grounded_task":
            return self._create_result(
                task,
                success=False,
                error=f"InteractionAgent does not support task type '{task_type}'"
            )
            
        description = payload.get("description", "")
        args = payload.get("args", {})
        
        logger.info(f"InteractionAgent started grounded subtask: '{description}'")
        await self._publish_status(f"Starting visual search: {description}...")
        
        # Check if browser page is active and we are looking for a link/result
        # This is a robust DOM-based fallback to bypass vision rate limits for link clicks
        collection_hint_test = ""
        ordinal_test = None
        
        # Simple local keyword check to avoid calling LLM for grounding hints if rate limited
        desc_lower = description.lower()
        if "link" in desc_lower or "result" in desc_lower:
            collection_hint_test = "link"
            for word in desc_lower.replace(",", " ").replace(".", " ").split():
                if "1st" in word or "first" in word:
                    ordinal_test = 1
                elif "2nd" in word or "second" in word:
                    ordinal_test = 2
                elif "3rd" in word or "third" in word:
                    ordinal_test = 3
                    
        if collection_hint_test == "link" and ordinal_test is not None:
            try:
                from container import ServiceContainer
                c = ServiceContainer.instance()
                tools = c.get_or_none("tools") if c else []
                browser_tool = next((t for t in tools if hasattr(t, "browser_ctrl")), None)
                if browser_tool and browser_tool.browser_ctrl and browser_tool.browser_ctrl.page:
                    page = browser_tool.browser_ctrl.page
                    url = page.url
                    if "google.com/search" in url:
                        logger.info("InteractionAgent DOM Fallback: Google search page detected. Extracting links directly.")
                        links = await browser_tool.browser_ctrl.google_search._extract_generic_links()
                        if links and len(links) >= ordinal_test:
                            target_url = links[ordinal_test - 1]["url"]
                            logger.info(f"InteractionAgent DOM Fallback: Found target link URL: {target_url}. Navigating browser directly!")
                            await browser_tool.browser_ctrl.open_url(target_url)
                            return self._create_result(task, success=True, result={
                                "status": "completed",
                                "summary": f"Directly navigated browser to the {ordinal_test}th link: {target_url}"
                            })
            except Exception as dom_err:
                logger.warning(f"InteractionAgent DOM Fallback failed: {dom_err}")
        
        # Grounding Extraction: Extract hints from description using LLM
        collection_hint = None
        ordinal = None
        direction = "top-to-bottom"
        
        try:
            extraction_prompt = f"""
            Given the grounded task description: "{description}"
            Extract the collection/element type we are looking for and the 1-indexed ordinal number (if any).
            Also identify if there is a direction preference.
            
            Return a JSON object:
            {{
              "collection_hint": "e.g. video, button, link, search result",
              "ordinal": integer or null,
              "direction": "top-to-bottom" | "left-to-right" | "bottom-to-top" (default "top-to-bottom")
            }}
            Return ONLY the raw JSON object.
            """
            extraction_res = await self.generate_response(extraction_prompt, response_mime_type="application/json")
            parsed_hints = self._parse_json_response(extraction_res)
            collection_hint = parsed_hints.get("collection_hint")
            
            raw_ordinal = parsed_hints.get("ordinal")
            try:
                if raw_ordinal is not None:
                    ordinal = int(float(raw_ordinal))
            except (ValueError, TypeError):
                logger.warning(f"Invalid ordinal value '{raw_ordinal}' extracted. Ignored.")
                
            direction = parsed_hints.get("direction", "top-to-bottom")
            logger.info(f"Extracted grounding hints: collection_hint={collection_hint}, ordinal={ordinal}, direction={direction}")
        except Exception as e:
            logger.warning(f"Failed to extract grounding hints via LLM: {e}. Proceeding without hints.")
            
        # Grounding Loop setup
        max_iterations = 6
        prev_hash = None
        history: List[dict] = []
        
        start_time = time.time()
        time_budget = 300.0  # 5 minutes wall-clock timeout budget
        
        stuck_count = 0
        diff_failure_count = 0
        
        for iteration in range(1, max_iterations + 1):
            logger.info(f"Grounded Interaction Loop - Iteration {iteration}/{max_iterations}")
            
            # Check wall-clock budget
            if time.time() - start_time > time_budget:
                return await self._escalate_to_recovery(
                    task, 
                    description, 
                    f"Grounded task exceeded hard time budget of {time_budget}s.",
                    last_observation="N/A (Timeout)",
                    last_action="iteration budget check"
                )
            
            # Check cancellation token (if available)
            try:
                from modules.task.state_manager import AgentStateManager
                sm = AgentStateManager()
                if sm.cancel_token.is_cancelled:
                    return self._create_result(task, success=False, error="Task was cancelled.")
            except Exception:
                pass
                
            # A. Stuck Detection (using screen state diff hash)
            diff_task = AgentTask(
                task_id=str(uuid.uuid4()),
                task_type="diff_screen_state",
                payload={"before_hash": prev_hash} if prev_hash else {},
                origin_agent=self.agent_id,
                target_agent="vision_agent"
            )
            diff_res = await self.bus.dispatch(diff_task)
            if diff_res.success:
                diff_failure_count = 0
                diff_data = diff_res.result
                current_hash = diff_data.get("current_hash")
                changed = diff_data.get("changed", True)
                if prev_hash and not changed:
                    stuck_count += 1
                    logger.warning(f"Stuck detection: Screen hash unchanged (count {stuck_count}).")
                    if stuck_count >= 2:
                        return await self._escalate_to_recovery(
                            task, 
                            description, 
                            "Screen state has not changed (stuck).",
                            last_observation="N/A",
                            last_action=str(history[-1]) if history else "N/A"
                        )
                else:
                    stuck_count = 0
                if current_hash:
                    prev_hash = current_hash
            else:
                diff_failure_count += 1
                logger.warning(f"Stuck detection: diff_screen_state failed ({diff_failure_count}/3): {diff_res.error}")
                if diff_failure_count >= 3:
                    return await self._escalate_to_recovery(
                        task, 
                        description, 
                        f"Screen diffing failed repeatedly (degraded state): {diff_res.error}",
                        last_observation="N/A",
                        last_action=str(history[-1]) if history else "N/A"
                    )
            
            # B. Observe (Locate/Identify elements)
            vision_obs_str = ""
            if collection_hint and ordinal is not None:
                locate_task = AgentTask(
                    task_id=str(uuid.uuid4()),
                    task_type="locate_ordinal_element",
                    payload={
                        "collection_hint": collection_hint,
                        "ordinal": ordinal,
                        "direction": direction
                    },
                    origin_agent=self.agent_id,
                    target_agent="vision_agent"
                )
                locate_res = await self.bus.dispatch(locate_task)
                if locate_res.success:
                    vision_obs = locate_res.result
                    if not isinstance(vision_obs, dict):
                        vision_obs = {"found": False}
                        
                    # Validate structured vision fields defensively
                    found = vision_obs.get("found", False)
                    needs_scroll = vision_obs.get("needs_scroll", False)
                    x_coord = vision_obs.get("x")
                    y_coord = vision_obs.get("y")
                    
                    if found:
                        try:
                            float(x_coord)
                            float(y_coord)
                        except (TypeError, ValueError):
                            logger.warning(f"Vision locate ordinal reported 'found' but invalid coordinates x={x_coord}, y={y_coord}. Resetting found to False.")
                            vision_obs["found"] = False
                            
                    vision_obs_str = json.dumps(vision_obs)
                    logger.info(f"Vision locate ordinal element: {vision_obs_str}")
                    
                    if vision_obs.get("found"):
                        label = vision_obs.get("label") or f"item {ordinal}"
                        await self._publish_status(f"Found '{label}'. Clicking...")
                    elif vision_obs.get("needs_scroll"):
                        await self._publish_status(f"Scrolling down to look for {collection_hint} {ordinal}...")
                else:
                    vision_obs_str = f"Error calling locate_ordinal_element: {locate_res.error}"
            else:
                analyze_task = AgentTask(
                    task_id=str(uuid.uuid4()),
                    task_type="analyze_screen",
                    payload={"query": f"Describe the screen contents to help execute task: {description}"},
                    origin_agent=self.agent_id,
                    target_agent="vision_agent"
                )
                analyze_res = await self.bus.dispatch(analyze_task)
                if analyze_res.success:
                    vision_obs_str = analyze_res.result.get("analysis", "")
                    logger.info(f"Vision analyze screen: {vision_obs_str}")
                else:
                    vision_obs_str = f"Error calling analyze_screen: {analyze_res.error}"
                    
            # C. Decide (LLM next step decision)
            # Use only the last 4 actions to prevent prompt history context window pollution
            prompt_history = history[-4:]
            prompt_history_str = json.dumps(prompt_history, indent=2)
            
            decision_prompt = f"""
            You are the Decision component of JARVIS's Grounded Interaction Loop.
            Goal: "{description}"
            
            Current step: {iteration}/{max_iterations}
            Action history in this loop (last few actions): {prompt_history_str}
            
            Latest vision observation:
            {vision_obs_str}
            
            Decide the next single action to take. Choose from:
            1. Scroll the screen to find the element.
               Action JSON: {{"action": "scroll", "args": {{"amount": -500}}}} (use negative to scroll down, positive to scroll up)
            2. Click on the target element at its absolute coordinates (x, y) if it has been found.
               Action JSON: {{"action": "click", "args": {{"x": <x_coord>, "y": <y_coord>}}}}
            3. Type text if needed. You can optionally specify target coordinates (x, y) to click target input field first before typing.
               Action JSON: {{"action": "type", "args": {{"text": "<text_to_type>", "x": <optional_x>, "y": <optional_y>}}}}
            4. Wait for page load or stability.
               Action JSON: {{"action": "wait", "args": {{"ms": 1000}}}}
            5. We have successfully achieved the goal.
               Action JSON: {{"action": "done", "args": {{"success": true, "summary": "<success summary>"}}}}
            6. We are stuck, cannot find the element, or cannot complete the task.
               Action JSON: {{"action": "done", "args": {{"success": false, "error": "<reason for giving up>"}}}}
            
            Return ONLY the valid JSON object for the next action.
            """
            
            try:
                decision_res = await self.generate_response(decision_prompt, response_mime_type="application/json")
                action_data = GroundedActionSchema.validate_and_normalize(self._parse_json_response(decision_res))
            except Exception as e:
                logger.error(f"Failed to generate/parse/validate decision action: {e}")
                return await self._escalate_to_recovery(
                    task, 
                    description, 
                    f"Failed to decide valid next step: {e}",
                    last_observation=vision_obs_str,
                    last_action="iteration decide call"
                )
                
            action = action_data.get("action")
            action_args = action_data.get("args", {})
            reasoning = action_data.get("reasoning", "")
            
            logger.info(f"Grounded loop decision: action={action}, args={action_args}, reasoning={reasoning}")
            
            # Log step in the shared WorldStateManager singleton instance
            self.ws.update_shared_state("last_interaction_step", {
                "iteration": iteration,
                "action": action,
                "args": action_args,
                "reasoning": reasoning
            })
            
            if action == "done":
                success = action_args.get("success", False)
                if success:
                    summary = action_args.get("summary", "Goal completed.")
                    await self._publish_status(f"Action complete: {summary}")
                    return self._create_result(task, success=True, result={"status": "completed", "summary": summary})
                else:
                    err = action_args.get("error", "Failed to complete grounded task.")
                    logger.warning(f"Grounded task reported failure: {err}")
                    return await self._escalate_to_recovery(
                        task, 
                        description, 
                        err,
                        last_observation=vision_obs_str,
                        last_action=f"action: {action}, args: {action_args}"
                    )
                    
            # D. Act (Dispatch action to ExecutionAgent)
            subtasks_list = []
            if action == "scroll":
                amount = action_args.get("amount", -500)
                subtasks_list = [{
                    "id": 1,
                    "description": f"Scroll by {amount}",
                    "tool_name": "scroll_mouse",
                    "args": {"amount": amount},
                    "dependencies": [],
                    "execution_mode": "deterministic"
                }]
            elif action == "click":
                x = action_args.get("x")
                y = action_args.get("y")
                subtasks_list = [{
                    "id": 1,
                    "description": f"Click mouse at ({x}, {y})",
                    "tool_name": "click_mouse",
                    "args": {"x": x, "y": y},
                    "dependencies": [],
                    "execution_mode": "deterministic"
                }]
            elif action == "type":
                text = action_args.get("text", "")
                x = action_args.get("x")
                y = action_args.get("y")
                
                # If target coordinates specified, click input field first
                if x is not None and y is not None:
                    click_subtask = {
                        "id": 1,
                        "description": f"Click mouse at ({x}, {y})",
                        "tool_name": "click_mouse",
                        "args": {"x": x, "y": y},
                        "dependencies": [],
                        "execution_mode": "deterministic"
                    }
                    type_subtask = {
                        "id": 2,
                        "description": f"Type text '{text}'",
                        "tool_name": "type_text",
                        "args": {"text": text},
                        "dependencies": [1],
                        "execution_mode": "deterministic"
                    }
                    subtasks_list = [click_subtask, type_subtask]
                else:
                    type_subtask = {
                        "id": 1,
                        "description": f"Type text '{text}'",
                        "tool_name": "type_text",
                        "args": {"text": text},
                        "dependencies": [],
                        "execution_mode": "deterministic"
                    }
                    subtasks_list = [type_subtask]
                    
            elif action == "wait":
                ms = action_args.get("ms", 1000)
                await asyncio.sleep(ms / 1000.0)
                history.append({
                    "step": iteration,
                    "action": "wait",
                    "args": action_args,
                    "success": True,
                    "result": f"Waited {ms}ms",
                    "timestamp": time.time()
                })
                continue
                
            action_success = False
            exec_res_str = ""
            if subtasks_list:
                exec_task = AgentTask(
                    task_id=str(uuid.uuid4()),
                    task_type="execute_plan",
                    payload={
                        "plan": subtasks_list,
                        "goal": description
                    },
                    origin_agent=self.agent_id,
                    target_agent="execution_agent"
                )
                exec_res = await self.bus.dispatch(exec_task)
                action_success = exec_res.success
                exec_res_str = str(exec_res.result if exec_res.success else exec_res.error)
                
                if not action_success:
                    logger.warning(f"Action dispatch failed: {exec_res.error}")
                    return await self._escalate_to_recovery(
                        task, 
                        description, 
                        f"Action execution failed: {exec_res.error}",
                        last_observation=vision_obs_str,
                        last_action=f"action: {action}, args: {action_args}"
                    )
            
            history.append({
                "step": iteration,
                "action": action,
                "args": action_args,
                "success": action_success,
                "result": exec_res_str,
                "timestamp": time.time()
            })
            
        return await self._escalate_to_recovery(
            task, 
            description, 
            "Iteration limit reached without achieving goal.",
            last_observation=vision_obs_str,
            last_action=str(history[-1]) if history else "N/A"
        )

    async def _escalate_to_recovery(self, task: AgentTask, description: str, error_reason: str, last_observation: str = "", last_action: str = "") -> AgentResult:
        logger.warning(f"InteractionAgent escalating grounded failure to recovery: {error_reason}")
        await self._publish_status(f"Task failed: {error_reason}. Attempting self-healing recovery...")
        
        # 1. Generate context via coordinator
        ctx_task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="generate_context",
            payload={"goal": description},
            origin_agent=self.agent_id,
            target_agent="coordinator_agent"
        )
        ctx_result = await self.bus.dispatch(ctx_task)
        dynamic_context = ctx_result.result.get("context", "") if (ctx_result and ctx_result.success) else ""
        
        error_context_str = (
            f"Error Reason: {error_reason}\n"
            f"Last Observation: {last_observation}\n"
            f"Last Action: {last_action}\n"
            f"Dynamic context: {dynamic_context}"
        )
        
        # 2. Call recover_failure on recovery_agent
        recovery_task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="recover_failure",
            payload={
                "failed_task_description": description,
                "error_context": error_context_str,
                "goal": description
            },
            origin_agent=self.agent_id,
            target_agent="recovery_agent"
        )
        recovery_result = await self.bus.dispatch(recovery_task)
        
        if recovery_result.success:
            res_data = recovery_result.result
            if not isinstance(res_data, dict):
                res_data = {"action": "abort", "reason": str(res_data)}
                
            action = str(res_data.get("action", "abort")).lower().strip()
            logger.info(f"Recovery agent responded with action: '{action}'")
            
            if action == "replan":
                new_plan = res_data.get("new_plan")
                if new_plan:
                    logger.info("Recovery agent suggested replan. Dispatching new plan to ExecutionAgent...")
                    await self._publish_status("Recovery successful. Executing new plan...")
                    exec_task = AgentTask(
                        task_id=str(uuid.uuid4()),
                        task_type="execute_plan",
                        payload={
                            "plan": new_plan,
                            "goal": description
                        },
                        origin_agent=self.agent_id,
                        target_agent="execution_agent"
                    )
                    return await self.bus.dispatch(exec_task)
                else:
                    return self._create_result(task, success=False, error="Recovery replan failed: new plan was empty.")
                    
            elif action == "retry":
                retry_count = task.payload.get("retry_count", 0)
                if retry_count < 2:
                    logger.info(f"Recovery agent suggested retry. Retrying task (attempt {retry_count + 1})...")
                    await self._publish_status(f"Retrying visual search (attempt {retry_count + 1})...")
                    task.payload["retry_count"] = retry_count + 1
                    return await self.handle(task)
                else:
                    logger.warning("Recovery retry ignored: max retry limit reached.")
                    return self._create_result(task, success=False, error=f"Grounded task failed: Max retry attempts exceeded. Error: {error_reason}")
                    
            elif action == "abort":
                reason = res_data.get("reason", "No reason provided.")
                logger.info(f"Recovery agent aborted task: {reason}")
                return self._create_result(task, success=False, error=f"Grounded task aborted: {reason}")
                
            else:
                return self._create_result(task, success=False, error=f"Grounded task failed: Unknown recovery action '{action}'. Original error: {error_reason}")
                
        return self._create_result(task, success=False, error=f"Grounded task failed: Recovery escalation failed. Original error: {error_reason}")
