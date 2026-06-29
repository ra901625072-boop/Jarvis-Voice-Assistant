import logging
import psutil

try:
    import win32gui
    import win32process
    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False

logger = logging.getLogger("JARVIS.WindowDetector")

class WindowDetector:
    """
    WindowDetector queries the OS active foreground window details.
    Uses win32gui and psutil on Windows displays.
    """
    def __init__(self):
        logger.info(f"WindowDetector initialized (win32 API available: {_WIN32_AVAILABLE}).")

    def get_active_window_info(self) -> dict:
        """
        Returns active window metadata:
        {
            "active_app": "chrome.exe",
            "window_title": "Google - Chrome",
            "rect": (left, top, width, height)
        }
        """
        default_info = {
            "active_app": "unknown",
            "window_title": "unknown",
            "rect": None
        }
        
        if not _WIN32_AVAILABLE:
            logger.warning("win32 libraries not available. Cannot detect active window.")
            return default_info
            
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return default_info
                
            title = win32gui.GetWindowText(hwnd)
            
            # Bounding box coords (left, top, right, bottom)
            rect = win32gui.GetWindowRect(hwnd)
            left, top, right, bottom = rect
            width = right - left
            height = bottom - top
            
            process_name = "unknown"
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid > 0:
                    proc = psutil.Process(pid)
                    process_name = proc.name()
            except Exception as e:
                logger.debug(f"Failed to fetch PID or process name: {e}")
                
            return {
                "active_app": process_name,
                "window_title": title if title else "Untitled Window",
                "rect": (left, top, width, height)
            }
        except Exception as e:
            logger.error(f"Error checking active window: {e}")
            return default_info
