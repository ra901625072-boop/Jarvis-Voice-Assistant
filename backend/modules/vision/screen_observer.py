import os
import time
import tempfile
import logging
import threading
import zlib
from typing import Optional, Tuple, List, Callable
from PIL import Image
import cv2
import numpy as np
import mss

logger = logging.getLogger("JARVIS.ScreenObserver")

class ScreenObserver:
    """
    ScreenObserver captures desktop screenshots, calculates hashes, and evaluates visual state differences.
    Redesigned to run a low-latency background daemon thread via mss and register visual event handlers.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ScreenObserver, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, cache_duration: float = 3.0, change_threshold: float = 5.0):
        if getattr(self, "_initialized", False):
            return
        self.cache_duration = cache_duration
        self.change_threshold = change_threshold
        self.last_capture_time = 0.0
        self.cached_image_path = None
        self.cached_np_image = None
        self.cached_hash = None
        self.cached_pil_image = None
        self._region_temp_files: set = set()
        self.interval = 0.2
        
        # Background observation daemon state
        self._observers: List[Callable[[Image.Image, str], None]] = []
        self._daemon_thread = None
        self._stop_event = threading.Event()
        self._daemon_lock = threading.Lock()
        
        self._initialized = True
        logger.info("ScreenObserver singleton initialized.")

    def start_observer(self, interval: float = 0.2):
        """Starts the background observation loop."""
        with self._daemon_lock:
            if self._daemon_thread and self._daemon_thread.is_alive():
                return
            self.interval = interval
            self._stop_event.clear()
            self._daemon_thread = threading.Thread(
                target=self._observation_loop, 
                args=(interval,), 
                name="JarvisScreenObserverDaemon", 
                daemon=True
            )
            self._daemon_thread.start()
            logger.info("ScreenObserver background observation daemon started.")

    def stop_observer(self):
        """Stops the background observation loop."""
        with self._daemon_lock:
            if self._daemon_thread:
                self._stop_event.set()
                self._daemon_thread.join(timeout=1.0)
                self._daemon_thread = None
                logger.info("ScreenObserver background observation daemon stopped.")

    def register_callback(self, callback: Callable[[Image.Image, str], None]):
        """Registers a callback function to be executed when the screen changes."""
        if callback not in self._observers:
            self._observers.append(callback)
            logger.debug("Registered a new screen change observer callback.")

    def unregister_callback(self, callback: Callable[[Image.Image, str], None]):
        """Unregisters a callback function."""
        if callback in self._observers:
            self._observers.remove(callback)
            logger.debug("Unregistered screen change observer callback.")

    def _observation_loop(self, interval: Optional[float] = None):
        """Background loop using mss to capture screen and detect differences."""
        logger.info("Starting observation loop in ScreenObserver background thread.")
        if interval is not None:
            self.interval = interval
        with mss.mss() as sct:
            while not self._stop_event.is_set():
                try:
                    # Capturing display 1 (primary monitor)
                    monitor = sct.monitors[1]
                    sct_img = sct.grab(monitor)
                    
                    # Convert to PIL Image
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    
                    # Convert to grayscale NumPy array for comparison
                    current_np = np.array(img.convert('L'))
                    # Use fast Adler-32 checksum instead of SHA256 (same detection quality, ~10x faster)
                    current_hash = zlib.adler32(current_np.tobytes()) & 0xffffffff
                    
                    has_changed = False
                    
                    if self.cached_hash != current_hash:
                        if self.cached_np_image is not None and current_np.shape == self.cached_np_image.shape:
                            diff = cv2.absdiff(current_np, self.cached_np_image)
                            mean_diff = np.mean(diff)
                            if mean_diff > self.change_threshold:
                                has_changed = True
                        else:
                            has_changed = True

                    if has_changed:
                        self.cached_np_image = current_np
                        self.cached_hash = current_hash
                        self.cached_pil_image = img
                        self.last_capture_time = time.time()
                        
                        # Trigger callbacks
                        for callback in list(self._observers):
                            try:
                                callback(img, current_hash)
                            except Exception as e:
                                logger.error(f"Error in ScreenObserver callback: {e}")

                except Exception as e:
                    logger.error(f"Error in background ScreenObserver loop: {e}")
                    
                time.sleep(self.interval)

    def set_frequency(self, state_str: str):
        """Adjust background thread's sleep time based on the active agent state."""
        state_str = str(state_str).upper()
        if state_str in ("IDLE", "COMPLETED", "FAILED"):
            new_interval = 0.5
        elif state_str in ("EXECUTING", "PLANNING", "REPLANNING"):
            new_interval = 0.1
        elif state_str in ("VERIFYING", "RECOVERING"):
            new_interval = 0.05
        else:
            new_interval = 0.2
            
        if self.interval != new_interval:
            logger.info(f"ScreenObserver interval changing: {self.interval}s -> {new_interval}s (State: {state_str})")
            self.interval = new_interval

    def get_screenshot(self, force_refresh: bool = False, region: Optional[Tuple[int, int, int, int]] = None) -> Tuple[Optional[str], Optional[str], bool]:
        """
        Returns (image_path, screen_hash, has_changed).
        Reuses the cached screenshot if recent, unless force_refresh is True or region is specified.
        """
        current_time = time.time()
        has_changed = False
        
        is_bg_active = self._daemon_thread is not None and self._daemon_thread.is_alive()
        
        if not force_refresh and region is None:
            if is_bg_active and self.cached_pil_image:
                # Ensure the cached image has an active temp file path
                if not self.cached_image_path or not os.path.exists(self.cached_image_path):
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        self.cached_image_path = tmp.name
                    self.cached_pil_image.save(self.cached_image_path)
                return self.cached_image_path, self.cached_hash, False
                
            if self.cached_image_path and os.path.exists(self.cached_image_path):
                if current_time - self.last_capture_time <= self.cache_duration:
                    return self.cached_image_path, self.cached_hash, False

        # Take new screenshot
        try:
            if region is None:
                with mss.mss() as sct:
                    monitor = sct.monitors[1]
                    sct_img = sct.grab(monitor)
                    screenshot = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            else:
                with mss.mss() as sct:
                    left, top, width, height = region
                    monitor = {"left": left, "top": top, "width": width, "height": height}
                    sct_img = sct.grab(monitor)
                    screenshot = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

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
                    if self.cached_np_image is not None and current_np.shape == self.cached_np_image.shape:
                        diff = cv2.absdiff(current_np, self.cached_np_image)
                        mean_diff = np.mean(diff)
                        if mean_diff > self.change_threshold:
                            has_changed = True
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
                self.cached_pil_image = screenshot
                self.last_capture_time = current_time
                
                return self.cached_image_path, self.cached_hash, has_changed
            else:
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
        self.stop_observer()
        if self.cached_image_path and os.path.exists(self.cached_image_path):
            try:
                os.remove(self.cached_image_path)
            except OSError as e:
                logger.error(f"Failed to cleanup ScreenObserver cache: {e}")
            self.cached_image_path = None
            self.cached_np_image = None
            self.cached_hash = None
            self.cached_pil_image = None
            self.last_capture_time = 0.0
        self.cleanup_region_temps()

    def __del__(self):
        self.cleanup()
