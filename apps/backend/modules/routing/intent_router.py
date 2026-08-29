"""
modules.routing.intent_router
-----------------------------
Intelligent Intent Classifier & Task Router for JARVIS Multi-Agent OS.
Distinguishes between conversational chit-chat, factual Q&A, user memory lookups,
single-step system controls, and complex multi-agent execution goals.
"""

import re
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from modules.routing.task_classifier import (
    TaskClassifier,
    TaskComplexityLevel,
    TaskExecutionLane,
    TaskClassificationReport,
)

logger = logging.getLogger("JARVIS.IntentRouter")


class QueryIntent(str, Enum):
    CONVERSATIONAL = "conversational"       # Greetings, identity, small talk, gratitude
    INFORMATIONAL_QA = "informational_qa"   # General knowledge questions, explanations, math, definitions
    MEMORY_QUERY = "memory_query"           # Inquiries about user profile, preferences, past sessions
    SYSTEM_ACTION = "system_action"         # Single-step local actions (volume, open app, screenshot)
    COMPLEX_GOAL = "complex_goal"           # Multi-step workflows (coding, web scraping, project creation, terminal)


@dataclass
class IntentClassificationResult:
    intent: QueryIntent
    confidence: float
    is_direct_chat: bool
    action_type: Optional[str] = None
    suggested_tool: Optional[str] = None
    extracted_params: Dict[str, Any] = None
    complexity_report: Optional[TaskClassificationReport] = None

    @property
    def is_complex(self) -> bool:
        if self.complexity_report:
            return self.complexity_report.is_complex
        return self.intent == QueryIntent.COMPLEX_GOAL


