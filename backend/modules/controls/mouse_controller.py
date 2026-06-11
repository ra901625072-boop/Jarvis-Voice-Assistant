import pyautogui
import logging
import time
import os
import tempfile
from typing import Tuple, Optional, Callable
from PIL import Image

try:
    from screeninfo import get_monitors
    import pygetwindow as gw
except ImportError:
    pass

try:
    import easyocr
except ImportError:
    easyocr = None

from modules.perception import vision
from modules.perception.screen_observer import ScreenObserver

logger = logging.getLogger("JARVIS.Mouse")

class MouseController:
    def __init__(self, observer: Optional[ScreenObserver] = None, ui_mapper=None):
        pyautogui.FAILSAFE = True
        self.reader = easyocr.Reader(['en']) if easyocr else None
        self.observer = observer or ScreenObserver()
        self.ui_mapper = ui_mapper
        logger.info("MouseController initialized.")

    def _safe_execute(self, action_func: Callable, retries: int = 3, delay: float = 0.5) -> bool:
        for attempt in range(retries):
            try:
                action_func()
                return True
            except pyautogui.FailSafeException:
                logger.warning("PyAutoGUI FailSafe triggered. Aborting action.")
                return False
            except Exception as e:
                logger.warning(f"Action failed (attempt {attempt+1}/{retries}): {e}")
                time.sleep(delay)
        logger.error("Action failed after maximum retries.")
        return False

    def _is_safe_coordinate(self, x: int, y: int) -> bool:
        try:
            for m in get_monitors():
                if m.x <= x < m.x + m.width and m.y <= y < m.y + m.height:
                    return True
            return False
        except Exception:
            return True

    def get_window_region(self, window_title: str) -> Optional[Tuple[int, int, int, int]]:
        try:
            windows = gw.getWindowsWithTitle(window_title)
            if windows:
                win = windows[0]
                return (win.left, win.top, win.width, win.height)
            logger.warning(f"Window not found: {window_title}")
            return None
        except Exception as e:
            logger.error(f"Error finding window region: {e}")
            return None

    def move(self, x: int, y: int, duration: float = 0.5) -> bool:
        if not self._is_safe_coordinate(x, y):
            logger.error(f"Coordinates ({x}, {y}) are out of bounds.")
            return False
        def action():
            pyautogui.moveTo(x, y, duration=duration)
            logger.info(f"Moved mouse to ({x}, {y})")
        return self._safe_execute(action)

    def click(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        if x is not None and y is not None and not self._is_safe_coordinate(x, y):
            logger.error(f"Coordinates ({x}, {y}) are out of bounds.")
            return False
        def action():
            if x is not None and y is not None:
                pyautogui.click(x=x, y=y)
                logger.info(f"Clicked at ({x}, {y})")
            else:
                pyautogui.click()
                logger.info("Clicked at current location")
        return self._safe_execute(action)

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        if x is not None and y is not None and not self._is_safe_coordinate(x, y):
            return False
        def action():
            if x is not None and y is not None:
                pyautogui.doubleClick(x=x, y=y)
            else:
                pyautogui.doubleClick()
        return self._safe_execute(action)

    def right_click(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        if x is not None and y is not None and not self._is_safe_coordinate(x, y):
            return False
        def action():
            if x is not None and y is not None:
                pyautogui.rightClick(x=x, y=y)
            else:
                pyautogui.rightClick()
        return self._safe_execute(action)

    def scroll(self, amount: int) -> bool:
        def action():
            pyautogui.scroll(amount)
        return self._safe_execute(action)

    def get_position(self) -> Tuple[Optional[int], Optional[int]]:
        try:
            x, y = pyautogui.position()
            return x, y
        except Exception:
            return None, None

    def take_screenshot(self, region: Optional[Tuple[int, int, int, int]] = None, save_path: Optional[str] = None, window_title: Optional[str] = None) -> Optional[Image.Image]:
        try:
            target_region = region
            if window_title:
                win_region = self.get_window_region(window_title)
                if win_region:
                    target_region = win_region
                else:
                    return None
                    
            if hasattr(self, 'observer') and self.observer:
                cached_path, _, _ = self.observer.get_screenshot()
                if cached_path:
                    img = Image.open(cached_path)
                    if target_region:
                        left, top, width, height = target_region
                        img = img.crop((left, top, left + width, top + height))
                    if save_path:
                        img.save(save_path)
                    return img
                    
            screenshot = pyautogui.screenshot(region=target_region)
            if save_path:
                screenshot.save(save_path)
            return screenshot
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return None

    def find_image(self, image_path: str, confidence: float = 0.8, window_title: Optional[str] = None) -> Optional[Tuple[int, int]]:
        if not os.path.exists(image_path):
            return None
        try:
            target_region = None
            if window_title:
                target_region = self.get_window_region(window_title)
                if not target_region:
                    return None
            location = pyautogui.locateCenterOnScreen(image_path, confidence=confidence, region=target_region)
            if location:
                return location.x, location.y
            return None
        except Exception:
            return None

    def click_image(self, image_path: str, confidence: float = 0.8, retries: int = 3, window_title: Optional[str] = None) -> bool:
        for _ in range(retries):
            location = self.find_image(image_path, confidence=confidence, window_title=window_title)
            if location:
                return self.click(location[0], location[1])
            time.sleep(1)
        return False

    def find_text(self, text: str, case_sensitive: bool = False, window_title: Optional[str] = None) -> Optional[Tuple[int, int]]:
        if not self.reader:
            return None
        try:
            region_offset_x = 0
            region_offset_y = 0
            target_region = None
            if window_title:
                target_region = self.get_window_region(window_title)
                if not target_region:
                    return None
                region_offset_x, region_offset_y = target_region[0], target_region[1]

            screenshot = self.take_screenshot(region=target_region)
            if not screenshot:
                return None
            
            import numpy as np
            img_np = np.array(screenshot)
            results = self.reader.readtext(img_np)
            
            target_text = text if case_sensitive else text.lower()
            
            for (bbox, detected_text, prob) in results:
                check_text = detected_text if case_sensitive else detected_text.lower()
                if target_text in check_text:
                    top_left = bbox[0]
                    bottom_right = bbox[2]
                    center_x = int((top_left[0] + bottom_right[0]) / 2)
                    center_y = int((top_left[1] + bottom_right[1]) / 2)
                    return center_x + region_offset_x, center_y + region_offset_y
            return None
        except Exception:
            return None

    def click_text(self, text: str, case_sensitive: bool = False, retries: int = 3, window_title: Optional[str] = None) -> bool:
        for _ in range(retries):
            location = self.find_text(text, case_sensitive=case_sensitive, window_title=window_title)
            if location:
                return self.click(location[0], location[1])
            time.sleep(1)
        return False

    def find_element_hierarchical(self, element_description: str, window_title: Optional[str] = None) -> Optional[Tuple[int, int]]:
        """
        Hierarchical Vision Routing:
        1. UI Map Cache
        2. OCR
        3. OpenCV Image Match
        4. Gemini Vision (Fallback)
        """
        region_offset_x = 0
        region_offset_y = 0
        target_region = None
        
        if window_title:
            target_region = self.get_window_region(window_title)
            if not target_region:
                return None
            region_offset_x, region_offset_y = target_region[0], target_region[1]

        # 1. UI Map Cache
        if self.ui_mapper:
            box = self.ui_mapper.get_element(element_description, window_title)
            if box:
                logger.info(f"Found '{element_description}' via UI Map cache.")
                return self._box_to_center(box, target_region, region_offset_x, region_offset_y)

        # 2. OCR (If description looks like text)
        if self.reader and len(element_description.split()) <= 3:
            loc = self.find_text(element_description, case_sensitive=False, window_title=window_title)
            if loc:
                logger.info(f"Found '{element_description}' via OCR.")
                return loc

        # 3. OpenCV (If we have a templates directory matching the description)
        template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", f"{element_description.lower().replace(' ', '_')}.png")
        if os.path.exists(template_path):
            loc = self.find_image(template_path, confidence=0.8, window_title=window_title)
            if loc:
                logger.info(f"Found '{element_description}' via OpenCV template.")
                return loc

        # 4. Gemini Vision Fallback
        logger.info(f"Falling back to Gemini Vision to locate '{element_description}'.")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            save_path = tmp.name

        # Get the hash BEFORE taking the custom screenshot so both
        # refer to the same screen frame (prevents wrong cache key).
        _, screen_hash, _ = self.observer.get_screenshot()

        screenshot = self.take_screenshot(region=target_region, save_path=save_path)
        if not screenshot:
            if os.path.exists(save_path):
                os.remove(save_path)
            return None

        box = vision.find_element_bounding_box(save_path, element_description, screen_hash=screen_hash)
        if os.path.exists(save_path):
            os.remove(save_path)

        if box:
            return self._box_to_center(box, target_region, region_offset_x, region_offset_y)

        return None

    def _box_to_center(self, box, target_region, region_offset_x, region_offset_y):
        screenshot = self.take_screenshot(region=target_region)
        if not screenshot:
            return None
        img_width, img_height = screenshot.size
            
        ymin, xmin, ymax, xmax = box
        pixel_xmin = int((xmin / 1000) * img_width)
        pixel_ymin = int((ymin / 1000) * img_height)
        pixel_xmax = int((xmax / 1000) * img_width)
        pixel_ymax = int((ymax / 1000) * img_height)
        
        center_x = int((pixel_xmin + pixel_xmax) / 2)
        center_y = int((pixel_ymin + pixel_ymax) / 2)
        
        return center_x + region_offset_x, center_y + region_offset_y

    def find_element_vision(self, element_description: str, window_title: Optional[str] = None) -> Optional[Tuple[int, int]]:
        # Keeping alias for backward compatibility
        return self.find_element_hierarchical(element_description, window_title)

    def click_element_vision(self, element_description: str, window_title: Optional[str] = None, retries: int = 3) -> bool:
        for attempt in range(retries):
            location = self.find_element_vision(element_description, window_title)
            if location:
                return self.click(location[0], location[1])
            time.sleep(1)
        return False

    def drag_to(self, x: int, y: int, duration: float = 0.5) -> bool:
        if not self._is_safe_coordinate(x, y):
            return False
        def action():
            pyautogui.dragTo(x, y, duration=duration)
        return self._safe_execute(action)

    def drag_rel(self, xOffset: int, yOffset: int, duration: float = 0.5) -> bool:
        def action():
            pyautogui.dragRel(xOffset, yOffset, duration=duration)
        return self._safe_execute(action)

    def mouse_down(self, button: str = 'left') -> bool:
        def action():
            pyautogui.mouseDown(button=button)
        return self._safe_execute(action)

    def mouse_up(self, button: str = 'left') -> bool:
        def action():
            pyautogui.mouseUp(button=button)
        return self._safe_execute(action)
