"""tools/builtin/translation/tool.py — TranslationTools toolset."""
import asyncio
import logging
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.language.translation_service import TranslationService

logger = logging.getLogger("JARVIS.TranslationTools")


class TranslationTools(JarvisToolset):
    """
    TranslationTools exposes text translation between Hindi, Gujarati, English,
    and other languages during a live voice or task session.

    SYSTEM PROMPT:
    Call translate_text whenever the user asks to translate spoken text, OCR-extracted
    document content, or typed text into another language — including Hindi, Gujarati,
    English, or any other language they name.

    SHORT DESCRIPTION:
    Translates text between languages using the configured translation engine
    (Gemini by default, optional Cloud Translation API if configured).

    PROCESS:
    1. Accepts source text and a target language (source language optional/auto-detected).
    2. Delegates to TranslationService.translate() off the event loop via asyncio.to_thread.
    3. Returns the translated text plus which languages/engine were used.

    FLOW:
    Agent -> translate_text() -> TranslationService -> Gemini/Cloud API -> TranslationResult -> Agent
    """

    def __init__(self, translation_service: TranslationService, security=None, room=None):
        super().__init__(security, room)
        self.translation_service = translation_service

    @llm.function_tool(
        description=(
            "Translate text into another language. Use this when the user asks to translate "
            "Hindi, Gujarati, English, or any other language text — spoken, typed, or extracted "
            "from a document/image. target_language: the language to translate INTO (e.g. 'English', "
            "'Hindi', 'Gujarati', 'French'). source_language: optional — leave blank to auto-detect."
        )
    )
    async def translate_text(self, text: str, target_language: str, source_language: str = "") -> str:
        try:
            result = await asyncio.to_thread(
                self.translation_service.translate,
                text,
                target_language,
                source_language or None,
            )
            return (
                f"Translated ({result.source_lang} → {result.target_lang}, via {result.engine_used}): "
                f"{result.translated_text}"
            )
        except Exception as e:
            logger.error(f"Translation failed: {e}", exc_info=True)
            return f"Translation failed: {str(e) or 'Unknown error'}"
