import logging

try:
    import pygetwindow as gw
except Exception:
    gw = None

try:
    import pyautogui
except Exception:
    pyautogui = None

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
            if gw:
                return gw.getActiveWindow()
            return None

        # Case-insensitive substring match across all windows
        keyword_lower = title_keyword.lower()
        if gw:
            matches = [w for w in gw.getAllWindows() if keyword_lower in w.title.lower()]
            if matches:
                return matches[0]

        # Windows win32 fallback
        try:
            import win32gui
            found_hwnds = []
            def _enum_handler(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if title and keyword_lower in title.lower():
                        found_hwnds.append((hwnd, title))
            win32gui.EnumWindows(_enum_handler, None)
            if found_hwnds:
                hwnd, title = found_hwnds[0]
                if gw:
                    for w in gw.getAllWindows():
                        if hasattr(w, '_hWnd') and w._hWnd == hwnd:
                            return w
                class WinObj:
                    def __init__(self, h, t):
                        self._hWnd = h
                        self.title = t
                        self.isMinimized = False
                    def activate(self):
                        win32gui.SetForegroundWindow(self._hWnd)
                    def restore(self):
                        import ctypes
                        ctypes.windll.user32.ShowWindow(self._hWnd, 9)
                    def minimize(self):
                        import ctypes
                        ctypes.windll.user32.ShowWindow(self._hWnd, 6)
                    def maximize(self):
                        import ctypes
                        ctypes.windll.user32.ShowWindow(self._hWnd, 3)
                    def close(self):
                        import win32con
                        win32gui.PostMessage(self._hWnd, win32con.WM_CLOSE, 0, 0)
                return WinObj(hwnd, title)
        except Exception:
            pass

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
                try:
                    import ctypes
                    user32 = ctypes.windll.user32
                    user32.AllowSetForegroundWindow(-1)
                    if hasattr(win, '_hWnd') and win._hWnd:
                        user32.ShowWindow(win._hWnd, 9)  # 9 = SW_RESTORE
                        user32.SetForegroundWindow(win._hWnd)
                    if hasattr(win, 'isMinimized') and win.isMinimized:
                        win.restore()
                    win.activate()
                except Exception as act_err:
                    logger.debug(f"win.activate() note: {act_err}")
                logger.info(f"Focused window: {win.title}")
                return True
            return False
        except Exception as e:
            logger.warning(f"Failed to focus window: {e}")
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
