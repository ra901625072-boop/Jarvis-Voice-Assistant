import pygetwindow as gw
import pyautogui
import logging

logger = logging.getLogger("JARVIS.Window")

class WindowController:
    """
    WindowController handles window actions including minimize, maximize, restore, close, and focus focus.

    SYSTEM PROMPT:
    Use WindowController to manipulate host OS graphical windows (minimize, maximize, focus, close). Verify window titles before performing operations, and ask for user confirmation before closing active windows.

    SHORT DESCRIPTION:
    Manages host OS window operations, layouts, states, and focus settings using PyGetWindow and PyAutoGUI.

    PROCESS:
    1. Finds target window matching a title keyword, defaulting to the currently active window if no keyword is provided.
    2. Invokes pygetwindow window control methods (minimize, maximize, restore, close, activate).
    3. Simulates system-wide hotkeys (e.g., win+d, alt+tab) using pyautogui.

    FLOW:
    Caller -> focus_window()/close_window() -> _get_window() -> pygetwindow API calls -> OS Window Manager -> Caller
    """
    def __init__(self):
        logger.info("WindowController initialized.")
        
    def _get_window(self, title_keyword=None):
        if not title_keyword:
            # Active window
            return gw.getActiveWindow()

        # Case-insensitive substring match across all windows
        keyword_lower = title_keyword.lower()
        matches = [w for w in gw.getAllWindows() if keyword_lower in w.title.lower()]
        if matches:
            return matches[0]
        return None

    def minimize_window(self, title_keyword=None):
        try:
            win = self._get_window(title_keyword)
            if win:
                win.minimize()
                logger.info(f"Minimized window: {win.title}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to minimize window: {e}")
            return False

    def maximize_window(self, title_keyword=None):
        try:
            win = self._get_window(title_keyword)
            if win:
                win.maximize()
                logger.info(f"Maximized window: {win.title}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to maximize window: {e}")
            return False

    def restore_window(self, title_keyword=None):
        try:
            win = self._get_window(title_keyword)
            if win:
                win.restore()
                logger.info(f"Restored window: {win.title}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to restore window: {e}")
            return False

    def close_window(self, title_keyword=None):
        try:
            win = self._get_window(title_keyword)
            if win:
                win.close()
                logger.info(f"Closed window: {win.title}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to close window: {e}")
            return False

    def focus_window(self, title_keyword=None):
        try:
            win = self._get_window(title_keyword)
            if win:
                if win.isMinimized:
                    win.restore()
                win.activate()
                logger.info(f"Focused window: {win.title}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to focus window: {e}")
            return False

    def switch_window(self):
        try:
            pyautogui.hotkey('alt', 'tab')
            logger.info("Switched window via alt-tab.")
            return True
        except Exception as e:
            logger.error(f"Failed to switch window: {e}")
            return False

    def show_desktop(self):
        try:
            pyautogui.hotkey('win', 'd')
            logger.info("Showed desktop.")
            return True
        except Exception as e:
            logger.error(f"Failed to show desktop: {e}")
            return False
