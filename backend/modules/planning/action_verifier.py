import logging
import time
from typing import Optional
from modules.perception.screen_observer import ScreenObserver
from modules.perception import vision

try:
    import pygetwindow as gw
except ImportError:
    pass

logger = logging.getLogger("JARVIS.ActionVerifier")

class ActionVerifier:
    def __init__(self, observer: Optional[ScreenObserver] = None):
        self.observer = observer or ScreenObserver()
        logger.info("ActionVerifier initialized.")

    def verify_state(self, expected_state: str, window_title: Optional[str] = None) -> bool:
        """
        Takes a fresh screenshot and asks Vision if the expected state is met.
        """
        region = None
        if window_title:
            try:
                windows = gw.getWindowsWithTitle(window_title)
                if windows:
                    win = windows[0]
                    region = (win.left, win.top, win.width, win.height)
            except Exception as e:
                logger.error(f"Error finding window for verification: {e}")
                
        # Force a fresh screenshot to see the outcome of the latest action
        image_path, screen_hash, _ = self.observer.get_screenshot(force_refresh=True, region=region)
        if not image_path:
            logger.error("Failed to capture screenshot for verification.")
            return False

        logger.info(f"Verifying screen state: '{expected_state}'")
        result = vision.verify_condition(image_path, expected_state, screen_hash=screen_hash)
        logger.info(f"Verification result: {result}")
        return result

    def wait_for_state(self, expected_state: str, window_title: Optional[str] = None, timeout: int = 10, interval: int = 2) -> bool:
        """
        Polls verify_state until it returns True or times out.
        Useful for waiting for pages to load or animations to finish.
        """
        start_time = time.time()
        logger.info(f"Waiting for state: '{expected_state}' (timeout={timeout}s)")
        
        while time.time() - start_time < timeout:
            if self.verify_state(expected_state, window_title):
                logger.info(f"State achieved: '{expected_state}'")
                return True
            time.sleep(interval)
            
        logger.warning(f"Timeout waiting for state: '{expected_state}'")
        return False
