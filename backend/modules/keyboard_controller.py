import pyautogui
import keyboard
import logging
import time

logger = logging.getLogger("JARVIS.Keyboard")

class KeyboardController:
    def __init__(self):
        # Fail-safe to allow user to abort by moving mouse to corner
        pyautogui.FAILSAFE = True
        logger.info("KeyboardController initialized.")

    def type_text(self, text: str, interval: float = 0.01):
        """
        Types alphabets, numbers, and special characters literally.
        """
        try:
            pyautogui.write(text, interval=interval)
            logger.info(f"Typed text: {text}")
            return True
        except Exception as e:
            logger.error(f"Error typing text: {e}")
            return False

    def press_key(self, keys: str):
        """
        Presses a single key or a combination string (e.g., 'enter', 'ctrl+c', 'win+d')
        """
        try:
            keyboard.send(keys)
            logger.info(f"Pressed key(s): {keys}")
            return True
        except Exception as e:
            logger.error(f"Error pressing keys: {e}")
            return False
            
    def hotkey(self, *keys):
        """
        Presses a combination of keys in sequence (e.g., hotkey('ctrl', 'shift', 'esc'))
        """
        try:
            pyautogui.hotkey(*keys)
            logger.info(f"Executed hotkey: {'+'.join(keys)}")
            return True
        except Exception as e:
            logger.error(f"Error executing hotkey: {e}")
            return False

    def hold_key(self, key: str):
        """
        Holds down a specific key (e.g., 'shift', 'ctrl', 'a')
        """
        try:
            pyautogui.keyDown(key)
            logger.info(f"Holding down key: {key}")
            return True
        except Exception as e:
            logger.error(f"Error holding key: {e}")
            return False

    def release_key(self, key: str):
        """
        Releases a previously held key
        """
        try:
            pyautogui.keyUp(key)
            logger.info(f"Released key: {key}")
            return True
        except Exception as e:
            logger.error(f"Error releasing key: {e}")
            return False
