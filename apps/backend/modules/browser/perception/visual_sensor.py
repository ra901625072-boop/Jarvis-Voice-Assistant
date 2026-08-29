"""
modules/browser/perception/visual_sensor.py — Visual Sensor for Screenshots & Diagnostic Capture.

Captures high-fidelity viewport screenshots and converts them for multi-modal vision inspection.
"""

import os
import time
import base64
import logging
from typing import Optional, Any

logger = logging.getLogger("JARVIS.Browser.VisualSensor")


class VisualSensor:
    """
    Handles screenshot capture, encoding, and diagnostic image persistence.
    """

    def __init__(self, output_dir: str = "d:/Jarvis/apps/backend/data/browser_snapshots"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    async def capture_screenshot(
        self,
        page: Any,
        filename_prefix: str = "snapshot",
        full_page: bool = False,
    ) -> Optional[str]:
        """
        Captures a screenshot of the current page and returns the absolute file path.
        """
        if not page:
            return None

        try:
            timestamp = int(time.time() * 1000)
            file_path = os.path.join(self.output_dir, f"{filename_prefix}_{timestamp}.png")
            await page.screenshot(path=file_path, full_page=full_page)
            logger.info(f"Captured screenshot to: {file_path}")
            return file_path
        except Exception as e:
            logger.warning(f"Failed to capture screenshot: {e}")
            return None

    async def capture_base64(self, page: Any, full_page: bool = False) -> Optional[str]:
        """
        Captures screenshot directly as a base64 encoded string for vision model input.
        """
        if not page:
            return None

        try:
            image_bytes = await page.screenshot(full_page=full_page)
            return base64.b64encode(image_bytes).decode("utf-8")
        except Exception as e:
            logger.warning(f"Failed to capture base64 screenshot: {e}")
            return None
