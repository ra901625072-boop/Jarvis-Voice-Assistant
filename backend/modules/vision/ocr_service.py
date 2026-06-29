import logging
from PIL import Image

logger = logging.getLogger("JARVIS.OCRService")

class OCRService:
    """
    OCRService extracts text from screenshots using the native Windows OCR engine (via winocr).
    Executes in ~50-300ms on CPU, making it extremely suitable for voice assistant responsiveness.
    """
    def __init__(self):
        logger.info("OCRService initialized using native Windows OCR (winocr).")

    def warmup(self):
        """
        Warms up the WinRT OCR engine projections in the background during assistant startup.
        Ensures the first active query does not see import/DLL loading latency.
        """
        try:
            import winocr
            # Use a standard 1280x720 blank image to fully warm up the DLL and neural engine for desktop screenshot sizes
            dummy = Image.new("RGB", (1280, 720))
            # Quick dummy recognition to load WinRT binaries
            winocr.recognize_pil_sync(dummy, lang='en')
            logger.info("Native Windows OCR (winocr) warmup completed.")
        except Exception as e:
            logger.error(f"winocr warmup failed: {e}")

    def extract_text(self, image: Image.Image) -> str:
        """
        Extracts text from a PIL Image using the native Windows OCR engine.
        Returns the merged text string.
        """
        try:
            import winocr
            # Convert image to RGB format if not already
            img_rgb = image.convert("RGB")
            
            # Direct synchronous call utilizing native OS APIs
            result = winocr.recognize_pil_sync(img_rgb, lang='en')
            text = result.get("text", "")
            logger.debug(f"winocr extracted {len(text)} characters of text.")
            return text
        except Exception as e:
            logger.error(f"winocr text extraction failed: {e}")
            return f"Error running native Windows OCR: {str(e)}"
