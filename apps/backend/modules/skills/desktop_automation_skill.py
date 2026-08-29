import os
import json
import asyncio
import logging
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill
from container import ServiceContainer

logger = logging.getLogger("JARVIS.DesktopAutomationSkill")

class DesktopAutomationSkill(BaseSkill):
    """
    Skill for autonomous desktop interaction (vision + mouse + keyboard).
    Implements a ReAct loop to achieve complex user goals on the native OS.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Automate a multi-step desktop/Windows flow (e.g. scroll, read, find, click) to achieve a goal")
    async def automate_desktop_flow(self, goal: str) -> str:
        """Automate a sequence of native OS actions based on a goal."""
        async def _do_automate():
            import pyautogui
            
            ui_mapper = ServiceContainer.instance().get_or_none("ui_mapper")
            if not ui_mapper:
                return "Error: UIMapper not available. Cannot find UI elements."

            screen_w, screen_h = pyautogui.size()
            history = []
            max_steps = 10
            
            for step in range(max_steps):
                image_path = await self.capture_screen()
                if not os.path.exists(image_path):
                    return f"Error: Failed to capture screen at step {step + 1}."

                prompt = (
                    f"You are JARVIS, executing an autonomous desktop flow.\n"
                    f"Goal: '{goal}'\n"
                    f"History of actions taken so far: {history}\n\n"
                    f"Based on the provided screenshot of the current screen, what is the VERY NEXT action to take?\n"
                    f"Return ONLY a valid JSON object with no markdown formatting. The JSON MUST have a 'reasoning' key explaining your thought process (e.g. keeping count of items), and an 'action' key with one of these values:\n"
                    f"- 'click': Also provide 'element_name' (a short string describing the UI element to click).\n"
                    f"- 'scroll': Also provide 'amount' (integer, e.g., -500 to scroll down, 500 to scroll up).\n"
                    f"- 'type': Also provide 'text' (string to type on the keyboard).\n"
                    f"- 'wait': Also provide 'ms' (integer milliseconds to wait).\n"
                    f"- 'done': Also provide 'summary' (string describing what was accomplished).\n\n"
                    f"Example 1: {{\"reasoning\": \"I need to open the notifications panel first.\", \"action\": \"click\", \"element_name\": \"Notification icon\"}}\n"
                    f"Example 2: {{\"reasoning\": \"I only see 4 items, I need to scroll down to see more.\", \"action\": \"scroll\", \"amount\": -500}}\n"
                    f"Example 3: {{\"reasoning\": \"I found the 10th video and clicked it.\", \"action\": \"done\", \"summary\": \"Clicked the 10th video.\"}}"
                )

                response = await self.analyze_image(image_path=image_path, prompt=prompt)
                
                if str(response).startswith("Error:"):
                    logger.warning(f"Vision API analysis failed: {response}. Retrying after short delay...")
                    history.append(f"thought: Vision API error ({response[:50]}). Waiting 2s... | action: wait")
                    await asyncio.sleep(2.0)
                    continue

                try:
                    action_data = self.clean_and_parse_json(response)
                    if not isinstance(action_data, dict) or "action" not in action_data:
                        raise ValueError("Invalid JSON format or missing 'action' key.")
                    
                    action = action_data["action"]
                    reasoning = action_data.get("reasoning", "")
                    
                    if action == "done":
                        summary = action_data.get("summary", "Goal completed.")
                        history.append(f"thought: {reasoning} | done: {summary}")
                        return f"Automation completed successfully.\nFlow History:\n" + "\n".join(history)
                        
                    elif action == "click":
                        element_name = action_data.get("element_name", "")
                        bbox = ui_mapper.get_element(element_name)
                        
                        if not bbox:
                            history.append(f"thought: {reasoning} | error: Attempted to click '{element_name}' but it was not found on screen.")
                            await asyncio.sleep(1)
                            continue
                            
                        ymin, xmin, ymax, xmax = bbox
                        center_x = int(((xmin + xmax) / 2) / 1000.0 * screen_w)
                        center_y = int(((ymin + ymax) / 2) / 1000.0 * screen_h)
                        
                        pyautogui.click(center_x, center_y)
                        history.append(f"thought: {reasoning} | click '{element_name}' at ({center_x}, {center_y})")
                        await asyncio.sleep(1.0)
                        
                    elif action == "scroll":
                        amount = action_data.get("amount", -300)
                        pyautogui.scroll(amount)
                        history.append(f"thought: {reasoning} | scroll by {amount}")
                        await asyncio.sleep(1.0)
                        
                    elif action == "type":
                        text = action_data.get("text", "")
                        pyautogui.write(text, interval=0.05)
                        history.append(f"thought: {reasoning} | type '{text}'")
                        await asyncio.sleep(0.5)
                        
                    elif action == "wait":
                        ms = action_data.get("ms", 1000)
                        await asyncio.sleep(ms / 1000.0)
                        history.append(f"thought: {reasoning} | wait {ms}ms")
                        
                    else:
                        history.append(f"Unknown action: {action}")
                        
                    # Standard pause for UI rendering between steps
                    await asyncio.sleep(1.5)

                        
                except Exception as e:
                    logger.error(f"Failed to parse or execute action in DesktopAutomationSkill: {response} - {e}")
                    history.append(f"error processing LLM instruction: {e}")
                    await asyncio.sleep(2) # Prevent rapid error loops
                    
            return f"CRITICAL FAILURE: Automation stopped after reaching max steps ({max_steps}) without completing the goal. DO NOT TELL THE USER IT WAS SUCCESSFUL.\nFlow History:\n" + "\n".join(history)

        return await self.safe_execute(
            _do_automate,
            confirmation_category="system",
            confirmation_action=f"automate desktop flow for goal: {goal}",
            confirmed=True, # Needs to be true for autonomous execution
            success_msg="Automated desktop flow",
            error_msg="Failed to automate desktop flow"
        )
