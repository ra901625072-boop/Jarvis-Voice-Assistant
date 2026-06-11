import os
import time
import tempfile
import logging
from typing import Optional, Tuple
import pyautogui
from PIL import Image
import cv2
import numpy as np
import hashlib

logger = logging.getLogger("JARVIS.ScreenObserver")

class ScreenObserver:
    def __init__(self, cache_duration: float = 3.0, change_threshold: float = 5.0):
        self.cache_duration = cache_duration
        self.change_threshold = change_threshold
        self.last_capture_time = 0.0
        self.cached_image_path = None
        self.cached_np_image = None
        self.cached_hash = None
        self._region_temp_files: set = set()  # Track region-specific temp files for cleanup
        logger.info("ScreenObserver initialized.")

    def get_screenshot(self, force_refresh: bool = False, region: Optional[Tuple[int, int, int, int]] = None) -> Tuple[Optional[str], Optional[str], bool]:
        """
        Returns (image_path, screen_hash, has_changed).
        Reuses the cached screenshot if recent, unless force_refresh is True or region is specified.
        """
        current_time = time.time()
        has_changed = False
        
        # We only cache full screen screenshots
        if not force_refresh and region is None:
            if self.cached_image_path and os.path.exists(self.cached_image_path):
                if current_time - self.last_capture_time <= self.cache_duration:
                    return self.cached_image_path, self.cached_hash, False

        # Take new screenshot
        try:
            screenshot = pyautogui.screenshot(region=region)
            
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                temp_path = tmp.name
                
            screenshot.save(temp_path)
            
            if region is None:
                current_np = np.array(screenshot.convert('L'))
                current_hash = hashlib.sha256(current_np.tobytes()).hexdigest()
                
                # Check if hash is exactly the same
                if self.cached_hash == current_hash:
                    has_changed = False
                else:
                    # Hash changed, but let's check if it's a significant visual change
                    if self.cached_np_image is not None and current_np.shape == self.cached_np_image.shape:
                        diff = cv2.absdiff(current_np, self.cached_np_image)
                        mean_diff = np.mean(diff)
                        if mean_diff > self.change_threshold:
                            has_changed = True
                            logger.debug(f"Significant screen change detected (diff: {mean_diff:.2f}).")
                        else:
                            has_changed = False
                    else:
                        has_changed = True
                
                if self.cached_image_path and os.path.exists(self.cached_image_path) and self.cached_image_path != temp_path:
                    try:
                        os.remove(self.cached_image_path)
                    except OSError:
                        pass
                
                self.cached_image_path = temp_path
                self.cached_np_image = current_np
                self.cached_hash = current_hash
                self.last_capture_time = current_time
                
                return self.cached_image_path, self.cached_hash, has_changed
            else:
                # Region-specific capture (not cached). Track it so cleanup() can delete it.
                self._region_temp_files.add(temp_path)
                return temp_path, None, True
                
        except Exception as e:
            logger.error(f"Failed to capture screen: {e}")
            return None, None, False

    def cleanup_region_temps(self):
        """Delete all accumulated region-specific temp screenshot files."""
        for path in list(self._region_temp_files):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        self._region_temp_files.clear()

    def cleanup(self):
        if self.cached_image_path and os.path.exists(self.cached_image_path):
            try:
                os.remove(self.cached_image_path)
            except OSError as e:
                logger.error(f"Failed to cleanup ScreenObserver cache: {e}")
            self.cached_image_path = None
            self.cached_np_image = None
            self.cached_hash = None
            self.last_capture_time = 0.0
        self.cleanup_region_temps()

    def __del__(self):
        self.cleanup()
