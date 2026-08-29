"""
ai/agents/language/agent.py — LanguageAgent specialist.

Handles language detection, translation, structured data extraction from
Hindi/Gujarati/English text, and language preference memory via the agent bus.
"""
import logging
import asyncio

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult
from modules.language.language_detector import detect_language
from modules.language.translation_service import TranslationService

logger = logging.getLogger("JARVIS.LanguageAgent")


class LanguageAgent(BaseAgent):
    """
    Specialist agent for language detection, translation, structured data
    extraction from Hindi/Gujarati text, and language preference memory.

    Registered on the bus as 'language_agent'. Other agents (e.g. coordinator,
    supervisor) can dispatch tasks to it for language-related operations.
    """

    def __init__(self, bus, memory=None):
        super().__init__(agent_id="language_agent")
        self.bus = bus
        self.memory = memory
        self.translation_service = TranslationService()
        self.bus.register(self.agent_id, self.handle)

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload

        try:
            if task_type == "detect_language":
                return await self._handle_detect_language(task, payload)
            elif task_type == "translate_text":
                return await self._handle_translate_text(task, payload)
            elif task_type == "extract_document_data":
                return await self._handle_extract_document_data(task, payload)
            elif task_type == "set_language_preference":
                return await self._handle_set_language_preference(task, payload)
            elif task_type == "get_language_preference":
                return await self._handle_get_language_preference(task, payload)
            else:
                return self._create_result(
                    task, success=False,
                    error=f"LanguageAgent does not support task type '{task_type}'"
                )
        except Exception as e:
            logger.exception(f"LanguageAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))

    async def _handle_detect_language(self, task: AgentTask, payload: dict) -> AgentResult:
        text = payload.get("text", "")
        if not text:
            return self._create_result(
                task, success=False, error="'text' is required for detect_language"
            )
        result = detect_language(text)
        return self._create_result(
            task, success=True,
            result=result.to_dict(),
            confidence=result.confidence,
            source="static"
        )

    async def _handle_translate_text(self, task: AgentTask, payload: dict) -> AgentResult:
        text = payload.get("text", "")
        target_lang = payload.get("target_lang", "en")
        source_lang = payload.get("source_lang")

        if not text:
            return self._create_result(
                task, success=False, error="'text' is required for translate_text"
            )

        result = await asyncio.to_thread(
            self.translation_service.translate,
            text,
            target_lang,
            source_lang,
        )
        return self._create_result(
            task, success=True,
            result=result.to_dict(),
            source="llm"
        )

    async def _handle_extract_document_data(self, task: AgentTask, payload: dict) -> AgentResult:
        text = payload.get("text", "")
        if not text:
            return self._create_result(
                task, success=False, error="'text' is required for extract_document_data"
            )

        prompt = (
            "You are JARVIS's document data extractor. The following text may be in "
            "Hindi (Devanagari), Gujarati, or English, possibly mixed.\n\n"
            "Extract structured data as JSON with keys: dates, amounts, names, "
            "addresses, other_key_values. Use empty lists/objects where nothing "
            "is found. Preserve original-language spelling for names/addresses, "
            "but format dates as ISO (YYYY-MM-DD) where confidently parseable.\n\n"
            f"TEXT:\n{text}"
        )

        response = await self.generate_response(
            prompt, response_mime_type="application/json"
        )
        data = self._parse_json_response(response)
        return self._create_result(task, success=True, result=data, source="llm")

    async def _handle_set_language_preference(self, task: AgentTask, payload: dict) -> AgentResult:
        language = payload.get("language")
        if not language:
            return self._create_result(
                task, success=False, error="'language' is required for set_language_preference"
            )
        if not self.memory:
            return self._create_result(
                task, success=False,
                error="MemoryManager is not available — cannot persist preferences"
            )

        self.memory.set_preference("preferred_language", language)
        logger.info(f"Language preference set to '{language}'")
        return self._create_result(
            task, success=True,
            result={"preferred_language": language},
            source="tool"
        )

    async def _handle_get_language_preference(self, task: AgentTask, payload: dict) -> AgentResult:
        if not self.memory:
            return self._create_result(
                task, success=True,
                result={"preferred_language": None}
            )

        pref = self.memory.get_preference("preferred_language")
        return self._create_result(
            task, success=True,
            result={"preferred_language": pref}
        )
