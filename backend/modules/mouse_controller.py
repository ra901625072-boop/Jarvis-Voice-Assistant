import pyautogui
import logging
import time

logger = logging.getLogger("JARVIS.Mouse")

class MouseController:
    def __init__(self):
        pyautogui.FAILSAFE = True
        logger.info("MouseController initialized.")

    def move(self, x: int, y: int, duration: float = 0.5):
        """Moves the mouse to specific coordinates."""
        try:
            pyautogui.moveTo(x, y, duration=duration)
            logger.info(f"Moved mouse to ({x}, {y})")
            return True
        except Exception as e:
            logger.error(f"Error moving mouse: {e}")
            return False

    def click(self, x: int = None, y: int = None):
        """Left clicks at current location or specified coordinates."""
        try:
            if x is not None and y is not None:
                pyautogui.click(x=x, y=y)
                logger.info(f"Clicked at ({x}, {y})")
            else:
                pyautogui.click()
                logger.info("Clicked at current location")
            return True
        except Exception as e:
            logger.error(f"Error clicking mouse: {e}")
            return False

    def double_click(self, x: int = None, y: int = None):
        """Double left clicks at current location or specified coordinates."""
        try:
            if x is not None and y is not None:
                pyautogui.doubleClick(x=x, y=y)
                logger.info(f"Double-clicked at ({x}, {y})")
            else:
                pyautogui.doubleClick()
                logger.info("Double-clicked at current location")
            return True
        except Exception as e:
            logger.error(f"Error double clicking mouse: {e}")
            return False

    def right_click(self, x: int = None, y: int = None):
        """Right clicks at current location or specified coordinates."""
        try:
            if x is not None and y is not None:
                pyautogui.rightClick(x=x, y=y)
                logger.info(f"Right-clicked at ({x}, {y})")
            else:
                pyautogui.rightClick()
                logger.info("Right-clicked at current location")
            return True
        except Exception as e:
            logger.error(f"Error right clicking mouse: {e}")
            return False

    def scroll(self, amount: int):
        """
        Scrolls the mouse wheel. 
        Positive amount scrolls up, negative amount scrolls down.
        """
        try:
            pyautogui.scroll(amount)
            logger.info(f"Scrolled mouse by {amount}")
            return True
        except Exception as e:
            logger.error(f"Error scrolling mouse: {e}")
            return False

    def get_position(self):
        """Returns the current (x, y) coordinates of the mouse."""
        try:
            x, y = pyautogui.position()
            return x, y
        except Exception as e:
            logger.error(f"Error getting mouse position: {e}")
            return None, None
