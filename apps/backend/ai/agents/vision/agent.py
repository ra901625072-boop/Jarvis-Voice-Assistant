import logging
from typing import Optional
from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.VisionAgent")

class VisionAgent(BaseAgent):
    """
    Visual understanding and screen analysis.
    Absorbs VisionManager reasoning logic and ScreenAssistantSkill.
    """
    def __init__(self, vision_manager, bus):
        super().__init__(agent_id="vision_agent")
        self.vision_manager = vision_manager
        self.bus = bus
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "analyze_screen":
                prompt = payload.get("prompt", "Describe what is visible on the screen")
                query = payload.get("query", "Describe what is visible on the screen")
                
                result_text = await self.vision_manager.analyze_screen(
                    query=query,
                    custom_prompt=prompt
                )
                
                return self._create_result(task, success=True, result={"analysis": result_text})
                
            elif task_type == "find_ui_element":
                element_description = payload.get("element_description", "")
                
                if hasattr(self.vision_manager, "ui_mapper"):
                    element = self.vision_manager.ui_mapper.find_element(element_description)
                    return self._create_result(task, success=True, result={"element": element})
                else:
                    return self._create_result(task, success=False, error="UIMapper not available.")
                    
            elif task_type == "read_screen_text":
                import asyncio
                if hasattr(self.vision_manager, "ocr_service") and hasattr(self.vision_manager, "observer"):
                    img_path = self.vision_manager.observer.get_latest_screenshot()
                    from PIL import Image
                    with Image.open(img_path) as pil_img:
                        ocr_text = await asyncio.to_thread(self.vision_manager.ocr_service.extract_text, pil_img)
                    return self._create_result(task, success=True, result={"text": ocr_text})
                else:
                    return self._create_result(task, success=False, error="OCR service not available.")
                
            else:
                return self._create_result(
                    task, 
                    success=False, 
                    error=f"VisionAgent does not support task type '{task_type}'"
                )
        except Exception as e:
            logger.exception(f"VisionAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))
