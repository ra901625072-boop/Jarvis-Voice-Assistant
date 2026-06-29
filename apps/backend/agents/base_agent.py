from abc import ABC, abstractmethod
from typing import Any, Optional
import os
import asyncio
import json
from google import genai
from google.genai import types
from agents.types import AgentTask, AgentResult

class BaseAgent(ABC):
    """
    Abstract base class for all JARVIS specialist agents.
    """
    def __init__(self, agent_id: str):
        self.agent_id = agent_id

    @property
    def gemini_client(self) -> Optional[genai.Client]:
        if not hasattr(BaseAgent, "_gemini_client_instance"):
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            BaseAgent._gemini_client_instance = genai.Client(api_key=api_key) if api_key else None
        return BaseAgent._gemini_client_instance

    async def generate_response(
        self, prompt: str, system_instruction: Optional[str] = None, model: str = "gemini-2.5-flash", response_mime_type: Optional[str] = None
    ) -> str:
        client = self.gemini_client
        if not client:
            raise RuntimeError("Gemini client not initialized. Check API keys.")

        config = types.GenerateContentConfig(
            temperature=0.2,
            system_instruction=system_instruction,
            response_mime_type=response_mime_type
        )
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=prompt,
            config=config
        )
        if response and response.text:
            return response.text.strip()
        raise ValueError("Empty response from Gemini")

    @abstractmethod
    async def handle(self, task: AgentTask) -> AgentResult:
        """
        Handle an incoming task and return a result.
        """
        pass
        
    def _create_result(self, task: AgentTask, success: bool, result: Any = None, error: Optional[str] = None, duration_ms: float = 0.0) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            success=success,
            result=result,
            error=error,
            duration_ms=duration_ms
        )

    def _parse_json_response(self, response: str) -> dict:
        """Safely parse JSON from Gemini response, handling markdown code fences."""
        cleaned = response.strip()
        # Strip ```json ... ``` or ``` ... ``` fences
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:])
            cleaned = cleaned.rstrip("`").strip()
        return json.loads(cleaned)

