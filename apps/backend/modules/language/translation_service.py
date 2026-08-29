import os
import logging
from modules.language.language_detector import detect_language

logger = logging.getLogger("JARVIS.TranslationService")

class TranslationResult:
    def __init__(self, translated_text: str, source_lang: str, target_lang: str, engine_used: str, confidence: float = 1.0):
        self.translated_text = translated_text
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.engine_used = engine_used
        self.confidence = confidence

    def to_dict(self):
        return {
            "translated_text": self.translated_text,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "engine_used": self.engine_used,
            "confidence": self.confidence
        }

    def __repr__(self):
        return (f"TranslationResult(translated_text='{self.translated_text[:30]}...', "
                f"source_lang='{self.source_lang}', target_lang='{self.target_lang}', "
                f"engine_used='{self.engine_used}')")

class TranslationService:
    """
    TranslationService handles translating text between Hindi, Gujarati, English,
    and other languages. Reuses the existing Gemini client connection by default.
    """
    def __init__(self):
        self._gemini_client = None

    def _get_gemini_client(self):
        if self._gemini_client is not None:
            return self._gemini_client
        try:
            from container import ServiceContainer
            container = ServiceContainer.instance()
            if container:
                vision_manager = container.get_or_none("vision_manager")
                if vision_manager and getattr(vision_manager, "client", None):
                    self._gemini_client = vision_manager.client
                    return self._gemini_client

            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if api_key:
                import google.genai
                self._gemini_client = google.genai.Client(api_key=api_key)
        except Exception as e:
            logger.debug(f"Failed to initialize Gemini client for TranslationService: {e}")
        return self._gemini_client

    def translate(self, text: str, target_lang: str, source_lang: str | None = None) -> TranslationResult:
        if not text or not text.strip():
            return TranslationResult("", source_lang or "en", target_lang, "noop")

        # 1. Resolve source language if not provided
        if source_lang is None:
            detection = detect_language(text)
            source_lang = detection.code
            logger.debug(f"Auto-detected source language: {source_lang}")

        # Map language codes to printable names if they are short (hi/gu/en)
        lang_names = {
            "en": "English",
            "hi": "Hindi",
            "gu": "Gujarati"
        }
        src_name = lang_names.get(source_lang.lower(), source_lang)
        tgt_name = lang_names.get(target_lang.lower(), target_lang)

        # 2. If same language target, return unchanged
        if source_lang.lower() == target_lang.lower() or src_name.lower() == tgt_name.lower():
            return TranslationResult(text, source_lang, target_lang, "noop")

        # 3. Optional higher-fidelity path: Google Cloud Translation API (opt-in)
        cloud_key = os.getenv("GOOGLE_CLOUD_TRANSLATE_KEY")
        if cloud_key:
            res_text = self._translate_with_cloud_api(text, source_lang, target_lang, cloud_key)
            if res_text:
                return TranslationResult(res_text, source_lang, target_lang, "google_cloud")

        # 4. Default path: Gemini prompt-based translation
        res_text = self._translate_with_gemini(text, src_name, tgt_name)
        if res_text:
            return TranslationResult(res_text, source_lang, target_lang, "gemini")

        # Fallback: return original text
        return TranslationResult(text, source_lang, target_lang, "fallback_failed")

    def _translate_with_gemini(self, text: str, source_lang_name: str, target_lang_name: str) -> str:
        client = self._get_gemini_client()
        if not client:
            logger.warning("Gemini client not available for translation.")
            return ""
        from config.settings import GEMINI_FALLBACK_CHAIN
        prompt = (
            f"Translate the following {source_lang_name} text into {target_lang_name}.\n"
            f"Return ONLY the translated text, no explanation, no quotes, no notes.\n\n"
            f"Text:\n{text}"
        )
        for model in GEMINI_FALLBACK_CHAIN:
            try:
                logger.info(f"Translating via Gemini ({model}): {source_lang_name} -> {target_lang_name}")
                response = client.models.generate_content(
                    model=model,
                    contents=[prompt]
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                logger.warning(f"Gemini translation on model {model} failed: {e}. Trying next fallback...")
                continue
        return ""

    def _translate_with_cloud_api(self, text: str, source_lang: str, target_lang: str, api_key: str) -> str | None:
        try:
            import requests
            url = f"https://translation.googleapis.com/language/translate/v2?key={api_key}"
            payload = {
                "q": text,
                "source": source_lang,
                "target": target_lang,
                "format": "text"
            }
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                translations = data.get("data", {}).get("translations", [])
                if translations:
                    return translations[0].get("translatedText", "")
            else:
                logger.warning(f"Google Cloud Translate API returned status code {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Google Cloud Translate API failed: {e}")
        return None
