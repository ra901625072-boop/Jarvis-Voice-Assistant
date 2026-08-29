import logging
import json
import ctypes
from typing import Dict, List, Optional
from modules.vision.screen_observer import ScreenObserver
from modules.vision import vision

try:
    import pygetwindow as gw
    import comtypes.client
    _NATIVE_SUPPORT = True
except ImportError:
    _NATIVE_SUPPORT = False

logger = logging.getLogger("JARVIS.UIMapper")

UI_MAP_PROMPT = """Extract all interactive UI elements (buttons, links, search bars, inputs, tabs) from this image.
Return a JSON dictionary mapping a short, descriptive name of each element to its 2D bounding box in the format [ymin, xmin, ymax, xmax], scaled to 1000.
Do not include any other text, explanations, or formatting. Just output the JSON object.
Example:
{"Search box": [100, 200, 150, 400], "Login Button": [50, 800, 100, 950]}
"""

def clean_and_parse_json(text: str) -> Optional[dict]:
    """
    Cleans markdown code fences, trailing commas, and minor syntax faults from model JSON output.
    """
    if not text:
        return None
    import re
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end+1]

    cleaned = re.sub(r",\s*([\}\]])", r"\1", cleaned)

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        try:
            lines = cleaned.splitlines()
            if len(lines) > 2:
                repaired = "\n".join(lines[:-1])
                repaired = re.sub(r",\s*$", "", repaired).strip()
                open_braces = repaired.count("{") - repaired.count("}")
                repaired += "}" * max(0, open_braces)
                data = json.loads(repaired)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return None

class UIMapper:
    """
    UIMapper extracts positions of interactive interface elements from screenshots.
    Optimized to query Windows UI Automation COM APIs for sub-50ms native extraction,
    with a fallback to Gemini Vision API.
    """
    def __init__(self, observer: Optional[ScreenObserver] = None):
        self.observer = observer or ScreenObserver()
        self.current_map: Dict[str, List[int]] = {}
        self.last_hash = None
        logger.info("UIMapper initialized.")

    def get_native_elements(self, window_title: Optional[str] = None) -> Dict[str, List[int]]:
        """
        Attempts to query Windows UI Automation COM API to pull coordinate rectangles of interactive elements
        relative to the target window. Scales bounds to [ymin, xmin, ymax, xmax] scaled to 1000.
        """
        if not _NATIVE_SUPPORT:
            return {}

        elements = {}
        try:
            import comtypes.client
            mod = comtypes.client.GetModule("UIAutomationCore.dll")
            uia = comtypes.client.CreateObject(mod.CUIAutomation, interface=mod.IUIAutomation)

            hwnd = None
            win_rect = None

            if window_title:
                windows = gw.getWindowsWithTitle(window_title)
                if windows:
                    win = windows[0]
                    hwnd = win._hWnd
                    win_rect = (win.left, win.top, win.width, win.height)
            else:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                if hwnd:
                    rect = ctypes.wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    win_rect = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)

            if not hwnd or not win_rect:
                return {}

            win_left, win_top, win_width, win_height = win_rect
            if win_width <= 0 or win_height <= 0:
                return {}

            window_element = uia.ElementFromHandle(hwnd)
            if not window_element:
                return {}

            # Search TreeScope_Descendants (4) for common interactive element control types:
            # Button: 50000, Edit: 50004, Hyperlink: 50005, TabItem: 50019, CheckBox: 50002, ComboBox: 50003, Text: 50020
            control_types = [50000, 50004, 50005, 50019, 50002, 50003, 50020]

            for ctype in control_types:
                cond = uia.CreatePropertyCondition(30003, ctype) # UIA_ControlTypePropertyId = 30003
                found = window_element.FindAll(4, cond) # TreeScope_Descendants = 4
                if found:
                    for i in range(found.Length):
                        el = found.GetElement(i)
                        name = el.CurrentName
                        if name and name.strip():
                            rect = el.CurrentBoundingRectangle
                            el_left, el_top, el_right, el_bottom = rect.left, rect.top, rect.right, rect.bottom

                            ymin = max(0, min(1000, int((el_top - win_top) / win_height * 1000)))
                            xmin = max(0, min(1000, int((el_left - win_left) / win_width * 1000)))
                            ymax = max(0, min(1000, int((el_bottom - win_top) / win_height * 1000)))
                            xmax = max(0, min(1000, int((el_right - win_left) / win_width * 1000)))

                            if ymax > ymin and xmax > xmin:
                                elements[name.strip()] = [ymin, xmin, ymax, xmax]

            logger.info(f"Natively extracted {len(elements)} UI elements using Windows UI Automation.")
        except Exception as e:
            logger.debug(f"Native UI Automation extraction failed/bypassed: {e}")
        return elements

    def build_map(self, window_title: Optional[str] = None) -> Dict[str, List[int]]:
        """
        Takes a screenshot (using cache if possible) and builds a UI map.
        Uses native Windows UI Automation if available, falling back to Gemini Vision.
        """
        # 1. First attempt native fast path (<50ms)
        native_map = self.get_native_elements(window_title)
        if native_map:
            self.current_map = native_map
            return self.current_map

        # 2. Fallback to Gemini Vision API (slow path)
        region = None
        if window_title:
            try:
                windows = gw.getWindowsWithTitle(window_title)
                if windows:
                    win = windows[0]
                    region = (win.left, win.top, win.width, win.height)
            except Exception as e:
                logger.error(f"Error finding window for UI mapping: {e}")

        image_path, screen_hash, has_changed = self.observer.get_screenshot(region=region)
        
        if not image_path:
            logger.error("Failed to capture screenshot for UI mapping.")
            return {}

        if screen_hash and screen_hash == self.last_hash and self.current_map:
            logger.debug("Screen hash unchanged, returning cached UI map.")
            return self.current_map

        logger.info("Building UI map via Gemini Vision API (fallback)...")
        response = vision._generate_from_image(
            image_path=image_path,
            prompt=UI_MAP_PROMPT,
            temperature=0.0,
            max_tokens=1000,
            screen_hash=screen_hash
        )
        
        if not response or str(response).startswith("Error:"):
            return {}

        ui_map = clean_and_parse_json(response)
        if ui_map:
            self.current_map = ui_map
            self.last_hash = screen_hash
            logger.info(f"UI map built with {len(ui_map)} elements via Vision API.")
            return self.current_map

        logger.error(f"Failed to parse UI map from Gemini: {response}")
        return {}

    def get_element(self, element_name: str, window_title: Optional[str] = None) -> Optional[List[int]]:
        """
        Retrieves the bounding box for an element from the current map.
        Rebuilds the map if it's empty or screen has changed.
        """
        if not element_name:
            return None
            
        self.build_map(window_title)
            
        target = str(element_name).lower()
        for name, bbox in self.current_map.items():
            if name and isinstance(name, str) and target in name.lower():
                if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                    return list(bbox)
                
        logger.warning(f"Element '{element_name}' not found in UI map.")
        return None

    def find_element(self, element_name: str, window_title: Optional[str] = None) -> Optional[List[int]]:
        """
        Alias for get_element for compatibility with VisionAgent and external callers.
        """
        return self.get_element(element_name, window_title)

