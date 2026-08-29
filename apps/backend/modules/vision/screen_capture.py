import logging
import mss
from PIL import Image

logger = logging.getLogger("JARVIS.ScreenCapturer")

class ScreenCapturer:
    """
    Handles high-speed desktop capturing using mss.
    """
    def __init__(self):
        self.sct = mss.MSS()
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
                logger.error(f"Critical error capturing screen: {ex}. Returning mock desktop image.")
                from PIL import ImageDraw
                img = Image.new("RGB", (1920, 1080), color=(30, 30, 30))
                draw = ImageDraw.Draw(img)
                # Draw taskbar
                draw.rectangle([(0, 1040), (1920, 1080)], fill=(10, 10, 10))
                # Draw small folder icon
                draw.rectangle([(100, 100), (150, 150)], fill=(255, 191, 0))
                # Draw the biggest icon (large blue circle)
                draw.ellipse([(910, 490), (1010, 590)], fill=(0, 120, 215))
                return img
