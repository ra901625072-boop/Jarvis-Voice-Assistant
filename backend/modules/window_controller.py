import pygetwindow as gw
import pyautogui
import logging

logger = logging.getLogger("JARVIS.Window")

class WindowController:
    def __init__(self):
        logger.info("WindowController initialized.")
        
    def _get_window(self, title_keyword=None):
        if not title_keyword:
            # Active window
            return gw.getActiveWindow()
            
        windows = gw.getWindowsWithTitle(title_keyword)
        if windows:
            return windows[0]
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
