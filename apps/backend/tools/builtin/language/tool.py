"""tools/builtin/language/tool.py — LanguageTools toolset."""
import uuid
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from ai.agents.types import AgentTask


class LanguageTools(JarvisToolset):
    """
    LanguageTools lets the user set a standing language preference and
    request structured data extraction from Hindi/Gujarati text.

    SYSTEM PROMPT:
    Call set_language_preference when the user explicitly asks you to
    remember or switch their preferred language (e.g. "mujhse Hindi mein
    baat karo", "reply to me in Gujarati from now on"). Call
    extract_structured_data when the user wants dates, names, amounts, or
    addresses pulled out of Hindi/Gujarati/English text or a document.

    SHORT DESCRIPTION:
    Manages language preference memory and structured data extraction from
    multilingual text via the LanguageAgent.

    PROCESS:
    1. Receives a user request to set language preference or extract data.
    2. Creates an AgentTask and dispatches it to the language_agent via the bus.
    3. Returns the result to the user.

    FLOW:
    Agent -> set_language_preference()/extract_structured_data() -> AgentBus
          -> LanguageAgent -> MemoryManager / Gemini -> AgentResult -> Agent
    """

    def __init__(self, bus, security=None, room=None):
        super().__init__(security, room)
        self.bus = bus

    @llm.function_tool(
        description=(
            "Set and remember the user's preferred language for future replies "
            "(e.g. 'Hindi', 'Gujarati', 'English', 'Hinglish'). Use this when the "
            "user explicitly asks you to speak or reply in a specific language going "
            "forward, such as 'mujhse Hindi mein baat karo' or 'from now on reply "
            "in Gujarati'."
        )
    )
    async def set_language_preference(self, language: str) -> str:
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="set_language_preference",
            payload={"language": language},
            origin_agent="supervisor",
            target_agent="language_agent",
        )
        try:
            from modules.memory.shared_context import SharedContextStore
            await SharedContextStore.get_instance().update_dict("user_preferences", {"preferred_language": language})
        except Exception:
            pass

        result = await self.bus.dispatch(task)
        if result.success:
            return f"Got it — I'll remember your preferred language is {language}."
        return f"Couldn't save that preference: {result.error}"

    @llm.function_tool(
        description=(
            "Extract structured data (dates, names, amounts, addresses) from "
            "Hindi, Gujarati, or English text — typed, spoken, or OCR-extracted "
            "from a document. Returns a JSON object with keys: dates, amounts, "
            "names, addresses, other_key_values."
        )
    )
    async def extract_structured_data(self, text: str) -> str:
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="extract_document_data",
            payload={"text": text},
            origin_agent="supervisor",
            target_agent="language_agent",
        )
        result = await self.bus.dispatch(task)
        if result.success:
            return f"Extracted data: {result.result}"
        return f"Extraction failed: {result.error}"
