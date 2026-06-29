import os
import io
import time
import logging
import asyncio
from typing import Optional
from PIL import Image
from google import genai
from google.genai import types

# Import window detector and OCR service from modules.vision
from modules.vision.window_detector import WindowDetector
from modules.vision.ocr_service import OCRService

from .screen_capture import ScreenCapturer
from .image_optimizer import optimize_image
from .vision_cache import VisionCache
from .openrouter_vision import OpenRouterVisionClient

logger = logging.getLogger("JARVIS.VisionManager")

class VisionRateLimiter:
    """
    Rate limiter to prevent excessive screenshot queries and loop spamming.
    """
    def __init__(self, max_calls: int = 10, period: float = 60.0):
        self.max_calls = max_calls
        self.period = period
        self.calls = []

    def acquire(self) -> bool:
        now = time.time()
        self.calls = [t for t in self.calls if now - t < self.period]
        if len(self.calls) >= self.max_calls:
            return False
        self.calls.append(now)
        return True

class VisionManager:
    """
    Main vision manager orchestrator for JARVIS.
    Features: On-demand capturing, active window targeting, duplicate check, OCR fast-path, and Gemini-to-Qwen fallback.
    """
    def __init__(self):
        # Gemini Client Init
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            self.client = genai.Client(api_key=api_key)
        else:
            self.client = None
            logger.warning("Google/Gemini API key is not configured in .env.")

        # Sub-components
        self.capturer = ScreenCapturer()
        self.cache = VisionCache(ttl=30.0)
        self.openrouter_client = OpenRouterVisionClient()
        self.window_detector = WindowDetector()
        self.ocr_service = OCRService()
        self.rate_limiter = VisionRateLimiter(max_calls=10, period=60.0)
        self._semaphore = asyncio.Semaphore(2)
        
        self.memory_manager = None
        logger.info("Redesigned VisionManager successfully initialized.")

    def warmup(self):
        """
        Warms up dependencies (winocr, mss, win32gui, and client)
        to eliminate first-use latency.
        """
        try:
            logger.info("Warming up OCR engine...")
            self.ocr_service.warmup()
            logger.info("Warming up screen capture and window detection modules...")
            dummy_region = (0, 0, 1, 1)
            self.capturer.capture(dummy_region)
            self.window_detector.get_active_window_info()
            logger.info("VisionManager warmup completed successfully.")
        except Exception as e:
            logger.warning(f"VisionManager warmup encountered issues: {e}")

    def set_memory_manager(self, memory_manager):
        """
        Allows lazy registration of MemoryManager instance from agent session.
        """
        self.memory_manager = memory_manager
        logger.info("MemoryManager registered to VisionManager.")

    def _generate_gemini_vision(self, image_bytes: bytes, prompt: str) -> str:
        """
        Calls Gemini 2.5 Flash Vision model using the generated image bytes.
        """
        if not self.client:
            raise ValueError("Gemini client is not initialized.")
        
        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        text_part = types.Part.from_text(text=prompt)
        
        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[image_part, text_part],
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=800,
            )
        )
        if response and response.text:
            return response.text.strip()
        raise ValueError("Empty response text from Gemini Vision.")

    def _generate_gemini_text(self, prompt: str) -> str:
        """
        Calls text-only Gemini 2.5 Flash for the OCR fast path.
        """
        if not self.client:
            raise ValueError("Gemini client is not initialized.")
        
        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=800,
            )
        )
        if response and response.text:
            return response.text.strip()
        raise ValueError("Empty response text from Gemini.")

    async def analyze_screen(self, query: str, custom_prompt: Optional[str] = None) -> str:
        """
        Processes vision queries in an asynchronous, sub-second latency model.
        """
        t_start = time.perf_counter()

        # Rate Limiter Check
        if not self.rate_limiter.acquire():
            logger.warning("Vision rate limit hit. Bypassing request.")
            return "Error: Screenshot query rate limit reached (max 10 requests per minute). Please wait before trying again."

        async with self._semaphore:
            # 2. Window Detection & Crop (Target active window)
            win_info = self.window_detector.get_active_window_info()
            region = win_info.get("rect")
            app_name = win_info.get("active_app", "Desktop")

            # 3. Capture Screen/Region (Runs in executor to avoid blocking loop)
            loop = asyncio.get_running_loop()
            img = await loop.run_in_executor(None, self.capturer.capture, region)
            t_capture = time.perf_counter()

            # 4. Image Compression & Hash Generation
            base64_image = await loop.run_in_executor(None, optimize_image, img)
            image_hash = self.cache.get_hash(base64_image)
            t_compress = time.perf_counter()

            # 5. Screenshot Deduplication (Hash Check)
            cached_result = self.cache.get(image_hash)
            if cached_result:
                elapsed_ms = int((time.perf_counter() - t_start) * 1000)
                logger.info(f"Duplicate frame detected. Returned cached result in {elapsed_ms}ms (0 API calls).")
                return cached_result

            # Convert compressed image to bytes for Gemini Vision if needed later
            import base64
            image_bytes = base64.b64decode(base64_image)

            # 6. OCR Fast Path check
            is_text_focused = any(kw in query.lower() for kw in ["error", "traceback", "exception", "syntax", "code", "terminal", "logs", "text", "message", "write"])
            is_visual_focused = any(kw in query.lower() for kw in ["layout", "design", "color", "button", "click", "where is", "logo", "icon", "look like"])
            
            ocr_text = ""
            use_ocr_path = False
            if is_text_focused and not is_visual_focused:
                ocr_text = await loop.run_in_executor(None, self.ocr_service.extract_text, img)
                if ocr_text and not ocr_text.startswith("Error") and len(ocr_text.split()) >= 5:
                    use_ocr_path = True
                    logger.info("OCR fast-path matched! Bypassing Vision model.")

            prompt = custom_prompt if custom_prompt else query

            # 7. Model Execution
            vision_result = None
            if use_ocr_path:
                # OCR Fast Path execution (Text model query is extremely low latency)
                ocr_prompt = f"""
                {prompt}

                Here is the text extracted from their active window via OCR:
                ```text
                {ocr_text}
                ```
                """
                try:
                    vision_result = await loop.run_in_executor(None, self._generate_gemini_text, ocr_prompt)
                    logger.info("Successfully answered via OCR text-only path.")
                except Exception as e:
                    logger.warning(f"OCR Fast Path LLM call failed: {e}. Falling back to Vision Model.")

            VISION_TIMEOUT = 8.0
            if not vision_result:
                # Primary: Gemini 2.5 Flash Vision Model
                try:
                    vision_result = await asyncio.wait_for(
                        loop.run_in_executor(None, self._generate_gemini_vision, image_bytes, prompt),
                        timeout=VISION_TIMEOUT
                    )
                    logger.info("Successfully answered via primary Gemini Vision model.")
                except asyncio.TimeoutError:
                    logger.warning("Gemini Vision timed out. Trying fallback...")
                    vision_result = None
                except Exception as e:
                    # Fallback: OpenRouter Qwen-VL model
                    logger.warning(f"Primary Gemini Vision failed: {e}. Attempting OpenRouter Qwen fallback...")
                    vision_result = None
                    
                if not vision_result:
                    try:
                        fallback_result = await asyncio.wait_for(
                            loop.run_in_executor(
                                None, 
                                self.openrouter_client.analyze_image, 
                                base64_image, 
                                prompt
                            ),
                            timeout=VISION_TIMEOUT
                        )
                        
                        if fallback_result and not fallback_result.startswith("Error:"):
                            vision_result = f"[Note: response via backup vision model, may be lower accuracy]\n{fallback_result}"
                            logger.info("Successfully answered via OpenRouter Qwen fallback.")
                        else:
                            vision_result = "VISION_UNAVAILABLE: Both vision models failed due to API quota/rate limits. Do NOT describe or guess screen content. Inform the user the vision system is temporarily unavailable."
                    except asyncio.TimeoutError:
                        vision_result = "VISION_UNAVAILABLE: Vision analysis timed out. Please try again in a moment."
                    except Exception as e:
                        vision_result = "VISION_UNAVAILABLE: Both vision models failed due to API quota/rate limits. Do NOT describe or guess screen content. Inform the user the vision system is temporarily unavailable."

            # Write result to Cache
            if vision_result and not vision_result.startswith("Error:"):
                self.cache.set(image_hash, vision_result)

            # Metrics profiling log
            total_time_ms = int((time.perf_counter() - t_start) * 1000)
            logger.info(f"=== JARVIS VISION METRICS ===")
            logger.info(f"Capture Time: {int((t_capture - t_start) * 1000)}ms")
            logger.info(f"Compression/Hash Time: {int((t_compress - t_capture) * 1000)}ms")
            logger.info(f"Total Process Latency: {total_time_ms}ms")
            logger.info(f"=====================================")

            return str(vision_result)

    async def process_query(self, query: str) -> str:
        """
        Compatibility wrapper that maps process_query (used by legacy tools)
        to the redesigned analyze_screen coroutine.
        """
        return await self.analyze_screen(query)
