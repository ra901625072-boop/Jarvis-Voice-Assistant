import os
import io
from pathlib import Path
import json
import sqlite3
import time
import threading
import logging
from google import genai
from google.genai import types
from PIL import Image

logger = logging.getLogger("JARVIS.Vision")

# =========================
# Gemini Configuration
# =========================

API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if API_KEY:
    client = genai.Client(api_key=API_KEY)
else:
    client = None


# =========================
# Persistent Vision Cache & Rate Limiter
# =========================

_db_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database")
os.makedirs(_db_dir, exist_ok=True)
_cache_db_path = os.path.join(_db_dir, "vision_cache.db")

def _init_cache_db():
    try:
        with sqlite3.connect(_cache_db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    cache_key TEXT PRIMARY KEY,
                    result TEXT,
                    created_at REAL
                )
            """)
    except Exception as e:
        logger.error(f"Failed to initialize vision cache DB: {e}")

_init_cache_db()

def _get_cached_result(cache_key: str) -> str:
    try:
        with sqlite3.connect(_cache_db_path) as conn:
            cursor = conn.execute("SELECT result FROM cache WHERE cache_key = ?", (cache_key,))
            row = cursor.fetchone()
            if row:
                return row[0]
    except Exception as e:
        logger.debug(f"Ignored error reading from vision cache: {e}")
    return None

def _set_cached_result(cache_key: str, result: str):
    try:
        with sqlite3.connect(_cache_db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO cache (cache_key, result, created_at) VALUES (?, ?, ?)",
                         (cache_key, result, time.time()))
    except Exception as e:
        logger.error(f"Failed to cache vision result: {e}")

class RateLimiter:
    def __init__(self, rpm: int = 15):
        self.rpm = rpm
        self.tokens = rpm
        self.last_update = time.time()
        self.lock = threading.Lock()

    def acquire(self) -> bool:
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.rpm, self.tokens + elapsed * (self.rpm / 60.0))
            self.last_update = now

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False

_rate_limiter = RateLimiter(rpm=15)


# =========================
# Prompts
# =========================

SCREEN_ANALYSIS_PROMPT = """
Analyze this screenshot.

Identify:
- Open applications
- Buttons
- Visible text
- Errors or warnings
- Browser tabs
- Forms
- Menus

Provide a short, voice-assistant-friendly summary.
"""

OCR_PROMPT = """
Extract all readable text from this screenshot.

Rules:
- Preserve line breaks.
- Return only the extracted text.
- Do not explain anything.
"""


# =========================
# Core Function
# =========================

def _generate_from_image(
    image_path: str,
    prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 1000,
    screen_hash: str = None
) -> str:
    """
    Send an image and prompt to Gemini using the new google-genai SDK.
    Uses persistent sqlite cache if screen_hash is provided.
    """

    if not client:
        return "Error: Vision tool requires GOOGLE_API_KEY or GEMINI_API_KEY to be set in .env"

    if screen_hash:
        cache_key = f"{screen_hash}_{prompt}"
        cached = _get_cached_result(cache_key)
        if cached is not None:
            logger.info("Vision cache hit.")
            return cached

    path = Path(image_path)

    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    # Apply Rate Limiting
    while not _rate_limiter.acquire():
        logger.warning("Vision API rate limit reached. Waiting...")
        time.sleep(2)

    try:
        # Read the image as raw PNG bytes — the new google-genai SDK does NOT
        # accept a PIL Image object directly; it requires a typed Part.
        with Image.open(path) as pil_image:
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            image_bytes = buf.getvalue()

        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")
        text_part  = types.Part.from_text(text=prompt)

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[image_part, text_part],
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            ),
        )

        result = response.text.strip() if response.text else ""
        if screen_hash:
            _set_cached_result(cache_key, result)
        return result

    except Exception as e:
        logger.error(f"Vision API Error: {e}")
        return f"Error: {str(e)}"


# =========================
# Public Functions
# =========================

def analyze_screen(image_path: str, screen_hash: str = None) -> str:
    """
    Generate a concise screen summary.
    """
    return _generate_from_image(
        image_path=image_path,
        prompt=SCREEN_ANALYSIS_PROMPT,
        temperature=0.1,
        max_tokens=500,
        screen_hash=screen_hash
    )


def extract_text_from_screen(image_path: str, screen_hash: str = None) -> str:
    """
    Extract all readable text from screenshot.
    """
    return _generate_from_image(
        image_path=image_path,
        prompt=OCR_PROMPT,
        temperature=0.0,
        max_tokens=4000,
        screen_hash=screen_hash
    )


def find_element_bounding_box(image_path: str, element_description: str, screen_hash: str = None) -> list[int]:
    """
    Uses Gemini to locate an element and return its bounding box as [ymin, xmin, ymax, xmax].
    Returns an empty list if it fails.
    """
    prompt = f'Find the "{element_description}" in this image. Return its 2D bounding box in the format [ymin, xmin, ymax, xmax], scaled to 1000. Do not include any other text, explanations, or formatting. Just output the array.'
    
    response = _generate_from_image(
        image_path=image_path,
        prompt=prompt,
        temperature=0.0,
        max_tokens=100,
        screen_hash=screen_hash
    )
    
    if not response or str(response).startswith("Error:"):
        return []
        
    try:
        # Strip potential markdown code blocks
        clean_response = response.strip().strip('`').replace('json\n', '').strip()
        box = json.loads(clean_response)
        if isinstance(box, list) and len(box) == 4:
            return box
    except Exception as e:
        print(f"Failed to parse bounding box from Gemini: {response} - {e}")
        
    return []


def verify_condition(image_path: str, expected_state: str, screen_hash: str = None) -> bool:
    """
    Asks Gemini Vision if the image meets the expected state.
    Returns True if YES, False if NO.
    """
    prompt = f"Does the current screen show the following state or outcome: '{expected_state}'? Answer only YES or NO. Do not explain."
    
    response = _generate_from_image(
        image_path=image_path,
        prompt=prompt,
        temperature=0.0,
        max_tokens=10,
        screen_hash=screen_hash
    )
    
    if not response or str(response).startswith("Error:"):
        return False
        
    clean_resp = response.strip().lower()
    return "yes" in clean_resp and "no" not in clean_resp.replace("yes", "")
