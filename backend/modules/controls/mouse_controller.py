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



logger = logging.getLogger("JARVIS.Mouse")

class MouseController:
    def __init__(self):
        pyautogui.FAILSAFE = True
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
                    
            screenshot = pyautogui.screenshot(region=target_region)
            if save_path:
                screenshot.save(save_path)
            return screenshot
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return None

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
