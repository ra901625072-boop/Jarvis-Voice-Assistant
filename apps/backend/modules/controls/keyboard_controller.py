import logging

try:
    import pyautogui
except Exception:
    pyautogui = None

try:
    import keyboard
except Exception:
    keyboard = None

logger = logging.getLogger("JARVIS.Keyboard")

class KeyboardController:
    """
    KeyboardController simulates keyboard input events like typing text, hotkeys, and holding/releasing keys.

    SYSTEM PROMPT:
    Use KeyboardController to type text or send key combinations. Be cautious with typing large payloads or using destructive shortcuts (like 'alt+f4' or 'ctrl+alt+delete').

    SHORT DESCRIPTION:
    Simulates programmatic keyboard input events such as typing, hotkeys, and individual key state controls.

    PROCESS:
    1. Configures pyautogui failsafe flags.
    2. Writes strings character-by-character with configurable delay via pyautogui.
    3. Triggers complex hotkeys and modifier key actions using the keyboard and pyautogui libraries.

    FLOW:
    Caller -> type_text()/press_key()/hold_key() -> pyautogui/keyboard modules -> OS input queue -> Caller
    """
    def __init__(self):
        if pyautogui is not None:
            pyautogui.FAILSAFE = True
        logger.info("KeyboardController initialized.")

    def type_text(self, text: str, interval: float = 0.01):
        """
        Types alphabets, numbers, and special characters literally.
        Falls back to clipboard paste for non-ASCII (Unicode, emoji, CJK) text.
        """
        try:
            # Check if text contains non-ASCII characters that pyautogui.write() can't handle
            if all(ord(c) < 128 for c in text):
                pyautogui.write(text, interval=interval)
            else:
                # Clipboard-paste fallback for Unicode text
                import pyperclip
                original_clipboard = pyperclip.paste()
                pyperclip.copy(text)
                pyautogui.hotkey('ctrl', 'v')
                import time
                time.sleep(0.1)  # Allow paste to complete
                pyperclip.copy(original_clipboard)  # Restore clipboard
            # Security: log character count only, not content (could contain passwords)
            logger.info(f"Typed text ({len(text)} characters)")
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
