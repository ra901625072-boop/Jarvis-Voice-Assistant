import json
import asyncio
import time
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill
from container import ServiceContainer
from ai.agents.browser.schemas import BrowserActionSchema

class BrowserAutomationSkill(BaseSkill):
    """
    Skill for multi-step web flows (navigate -> click -> type -> extract).
    Re-uses the existing BrowserTools instance from ServiceContainer to avoid duplicate Playwright sessions.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    def _get_browser_tools(self):
        container = ServiceContainer.instance()
        if not container:
            return None
        tools_list = container.get_or_none("tools")
        if not tools_list:
            return None
            
        for t in tools_list:
            if t.__class__.__name__ == "BrowserTools":
                return t
        return None

    async def _wait_for_selector(self, ctrl, selector: str, timeout_ms: int = 3000) -> bool:
        """Checks for selector presence and visibility defensively, with exception guards."""
        if not ctrl.page or not selector:
            return False
            
        try:
            locator = ctrl.page.locator(selector)
            await locator.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception as e:
            self.logger.debug(f"Selector '{selector}' visibility wait failed: {e}")
            try:
                count = await ctrl.page.locator(selector).count()
                return count > 0
            except Exception:
                return False

    @llm.function_tool(description="Automate a multi-step web flow based on instructions")
    async def automate_web_flow(self, url: str, instructions: str, close_on_finish: bool = False) -> str:
        """Automate a sequence of browser actions."""
        async def _do_automate():
            if not url and not instructions:
                return "Error: Both URL and instructions cannot be empty."

            browser_tools = self._get_browser_tools()
            if not browser_tools:
                return "Error: BrowserTools not found in ServiceContainer. Cannot automate browser."
            
            ctrl = browser_tools.browser_ctrl
            if not ctrl:
                return "Error: BrowserController not found. Cannot automate browser."
                
            start_time = time.time()
            time_budget = 120.0
            results = []
            
            try:
                await ctrl._ensure_driver()
                
                # Step 1: Navigate
                nav_result = await ctrl.open_url(url, timeout=15000)
                if isinstance(nav_result, dict):
                    nav_success = nav_result.get("success", False)
                    nav_res_str = nav_result.get("message", str(nav_result))
                else:
                    nav_success = "failed" not in str(nav_result).lower() and "error" not in str(nav_result).lower()
                    nav_res_str = str(nav_result)
                    
                if not nav_success:
                    return f"Failed to navigate to {url}: {nav_res_str}"
                    
                results.append({
                    "step": 0,
                    "action": "navigate",
                    "selector": None,
                    "success": True,
                    "result": nav_res_str,
                    "timestamp": time.time()
                })
                
                step = 0
                max_steps = 8
                
                while step < max_steps:
                    # 1. Hard time budget check
                    if time.time() - start_time > time_budget:
                        return f"Failed: Automation exceeded hard time budget of {time_budget}s."

                    page_info = await ctrl.get_current_page_info()
                    struct = await ctrl.extract_page_structure()
                    struct_str = json.dumps(struct, indent=2) if isinstance(struct, list) else str(struct)
                    
                    prompt = (
                        f"You are a web automation assistant. Objective: {instructions}\n"
                        f"Current Page: {page_info.get('title')} ({page_info.get('url')})\n"
                        f"Interactive DOM Elements:\n{struct_str}\n\n"
                        f"Decide the single NEXT action to take. Allowed actions:\n"
                        f"- {{\"action\": \"click\", \"selector\": \"css selector\"}}\n"
                        f"- {{\"action\": \"type\", \"selector\": \"css selector\", \"text\": \"text to type\"}}\n"
                        f"- {{\"action\": \"wait\", \"ms\": 1000}}\n"
                        f"- {{\"action\": \"extract\", \"instruction\": \"what to extract/verify\"}}\n"
                        f"- {{\"action\": \"completed\", \"reason\": \"explain goal status\"}}\n\n"
                        f"Return ONLY a JSON object matching one of the options."
                    )
                    
                    plan_text = await self.generate_response(prompt=prompt, response_mime_type="application/json")
                    try:
                        act = BrowserActionSchema.validate_and_normalize(self.clean_and_parse_json(plan_text))
                    except Exception as e:
                        return f"Failed to plan step {step+1}: {e}\nResponse: {plan_text}"
                        
                    action_type = act.get("action")
                    reason = act.get("reason", "")
                    
                    if action_type == "completed":
                        results.append({
                            "step": step + 1,
                            "action": "completed",
                            "selector": None,
                            "success": True,
                            "result": reason,
                            "timestamp": time.time()
                        })
                        break
                        
                    action_success = False
                    action_res = ""
                    
                    if action_type == "wait":
                        ms = act.get("ms", 1000)
                        await asyncio.sleep(ms / 1000.0)
                        action_success = True
                        action_res = f"Waited {ms}ms"
                    elif action_type == "extract":
                        page_text = await browser_tools.get_page_state()
                        extract_prompt = f"Extract or answer '{act.get('instruction')}' based on the page text:\n\n{page_text}"
                        action_res = await self.generate_response(prompt=extract_prompt)
                        action_success = True
                    elif action_type in ("click", "type"):
                        selector = act.get("selector", "")
                        text = act.get("text", "")
                        
                        exists = await self._wait_for_selector(ctrl, selector)
                        if exists:
                            if action_type == "click":
                                action_res = await ctrl.click_dom_element(selector, timeout=10000)
                            else:
                                action_res = await ctrl.fill_form(selector, text, timeout=10000)
                                
                            if isinstance(action_res, dict):
                                action_success = action_res.get("success", False)
                                action_res = action_res.get("message", str(action_res))
                            else:
                                action_success = "error" not in str(action_res).lower() and "failed" not in str(action_res).lower()
                        else:
                            action_res = f"Verification failed: Selector '{selector}' was not found/visible."
                            
                    # Dynamic Retry (re-observe and request corrected action from LLM)
                    if not action_success and action_type in ("click", "type"):
                        self.logger.warning(f"Step {step+1} failed: {action_res}. Re-observing the page and requesting corrected action...")
                        await asyncio.sleep(1.5)
                        
                        try:
                            page_info = await ctrl.get_current_page_info()
                            struct = await ctrl.extract_page_structure()
                            struct_str = json.dumps(struct, indent=2) if isinstance(struct, list) else str(struct)
                            
                            retry_prompt = (
                                f"Your previous action '{action_type}' with selector '{act.get('selector')}' failed.\n"
                                f"Action result: {action_res}\n\n"
                                f"Objective: {instructions}\n"
                                f"Current Page State: {page_info.get('title')} ({page_info.get('url')})\n"
                                f"Interactive DOM Elements:\n{struct_str}\n\n"
                                f"Based on this new state, decide a corrected single action. Return ONLY JSON."
                            )
                            
                            retry_plan_text = await self.generate_response(prompt=retry_prompt, response_mime_type="application/json")
                            retry_act = BrowserActionSchema.validate_and_normalize(self.clean_and_parse_json(retry_plan_text))
                            action_type = retry_act.get("action")
                            reason = retry_act.get("reason", "")
                            
                            if action_type == "completed":
                                results.append({
                                    "step": step + 1,
                                    "action": "completed",
                                    "selector": None,
                                    "success": True,
                                    "result": reason,
                                    "timestamp": time.time()
                                })
                                break
                                
                            if action_type == "navigate":
                                target_url = retry_act.get("url")
                                action_res = await ctrl.open_url(target_url, timeout=15000)
                                if isinstance(action_res, dict):
                                    action_success = action_res.get("success", False)
                                    action_res = action_res.get("message", str(action_res))
                                else:
                                    action_success = "error" not in str(action_res).lower() and "failed" not in str(action_res).lower()
                            elif action_type in ("click", "type"):
                                selector = retry_act.get("selector")
                                text = retry_act.get("text", "")
                                
                                exists = await self._wait_for_selector(ctrl, selector)
                                if exists:
                                    if action_type == "click":
                                        action_res = await ctrl.click_dom_element(selector, timeout=10000)
                                    else:
                                        action_res = await ctrl.fill_form(selector, text, timeout=10000)
                                        
                                    if isinstance(action_res, dict):
                                        action_success = action_res.get("success", False)
                                        action_res = action_res.get("message", str(action_res))
                                    else:
                                        action_success = "error" not in str(action_res).lower() and "failed" not in str(action_res).lower()
                                else:
                                    action_res = f"Selector '{selector}' not visible on retry."
                        except Exception as retry_err:
                            action_res = f"Retry planning failed: {retry_err}"
                            
                    results.append({
                        "step": step + 1,
                        "action": action_type,
                        "selector": act.get("selector") if action_type in ("click", "type") else None,
                        "success": action_success,
                        "result": str(action_res),
                        "timestamp": time.time()
                    })
                    
                    if not action_success:
                        # Save screenshot on failure
                        screenshot_path = f"d:/Jarvis/automation_failure_step_{step+1}.png"
                        try:
                            if ctrl.page:
                                await ctrl.page.screenshot(path=screenshot_path)
                                self.logger.info(f"Saved failure screenshot to: {screenshot_path}")
                        except Exception as ss_err:
                            self.logger.warning(f"Failed to capture failure screenshot: {ss_err}")
                            
                        return f"Failed permanently at step {step+1} ({action_type}): {action_res}"
                        
                    step += 1
                    await asyncio.sleep(1.0)
                    
                return "Automation completed.\n" + json.dumps(results, indent=2)
            finally:
                # Cleanup: close current page context only if explicitly requested
                if close_on_finish:
                    try:
                        await ctrl.close_website(url)
                    except Exception as clean_err:
                        self.logger.warning(f"Browser cleanup failed: {clean_err}")

        return await self.safe_execute(
            _do_automate,
            confirmation_category="media",
            confirmation_action=f"automate web flow on {url}",
            confirmed=True,
            success_msg="Automated web flow",
            error_msg="Failed to automate web flow"
        )

    @llm.function_tool(description="Extract specific data fields from a web page")
    async def extract_page_data(self, url: str, fields: str) -> str:
        """Navigate to a URL and extract specific fields."""
        async def _do_extract():
            browser_tools = self._get_browser_tools()
            if not browser_tools:
                return "Error: BrowserTools not found."
            
            nav_result = await browser_tools.navigate(url=url)
            if "failed" in str(nav_result).lower() or "error" in str(nav_result).lower():
                return f"Failed to navigate to {url}: {nav_result}"

            page_state = await browser_tools.get_page_state()
            
            prompt = (
                f"You are a web data extraction tool. Extract the following fields from the page content below.\n"
                f"Fields to extract: {fields}\n\n"
                f"Page Content:\n{page_state}\n\n"
                f"Return the extracted data as a formatted JSON object."
            )
            
            data = await self.generate_response(prompt=prompt, response_mime_type="application/json")
            return data

        return await self.safe_execute(
            _do_extract,
            confirmation_category="read",
            confirmation_action=f"extract {fields} from {url}",
            confirmed=True,
            success_msg="Extracted page data successfully",
            error_msg="Failed to extract page data"
        )
