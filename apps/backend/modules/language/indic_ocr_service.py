import os
import logging
from PIL import Image

logger = logging.getLogger("JARVIS.IndicOCRService")

class IndicOCRService:
    """
    IndicOCRService routes OCR requests to the appropriate engine:
    1. Windows native OCR (winocr) for fast, local English OCR.
    2. EasyOCR for Hindi OCR (local, offline).
    3. Tesseract (pytesseract) for Gujarati/Hindi OCR if installed.
    4. Gemini 2.5 Flash for high-quality multimodal cloud OCR as a robust fallback.
    """
    def __init__(self):
        self._easyocr_reader = None
        self._gemini_client = None
        self._initialized_easyocr = False

    def _get_gemini_client(self):
        if self._gemini_client is not None:
            return self._gemini_client
        try:
            # Try to get the client from the ServiceContainer
            from container import ServiceContainer
            container = ServiceContainer.instance()
            if container:
                # Retrieve from vision_manager if registered
                vision_manager = container.get_or_none("vision_manager")
                if vision_manager and getattr(vision_manager, "client", None):
                    self._gemini_client = vision_manager.client
                    return self._gemini_client

            # Fallback to creating a new client from env variables
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if api_key:
                import google.genai
                self._gemini_client = google.genai.Client(api_key=api_key)
        except Exception as e:
            logger.debug(f"Failed to initialize Gemini client for IndicOCRService: {e}")
        return self._gemini_client

    def _get_easyocr_reader(self):
        if self._easyocr_reader is not None or self._initialized_easyocr:
            return self._easyocr_reader
        self._initialized_easyocr = True
        try:
            import easyocr
            logger.info("Initializing EasyOCR reader for ['hi', 'en']...")
            self._easyocr_reader = easyocr.Reader(['hi', 'en'], gpu=False)
            logger.info("EasyOCR reader initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize EasyOCR reader: {e}")
        return self._easyocr_reader

    def _ocr_with_easyocr(self, image: Image.Image) -> str:
        reader = self._get_easyocr_reader()
        if not reader:
            return ""
        try:
            import numpy as np
            img_np = np.array(image.convert("RGB"))
            results = reader.readtext(img_np)
            text = " ".join([res[1] for res in results])
            return text.strip()
        except Exception as e:
            logger.error(f"EasyOCR extraction failed: {e}")
            return ""

    def _ocr_with_tesseract(self, image: Image.Image, lang: str = "guj+hin+eng") -> str:
        try:
            import pytesseract
            tess_cmd = os.getenv("TESSERACT_CMD_PATH")
            if tess_cmd:
                pytesseract.pytesseract.tesseract_cmd = tess_cmd
            
            text = pytesseract.image_to_string(image, lang=lang)
            return text.strip()
        except Exception as e:
            logger.debug(f"Pytesseract extraction failed (likely not installed or missing lang pack): {e}")
            return ""

    def _ocr_with_gemini(self, image: Image.Image) -> str:
        client = self._get_gemini_client()
        if not client:
            logger.warning("Gemini client not available for OCR fallback.")
            return ""
        from config.settings import GEMINI_FALLBACK_CHAIN
        for model in GEMINI_FALLBACK_CHAIN:
            try:
                logger.info(f"Calling Gemini ({model}) for OCR...")
                response = client.models.generate_content(
                    model=model,
                    contents=[
                        image,
                        "Extract and transcribe all text from this image exactly as written. "
                        "Support multiple languages, including Hindi and Gujarati scripts. "
                        "Preserve layout and line breaks. Return ONLY the transcribed text, without any explanation or notes."
                    ]
                )
                text = response.text or ""
                if text:
                    logger.info(f"Gemini OCR completed successfully ({len(text)} characters extracted).")
                    return text.strip()
            except Exception as e:
                logger.warning(f"Gemini OCR on model {model} failed: {e}. Trying next fallback...")
                continue
        return ""

    def extract_text(self, image: Image.Image, languages: list[str] = None) -> str:
        if not languages:
            languages = ["en"]

        logger.info(f"IndicOCRService.extract_text called with languages={languages}")

        has_hindi = "hi" in languages
        has_gujarati = "gu" in languages

        # 1. Fast Path: English only -> use native Windows OCR if possible
        if not has_hindi and not has_gujarati:
            try:
                import winocr
                result = winocr.recognize_pil_sync(image.convert("RGB"), lang='en')
                return result.get("text", "").strip()
            except Exception as e:
                logger.warning(f"WinOCR fast path failed: {e}")

        # 2. Gujarati flow (Tesseract -> Gemini fallback)
        if has_gujarati:
            text = self._ocr_with_tesseract(image, lang="guj+hin+eng")
            if text and len(text.strip()) > 3:
                logger.info("Gujarati text extracted successfully using Tesseract.")
                return text

            logger.info("Tesseract not available or failed for Gujarati. Trying Gemini OCR fallback...")
            text = self._ocr_with_gemini(image)
            if text:
                return text

        # 3. Hindi flow (EasyOCR -> Tesseract -> Gemini fallback)
        if has_hindi:
            text = self._ocr_with_easyocr(image)
            if text and len(text.strip()) > 3:
                logger.info("Hindi text extracted successfully using EasyOCR.")
                return text

            text = self._ocr_with_tesseract(image, lang="hin+eng")
            if text and len(text.strip()) > 3:
                logger.info("Hindi text extracted successfully using Tesseract.")
                return text

            logger.info("EasyOCR/Tesseract failed for Hindi. Trying Gemini OCR fallback...")
            text = self._ocr_with_gemini(image)
            if text:
                return text

        # Default fallback to Gemini if non-English languages requested but not processed yet
        if has_hindi or has_gujarati:
            text = self._ocr_with_gemini(image)
            if text:
                return text

        # Final absolute fallback to winocr
        try:
            import winocr
            result = winocr.recognize_pil_sync(image.convert("RGB"), lang='en')
            return result.get("text", "").strip()
        except Exception:
            return ""
