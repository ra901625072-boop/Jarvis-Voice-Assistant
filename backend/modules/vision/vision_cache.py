import hashlib
import time
import logging
import threading

logger = logging.getLogger("JARVIS.VisionCache")

class VisionCache:
    """
    Thread-safe in-memory cache mapped from screenshot hash to analyzed response text.
    Acts as the session visual context and prevents duplicate model calls.
    """
    def __init__(self, ttl: float = 30.0):
        self.ttl = ttl
        self._cache = {}  # dict of {hash: (result_text, timestamp)}
        self._last_screenshot_hash = None
        self._last_vision_analysis = None
        self._last_timestamp = 0.0
        self._lock = threading.Lock()

    def get_hash(self, base64_image: str) -> str:
        """
        Generates SHA-256 hash of base64 image data to identify visual matches.
        SHA-256 is used instead of MD5 to avoid hash collisions.
        """
        return hashlib.sha256(base64_image.encode('utf-8')).hexdigest()

    def get(self, image_hash: str) -> str:
        """
        Retrieves cached analysis for a given hash if it is within TTL.
        """
        with self._lock:
            now = time.time()
            # Session state check (quick context reuse with TTL check)
            if image_hash == self._last_screenshot_hash and self._last_vision_analysis:
                if now - self._last_timestamp < self.ttl:
                    logger.info("Session visual cache match! Returning last analysis.")
                    return self._last_vision_analysis
                else:
                    logger.info("Session visual cache expired.")
                    self._last_screenshot_hash = None
                    self._last_vision_analysis = None

            if image_hash in self._cache:
                result, timestamp = self._cache[image_hash]
                if now - timestamp < self.ttl:
                    logger.info("Vision TTL cache hit!")
                    # Update session variables
                    self._last_screenshot_hash = image_hash
                    self._last_vision_analysis = result
                    self._last_timestamp = timestamp
                    return result
                else:
                    # Expire cache entry
                    del self._cache[image_hash]
            return None

    def set(self, image_hash: str, result: str):
        """
        Stores an analysis in the cache and updates session tracking.
        """
        now = time.time()
        with self._lock:
            self._cache[image_hash] = (result, now)
            self._last_screenshot_hash = image_hash
            self._last_vision_analysis = result
            self._last_timestamp = now
        logger.debug("Vision cache updated.")
