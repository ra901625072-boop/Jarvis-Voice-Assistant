import logging
import json
from typing import Dict, List, Optional
from modules.perception.screen_observer import ScreenObserver
from modules.perception import vision

try:
    import pygetwindow as gw
except ImportError:
    pass

logger = logging.getLogger("JARVIS.UIMapper")

UI_MAP_PROMPT = """Extract all interactive UI elements (buttons, links, search bars, inputs, tabs) from this image.
Return a JSON dictionary mapping a short, descriptive name of each element to its 2D bounding box in the format [ymin, xmin, ymax, xmax], scaled to 1000.
Do not include any other text, explanations, or formatting. Just output the JSON object.
Example:
{"Search box": [100, 200, 150, 400], "Login Button": [50, 800, 100, 950]}
"""

class UIMapper:
    def __init__(self, observer: Optional[ScreenObserver] = None):
        self.observer = observer or ScreenObserver()
        self.current_map: Dict[str, List[int]] = {}
        self.last_hash = None
        logger.info("UIMapper initialized.")

    def build_map(self, window_title: Optional[str] = None) -> Dict[str, List[int]]:
        """
        Takes a screenshot (using cache if possible) and builds a UI map using Gemini.
        Only invokes Gemini if the screen hash has changed.
        """
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

        logger.info("Building UI map via Vision...")
        response = vision._generate_from_image(
            image_path=image_path,
            prompt=UI_MAP_PROMPT,
            temperature=0.0,
            max_tokens=2000,
            screen_hash=screen_hash
        )
        
        if not response or str(response).startswith("Error:"):
            return {}

        try:
            clean_resp = response.strip().strip('`').replace('json\n', '').strip()
            ui_map = json.loads(clean_resp)
            if isinstance(ui_map, dict):
                self.current_map = ui_map
                self.last_hash = screen_hash
                logger.info(f"UI map built with {len(ui_map)} elements.")
                return self.current_map
        except Exception as e:
            logger.error(f"Failed to parse UI map from Gemini: {response} - {e}")
            
        return {}

    def get_element(self, element_name: str, window_title: Optional[str] = None) -> Optional[List[int]]:
        """
        Retrieves the bounding box for an element from the current map.
        Rebuilds the map if it's empty or screen has changed.
        """
        # Always call build_map to verify cache freshness
        self.build_map(window_title)
            
        target = element_name.lower()
        for name, bbox in self.current_map.items():
            if target in name.lower():
                return bbox
                
        logger.warning(f"Element '{element_name}' not found in UI map.")
        return None