class IntentRouter:
    """
    High-performance rule + regex + semantic router for user requests.
    Enables instant direct responses for Q&A/Chat/Memory and delegates true operational goals.
    """

    # 1. Conversational greetings, identity, and chit-chat patterns
    GREETINGS_PATTERN = re.compile(
        r"^(?:hello|hi|hey|good\s+(?:morning|afternoon|evening|night)|namaste|salaam|ola|sup|yo)"
        r"(?:\s+(?:jarvis|sir|buddy|there|assistant))?[!?,.]*$",
        re.IGNORECASE,
    )
    CHIT_CHAT_PATTERN = re.compile(
        r"^(?:who\s+are\s+you|what\s+is\s+your\s+name|who\s+made\s+you|who\s+created\s+you|"
        r"how\s+are\s+you|how\s+r\s+u|how\s+do\s+you\s+do|kya\s+haal\s+hai|kaise\s+ho|tum\s+kaun\s+ho|"
        r"thank\s+you|thanks|thank\s+u|dhanyawad|shukriya|bye|goodbye|see\s+you|cya|"
        r"what\s+can\s+you\s+do|what\s+are\s+your\s+capabilities|help|kya\s+kar\s+sakte\s+ho|"
        r"are\s+you\s+there|are\s+you\s+online|systems\s+status|status\s+check)[!?,.]*$",
        re.IGNORECASE,
    )

    # 2. Memory & user knowledge inquiry patterns
    MEMORY_QUERY_PATTERNS = [
        re.compile(r"\b(?:what\s+(?:is|do)\s+you\s+know\s+about\s+me)\b", re.IGNORECASE),
        re.compile(r"\b(?:what\s+do\s+you\s+remember\s+about\s+me)\b", re.IGNORECASE),
        re.compile(r"\b(?:who\s+am\s+i|what\s+is\s+my\s+name|do\s+you\s+know\s+me)\b", re.IGNORECASE),
        re.compile(r"\b(?:do\s+you\s+remember\s+(?:my|what|our|the))\b", re.IGNORECASE),
        re.compile(r"\b(?:what\s+(?:did\s+we|were\s+we)\s+(?:discuss|talk\s+about|do)\s+(?:earlier|yesterday|last\s+session|before))\b", re.IGNORECASE),
        re.compile(r"\b(?:what\s+are\s+my\s+preferences|my\s+profile\s+details)\b", re.IGNORECASE),
        re.compile(r"\b(?:tell\s+me\s+(?:everything\s+)?about\s+me)\b", re.IGNORECASE),
    ]

    # 3. Informational Q&A (questions that should be answered with LLM knowledge, NOT multi-step execution tools)
    QA_PREFIX_PATTERNS = [
        r"^(?:what\s+is|what\s+are|what\s+was|what\s+were)\s+(?!the\s+file|the\s+output|the\s+error)",
        r"^(?:how\s+does|how\s+do|how\s+can\s+one|how\s+to\s+explain)",
        r"^(?:why\s+is|why\s+are|why\s+does|why\s+do)",
        r"^(?:who\s+was|who\s+is|who\s+won|who\s+discovered)",
        r"^(?:explain|describe|define|summarize|tell\s+me\s+about|calculate|what\s+is\s+\d+)",
        r"^(?:write\s+a\s+(?:poem|story|joke|essay|quote|riddle|haiku))",
    ]

    # 4. Clear action triggers that require tools / operational execution
    ACTION_VERBS = [
        "create", "build", "make", "generate", "code", "refactor", "debug", "fix",
        "open", "launch", "start", "close", "kill", "stop", "restart", "shutdown",
        "run", "execute", "install", "download", "browse", "navigate", "search online for",
        "scrape", "extract", "click", "type", "press", "scroll", "delete", "remove",
        "take screenshot", "capture screen", "set volume", "mute", "unmute", "set brightness",
        "check", "read", "show", "send", "whatsapp", "email", "gmail", "instagram", "unread"
    ]

    @classmethod
    def classify(cls, query: str) -> IntentClassificationResult:
        """Classifies a user query string into a structured intent using TaskClassifier."""
        report = TaskClassifier.classify(query)

        # Map TaskComplexityLevel & primary_intent to QueryIntent
        if report.complexity_level == TaskComplexityLevel.LEVEL_0_CONVERSATIONAL:
            if report.primary_intent == "informational_qa":
                intent = QueryIntent.INFORMATIONAL_QA
            else:
                intent = QueryIntent.CONVERSATIONAL
            confidence = 0.98 if report.primary_intent == "greetings_and_chitchat" else 0.90
        elif report.complexity_level == TaskComplexityLevel.LEVEL_1_MEMORY:
            intent = QueryIntent.MEMORY_QUERY
            confidence = 0.95
        elif report.complexity_level == TaskComplexityLevel.LEVEL_2_SINGLE_ACTION:
            intent = QueryIntent.SYSTEM_ACTION
            confidence = 0.95
        else:
            intent = QueryIntent.COMPLEX_GOAL
            confidence = 0.95 if report.is_complex else 0.80

        return IntentClassificationResult(
            intent=intent,
            confidence=confidence,
            is_direct_chat=report.is_direct_chat,
            action_type=report.primary_intent,
            suggested_tool=report.suggested_tool,
            extracted_params=report.extracted_params,
            complexity_report=report,
        )

    @classmethod
    async def handle_direct_memory_query(
        cls,
        query: str,
        memory_manager,
        llm_generator_fn,
        preferred_language: Optional[str] = "Hinglish",
    ) -> str:
        """
        Retrieves user facts, preferences, and session context from MemoryManager
        and synthesizes a personalized J.A.R.V.I.S. response.
        """
        facts_summary = []
        preferences_summary = []
        last_session_summary = ""

        if memory_manager:
            try:
                memories = memory_manager.search_memories(query="user preference identity name profile interest", limit=6)
                for m in memories:
                    content = m.get("content") if isinstance(m, dict) else str(m)
                    if content and content not in facts_summary:
                        facts_summary.append(content)
            except Exception as e:
                logger.debug(f"Error fetching memories for memory query: {e}")

            try:
                if hasattr(memory_manager, "get_all_preferences"):
                    prefs = memory_manager.get_all_preferences()
                    if isinstance(prefs, dict):
                        for k, v in prefs.items():
                            preferences_summary.append(f"{k}: {v}")
            except Exception as e:
                logger.debug(f"Error fetching preferences: {e}")

            try:
                if hasattr(memory_manager, "get_last_session_summary"):
                    last_session_summary = memory_manager.get_last_session_summary() or ""
            except Exception as e:
                logger.debug(f"Error fetching last session summary: {e}")

        facts_block = "\n".join([f"- {f}" for f in facts_summary]) if facts_summary else "No explicit personal facts recorded yet."
        prefs_block = "\n".join([f"- {p}" for p in preferences_summary]) if preferences_summary else "Standard developer preferences."
        session_block = last_session_summary if last_session_summary else "Active ongoing assistance."

        prompt = f"""
You are J.A.R.V.I.S., the personal AI assistant for Sir.
The user asked: "{query}"

Here is what you know from long-term memory:
- User Known Facts & History:
{facts_block}

- User Preferences:
{prefs_block}

- Recent Session Context:
{session_block}

Answer Sir warmly, accurately, and naturally in J.A.R.V.I.S. character (in Hinglish if addressed in Hindi/Hinglish, otherwise English).
Summarize what you know about Sir, their current projects, and preferences clearly in 2-4 sentences.
"""
        try:
            response = await llm_generator_fn(prompt)
            if response and response.strip():
                return response.strip()
        except Exception as e:
            logger.warning(f"Failed to generate direct memory response: {e}")

        if facts_summary or last_session_summary:
            items = facts_summary[:3]
            if last_session_summary:
                items.append(f"Recent work: {last_session_summary}")
            return f"Sir, I have recorded our ongoing work and preferences: " + "; ".join(items)
        return "Sir, I know you as my creator and primary user. I am continuously learning your preferences as we collaborate."

    @classmethod
    async def handle_direct_conversation_or_qa(
        cls,
        query: str,
        llm_generator_fn,
        memory_context: str = "",
        preferred_language: Optional[str] = "Hinglish",
    ) -> str:
        """
        Generates a direct, crisp, persona-grounded response for general chit-chat and Q&A.
        """
        prompt = f"""
You are J.A.R.V.I.S., the advanced personal AI assistant for Sir.
User input: "{query}"

Context / Recent Memory:
{memory_context if memory_context else "All core systems operating normally."}

Guidelines:
1. Respond concisely, politely, and intelligently in J.A.R.V.I.S. character.
2. Language: Natural Hinglish (Latin script) if addressed in Hindi/Hinglish, or clear English if addressed in English.
3. Keep conversational replies under 3 sentences. For technical explanations or code examples, provide clear, concise answers.
"""
        try:
            response = await llm_generator_fn(prompt)
            if response and response.strip():
                return response.strip()
        except Exception as e:
            logger.warning(f"Failed to generate direct conversation response: {e}")

        return "Hello Sir! All systems are online and standing by for your commands."
