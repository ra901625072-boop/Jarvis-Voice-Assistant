import logging
import asyncio
import os
from typing import Dict, Any, Optional, List
from PIL import Image
try:
    import pyautogui
except Exception:
    pyautogui = None

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.VisionAgent")

class VisionTaskTypes:
    ANALYZE_SCREEN = "analyze_screen"
    FIND_UI_ELEMENT = "find_ui_element"
    READ_SCREEN_TEXT = "read_screen_text"
    LOCATE_ORDINAL_ELEMENT = "locate_ordinal_element"
    COUNT_VISIBLE_ITEMS = "count_visible_items"
    DIFF_SCREEN_STATE = "diff_screen_state"

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
        logger.info("VisionAgent successfully registered on AgentBus.")

    def _to_abs_bbox(self, bbox: Optional[List[float]], window_rect: Optional[List[int]]) -> Optional[List[int]]:
        """Converts normalized bbox [ymin, xmin, ymax, xmax] (0-1000) to absolute [x, y, w, h]."""
        if not bbox or len(bbox) != 4 or not window_rect or len(window_rect) != 4:
            return None
        win_left, win_top, win_width, win_height = window_rect
        if win_width <= 0 or win_height <= 0:
            logger.warning(f"VisionAgent: Invalid active window dimensions {win_width}x{win_height}.")
            return None
        try:
            ymin, xmin, ymax, xmax = [float(v) for v in bbox]
            abs_xmin = int(win_left + (xmin / 1000.0) * win_width)
            abs_ymin = int(win_top + (ymin / 1000.0) * win_height)
            abs_xmax = int(win_left + (xmax / 1000.0) * win_width)
            abs_ymax = int(win_top + (ymax / 1000.0) * win_height)
            return [abs_xmin, abs_ymin, max(0, abs_xmax - abs_xmin), max(0, abs_ymax - abs_ymin)]
        except (ValueError, TypeError) as e:
            logger.warning(f"VisionAgent: Bbox conversion error: {e}")
            return None

    def _to_abs_center(self, center: Optional[List[float]], window_rect: Optional[List[int]]) -> Optional[List[int]]:
        """Converts normalized center [cx, cy] (0-1000) to absolute screen coordinates [x, y]."""
        if not center or len(center) != 2 or not window_rect or len(window_rect) != 4:
            return None
        win_left, win_top, win_width, win_height = window_rect
        if win_width <= 0 or win_height <= 0:
            return None
        try:
            cx, cy = [float(v) for v in center]
            return [
                int(win_left + (cx / 1000.0) * win_width),
                int(win_top + (cy / 1000.0) * win_height)
            ]
        except (ValueError, TypeError):
            return None

    def _parse_and_validate_vision_json(self, response_str: str, schema_type: str) -> dict:
        """Parses LLM response text and validates schema parameters strictly to prevent silent failures."""
        try:
            parsed = self._parse_json_response(response_str)
        except Exception as e:
            logger.warning(f"VisionAgent: JSON parsing failed: {e}. Raw response: {response_str}")
            parsed = {}

        if not isinstance(parsed, dict):
            logger.warning(f"VisionAgent: Parsed JSON is not a dictionary. Got: {type(parsed)}")
            parsed = {}
            
        if schema_type == "locate":
            parsed["found"] = bool(parsed.get("found", False))
            parsed["needs_scroll"] = bool(parsed.get("needs_scroll", False))
            
            bbox = parsed.get("bbox")
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                try:
                    parsed["bbox"] = [float(v) for v in bbox]
                except (ValueError, TypeError):
                    parsed["bbox"] = None
            else:
                parsed["bbox"] = None
                
            center = parsed.get("center")
            if isinstance(center, (list, tuple)) and len(center) == 2:
                try:
                    parsed["center"] = [float(v) for v in center]
                except (ValueError, TypeError):
                    parsed["center"] = None
            else:
                parsed["center"] = None
                
            # If bounding box is None/invalid, invalidate center coordinates too
            if parsed["bbox"] is None:
                parsed["center"] = None
                
            try:
                parsed["total_visible"] = int(float(parsed.get("total_visible", 0)))
            except (ValueError, TypeError):
                parsed["total_visible"] = 0
                
        elif schema_type == "count":
            try:
                parsed["count"] = int(float(parsed.get("count", 0)))
            except (ValueError, TypeError):
                parsed["count"] = 0
                
            raw_items = parsed.get("items", [])
            valid_items = []
            if isinstance(raw_items, list):
                for idx, item in enumerate(raw_items):
                    if isinstance(item, dict):
                        item_idx = item.get("index")
                        try:
                            item["index"] = int(float(item_idx)) if item_idx is not None else idx + 1
                        except (ValueError, TypeError):
                            item["index"] = idx + 1
                            
                        item["label"] = str(item.get("label", ""))
                        
                        bbox = item.get("bbox")
                        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                            try:
                                item["bbox"] = [float(v) for v in bbox]
                            except (ValueError, TypeError):
                                pass
                        valid_items.append(item)
            parsed["items"] = valid_items
            
        elif schema_type == "diff":
            parsed["changed"] = bool(parsed.get("changed", True))
            parsed["reason"] = str(parsed.get("reason", "No reason provided"))
            
        return parsed

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload or {}
        
        logger.info(f"VisionAgent processing task: '{task_type}'")
        
        try:
            if task_type == VisionTaskTypes.ANALYZE_SCREEN:
                prompt = payload.get("prompt", "Describe what is visible on the screen")
                query = payload.get("query", "Describe what is visible on the screen")
                
                result_text = await self.vision_manager.analyze_screen(
                    query=query,
                    custom_prompt=prompt
                )
                
                data_payload = {"analysis": result_text}
                return self._create_result(task, success=True, result={
                    "task_type": task_type,
                    "data": data_payload,
                    **data_payload
                })
                
            elif task_type == VisionTaskTypes.FIND_UI_ELEMENT:
                element_description = payload.get("element_description", "")
                
                if hasattr(self.vision_manager, "ui_mapper"):
                    ui_mapper = self.vision_manager.ui_mapper
                    if hasattr(ui_mapper, "find_element"):
                        element = ui_mapper.find_element(element_description)
                    elif hasattr(ui_mapper, "get_element"):
                        element = ui_mapper.get_element(element_description)
                    else:
                        element = None
                        
                    if element is None:
                        logger.warning(f"VisionAgent: Element '{element_description}' not found.")
                        return self._create_result(task, success=False, error=f"Element '{element_description}' not found")
                        
                    data_payload = {"element": element}
                    return self._create_result(task, success=True, result={
                        "task_type": task_type,
                        "data": data_payload,
                        **data_payload
                    })
                else:
                    return self._create_result(task, success=False, error="UIMapper not available.")
                    
            elif task_type == VisionTaskTypes.READ_SCREEN_TEXT:
                if hasattr(self.vision_manager, "ocr_service") and hasattr(self.vision_manager, "observer"):
                    img_path = self.vision_manager.observer.get_latest_screenshot()
                    if not img_path or not os.path.exists(img_path):
                        return self._create_result(task, success=False, error="No valid screenshot available for OCR.")
                    
                    with Image.open(img_path) as pil_img:
                        ocr_text = await asyncio.to_thread(self.vision_manager.ocr_service.extract_text, pil_img)
                        
                    data_payload = {"text": ocr_text}
                    return self._create_result(task, success=True, result={
                        "task_type": task_type,
                        "data": data_payload,
                        **data_payload
                    })
                else:
                    return self._create_result(task, success=False, error="OCR service not available.")
                
            elif task_type == VisionTaskTypes.LOCATE_ORDINAL_ELEMENT:
                collection_hint = payload.get("collection_hint", "items")
                ordinal = payload.get("ordinal", 1)
                direction = payload.get("direction", "top-to-bottom")
                
                prompt = f"""
Analyze this screen image.
Identify all primary elements matching '{collection_hint}' in the main list, ordered in '{direction}' direction.
We want to locate the element at 1-indexed ordinal position {ordinal}.

Be extremely precise. Only count primary items matching the collection type (e.g. main search result cards/videos in the central feed, NOT sidebar recommendations, header links, or unrelated ads).
Identify all visible items of this type in order. For each, note its 1-indexed position.

If the requested ordinal ({ordinal}) is greater than the total visible items in the main list:
Return a JSON object indicating that it is not found and needs scrolling:
{{
  "found": false,
  "index_seen": null,
  "total_visible": <total count of visible elements of this type in the main list>,
  "bbox": null,
  "center": null,
  "needs_scroll": true,
  "label": null
}}
If the requested ordinal ({ordinal}) is within the visible items:
Identify the item at position {ordinal}. Locate its bounding box [ymin, xmin, ymax, xmax] normalized to 0-1000 relative to the image boundaries (0 is top/left, 1000 is bottom/right).
Compute its center coordinate [x, y] in the same 0-1000 normalized space, where x = (xmin + xmax)/2 and y = (ymin + ymax)/2.
Return a JSON object:
{{
  "found": true,
  "index_seen": {ordinal},
  "total_visible": <total count of visible elements of this type in the main list>,
  "bbox": [ymin, xmin, ymax, xmax],
  "center": [center_x, center_y],
  "needs_scroll": false,
  "label": "<the text label or title of this item>"
}}
Return ONLY the raw JSON object, without markdown code fences or other characters.
"""
                response_str = await self.vision_manager.analyze_screen(
                    query=f"Locate element {ordinal} of {collection_hint}",
                    custom_prompt=prompt
                )
                parsed = self._parse_and_validate_vision_json(response_str, "locate")
                
                found = parsed.get("found", False)
                needs_scroll = parsed.get("needs_scroll", False)
                total_visible = parsed.get("total_visible", 0)
                index_seen = parsed.get("index_seen")
                label = parsed.get("label", "")
                bbox = parsed.get("bbox")
                center = parsed.get("center")
                
                win_info = self.vision_manager.window_detector.get_active_window_info()
                region = win_info.get("rect") if win_info else None
                if region and len(region) == 4:
                    win_left, win_top, win_width, win_height = region
                else:
                    win_left, win_top = 0, 0
                    win_width, win_height = pyautogui.size()
                
                abs_bbox = self._to_abs_bbox(bbox, [win_left, win_top, win_width, win_height])
                abs_center = self._to_abs_center(center, [win_left, win_top, win_width, win_height])
                
                data_payload = {
                    "found": found,
                    "index_seen": index_seen,
                    "total_visible": total_visible,
                    "bbox": abs_bbox,
                    "center": abs_center,
                    "needs_scroll": needs_scroll,
                    "label": label
                }
                return self._create_result(task, success=True, result={
                    "task_type": task_type,
                    "data": data_payload,
                    **data_payload
                })

            elif task_type == VisionTaskTypes.COUNT_VISIBLE_ITEMS:
                collection_hint = payload.get("collection_hint", "items")
                
                prompt = f"""
Analyze this screen image.
Count all visible elements matching '{collection_hint}'.
Identify each visible item, assigning a 1-indexed index in standard reading order.
For each item, find its bounding box [ymin, xmin, ymax, xmax] normalized to 0-1000 relative to the image boundaries.
Return a JSON object:
{{
  "count": <total count of visible elements of this type>,
  "items": [
    {{
      "index": 1,
      "label": "<the text label or title of this item>",
      "bbox": [ymin, xmin, ymax, xmax]
    }},
    ...
  ]
}}
Return ONLY the raw JSON object, without markdown code fences or other characters.
"""
                response_str = await self.vision_manager.analyze_screen(
                    query=f"Count visible {collection_hint}",
                    custom_prompt=prompt
                )
                parsed = self._parse_and_validate_vision_json(response_str, "count")
                items = parsed["items"]
                
                win_info = self.vision_manager.window_detector.get_active_window_info()
                region = win_info.get("rect") if win_info else None
                if region and len(region) == 4:
                    win_left, win_top, win_width, win_height = region
                else:
                    win_left, win_top = 0, 0
                    win_width, win_height = pyautogui.size()
                
                for item in items:
                    bbox = item.get("bbox")
                    abs_bbox = self._to_abs_bbox(bbox, [win_left, win_top, win_width, win_height])
                    if abs_bbox:
                        item["bbox"] = abs_bbox
                
                data_payload = {
                    "count": parsed["count"] if parsed["count"] > 0 else len(items),
                    "items": items
                }
                return self._create_result(task, success=True, result={
                    "task_type": task_type,
                    "data": data_payload,
                    **data_payload
                })

            elif task_type == VisionTaskTypes.DIFF_SCREEN_STATE:
                before_hash = payload.get("before_hash")
                before_summary = payload.get("before_summary")
                
                win_info = self.vision_manager.window_detector.get_active_window_info()
                region = win_info.get("rect") if win_info else None
                
                loop = asyncio.get_running_loop()
                img = await loop.run_in_executor(None, self.vision_manager.capturer.capture, region)
                
                from modules.vision.image_optimizer import optimize_image
                base64_image = await loop.run_in_executor(None, optimize_image, img)
                current_hash = self.vision_manager.cache.get_hash(base64_image)
                
                changed = True
                reason = "Unknown"
                
                if before_hash:
                    changed = (current_hash != before_hash)
                    reason = f"Hash comparison: current {current_hash} vs before {before_hash}"
                elif before_summary:
                    prompt = f"""
Analyze this screen image.
The user previously saw a screen described as: "{before_summary}".
Has the screen state changed significantly (e.g., navigated to a new page, opened a menu, started playing a video, loaded new content)?
Answer in JSON format:
{{
  "changed": boolean,
  "reason": "brief description of what changed or why it did not change"
}}
Return ONLY the raw JSON object, without markdown code fences or other characters.
"""
                    response_str = await self.vision_manager.analyze_screen(
                        query="Has the screen state changed?",
                        custom_prompt=prompt
                    )
                    parsed = self._parse_and_validate_vision_json(response_str, "diff")
                    changed = parsed["changed"]
                    reason = parsed["reason"]
                
                data_payload = {
                    "changed": changed,
                    "reason": reason,
                    "current_hash": current_hash
                }
                return self._create_result(task, success=True, result={
                    "task_type": task_type,
                    "data": data_payload,
                    **data_payload
                })
                
            else:
                return self._create_result(
                    task, 
                    success=False, 
                    error=f"VisionAgent does not support task type '{task_type}'"
                )
        except Exception as e:
            logger.exception(f"VisionAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))
