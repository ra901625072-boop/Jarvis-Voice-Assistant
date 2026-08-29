import os
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class ScreenAssistantSkill(BaseSkill):
    """
    Skill for screen-grounded Q&A, directly using the base capture and vision tools.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Ask a question about what is currently visible on the screen")
    async def ask_about_screen(self, question: str) -> str:
        """Capture the screen and answer a question about it."""
        async def _do_ask():
            # 1. Capture screen
            image_path = await self.capture_screen()
            if not os.path.exists(image_path):
                return "Error: Failed to capture the screen."

            # 2. Analyze with Gemini Vision
            prompt = (
                f"You are a helpful assistant looking at the user's screen. "
                f"Please answer the following question based ONLY on what you see in the image: {question}"
            )
            response = await self.analyze_image(image_path=image_path, prompt=prompt)
            
            # The capture_screen background task will clean up the temp file
            return response

        return await self.safe_execute(
            _do_ask,
            confirmation_category="media", # capturing screen is media/read tier
            confirmation_action="capture screen to answer question",
            confirmed=True,
            success_msg="Analyzed screen successfully",
            error_msg="Failed to analyze screen"
        )

    @llm.function_tool(description="Read and extract all visible text from the current screen")
    async def read_screen_text(self) -> str:
        """Extract text from the current screen."""
        async def _do_read():
            # 1. Capture screen
            image_path = await self.capture_screen()
            if not os.path.exists(image_path):
                return "Error: Failed to capture the screen."

            # 2. Extract text with Gemini Vision
            prompt = (
                "Extract all the readable text from this screenshot. "
                "Structure it logically, keeping paragraphs and lists intact."
            )
            response = await self.analyze_image(image_path=image_path, prompt=prompt)
            return response

        return await self.safe_execute(
            _do_read,
            confirmation_category="media",
            confirmation_action="capture screen to read text",
            confirmed=True,
            success_msg="Extracted screen text successfully",
            error_msg="Failed to extract screen text"
        )

    @llm.function_tool(description="Click a native UI element by name/description (e.g., 'System', 'Submit'). MUST use this for Windows apps, NOT for web browsers.")
    async def click_screen_element(self, element_name: str) -> str:
        """Finds an element on the screen and clicks it."""
        async def _do_click():
            try:
                from container import ServiceContainer
                ui_mapper = ServiceContainer.instance().get_or_none("ui_mapper")
                if not ui_mapper:
                    return "Error: UIMapper not available."
                
                # get_element returns [ymin, xmin, ymax, xmax] scaled to 1000
                bbox = ui_mapper.get_element(element_name)
                if not bbox:
                    return f"Could not find element matching '{element_name}' on screen."
                
                ymin, xmin, ymax, xmax = bbox
                
                import pyautogui
                screen_w, screen_h = pyautogui.size()
                
                # Calculate absolute center coords
                center_x = int(((xmin + xmax) / 2) / 1000.0 * screen_w)
                center_y = int(((ymin + ymax) / 2) / 1000.0 * screen_h)
                
                pyautogui.click(center_x, center_y)
                return f"Successfully clicked '{element_name}' at native coordinates ({center_x}, {center_y})."
            except Exception as e:
                return f"Failed to click '{element_name}': {e}"

        return await self.safe_execute(
            _do_click,
            confirmation_category="system",
            confirmation_action=f"click {element_name} on screen",
            confirmed=True,
            success_msg=f"Clicked {element_name}",
            error_msg=f"Failed to click {element_name}"
        )

    @llm.function_tool(description="Visually verify if a specific state or condition is true on the screen (e.g., 'is a video playing?', 'is the download complete?').")
    async def verify_screen_state(self, condition: str) -> str:
        """Capture the screen and verify if a specific condition is met."""
        async def _do_verify():
            image_path = await self.capture_screen()
            if not os.path.exists(image_path):
                return "Error: Failed to capture the screen."

            prompt = (
                f"You are a strict QA assistant looking at the user's screen. "
                f"Please verify if the following condition is currently true: '{condition}'. "
                f"Answer YES or NO, followed by a brief 1-sentence explanation of what you see that confirms your answer."
            )
            response = await self.analyze_image(image_path=image_path, prompt=prompt)
            return response

        return await self.safe_execute(
            _do_verify,
            confirmation_category="media",
            confirmation_action=f"verify screen condition: {condition}",
            confirmed=True,
            success_msg="Verified screen state",
            error_msg="Failed to verify screen state"
        )
