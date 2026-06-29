import logging
import mss
from PIL import Image

logger = logging.getLogger("JARVIS.ScreenCapturer")

class ScreenCapturer:
    """
    Handles high-speed desktop capturing using mss.
    """
    def __init__(self):
        self.sct = mss.mss()
        logger.info("ScreenCapturer initialized with shared mss instance.")

    def __del__(self):
        try:
            self.sct.close()
        except Exception:
            pass

    def capture(self, region: tuple = None) -> Image.Image:
        """
        Captures the screen.
        If region is provided as (left, top, width, height), crops to it.
        Otherwise, captures the full primary screen.
        """
        try:
            if region:
                left, top, width, height = region
                if width > 0 and height > 0:
                    monitor = {"left": int(left), "top": int(top), "width": int(width), "height": int(height)}
                    sct_img = self.sct.grab(monitor)
                    return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            # Fallback to full primary monitor
            monitor = self.sct.monitors[1] if len(self.sct.monitors) > 1 else self.sct.monitors[0]
            sct_img = self.sct.grab(monitor)
            return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception as e:
            logger.error(f"Failed to capture screen: {e}. Attempting fullscreen fallback.")
            try:
                # Direct simple fullscreen capture fallback
                monitor = self.sct.monitors[0]
                sct_img = self.sct.grab(monitor)
                return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            except Exception as ex:
                logger.error(f"Critical error capturing screen: {ex}")
                raise ex
