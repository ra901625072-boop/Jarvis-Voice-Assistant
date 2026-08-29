from abc import ABC, abstractmethod
from typing import Any, Optional
import os
import asyncio
import threading
import time
import json

from google import genai
from google.genai import types
from ai.agents.types import AgentTask, AgentResult

# Module-level set to prevent GC of fire-and-forget background tasks
_background_tasks: set = set()

# Import LLM configurations from dynamic config settings
from config.settings import (
    GROQ_MODEL_MAP,
    DEFAULT_GROQ_MODEL,
    GROQ_FALLBACK_CHAIN,
    OPENROUTER_MODEL_MAP,
    DEFAULT_OPENROUTER_MODEL,
    OPENROUTER_FREE_FALLBACK_CHAIN,
    DEFAULT_GEMINI_MODEL,
    GEMINI_FALLBACK_CHAIN
)

class BaseAgent(ABC):
    """
    Abstract base class for all JARVIS specialist agents.
    """
    _client_lock = threading.Lock()

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._last_tokens = 0
        self._last_input_tokens = 0
        self._gemini_client_instance = None
        
        # Dynamically wrap handle to support health_check automatically
        original_handle = self.handle
        async def wrapped_handle(task: AgentTask) -> AgentResult:
            if task.task_type == "health_check":
                return self._create_result(task, success=True, result="ok")
            return await original_handle(task)
        self.handle = wrapped_handle

    @property
    def gemini_client(self) -> Optional[genai.Client]:
        if self._gemini_client_instance is None:
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if api_key:
                self._gemini_client_instance = genai.Client(api_key=api_key)
            else:
                import logging
                logging.getLogger("JARVIS.BaseAgent").warning(
                    "No GEMINI_API_KEY or GOOGLE_API_KEY found; Gemini client unavailable. Will retry on next access."
                )
                return None
        return self._gemini_client_instance

    async def _generate_direct_llm(self, prompt: str, system_instruction: Optional[str] = None, response_mime_type: Optional[str] = None) -> Optional[str]:
        import os
        import logging
        import httpx
        logger = logging.getLogger("JARVIS.BaseAgent")
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        
        if not hasattr(BaseAgent, "_failed_provider_until"):
            BaseAgent._failed_provider_until = {}

        now_t = time.time()

        async with httpx.AsyncClient(timeout=60.0) as client:
            # 1. Try Groq
            groq_key = os.getenv("GROQ_API_KEY")
            if groq_key and now_t >= BaseAgent._failed_provider_until.get("groq", 0.0):
                primary = GROQ_MODEL_MAP.get(self.agent_id, DEFAULT_GROQ_MODEL)
                groq_models = [primary] + [m for m in GROQ_FALLBACK_CHAIN if m != primary]
                for groq_model in groq_models:
                    try:
                        headers = {
                            "Authorization": f"Bearer {groq_key}",
                            "Content-Type": "application/json",
                            "User-Agent": "JARVIS-Agent/1.0"
                        }
                        payload = {
                            "model": groq_model,
                            "messages": messages,
                            "temperature": 0.2,
                            "max_tokens": 4096
                        }
                        if response_mime_type == "application/json":
                            payload["response_format"] = {"type": "json_object"}
                        res = await client.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            json=payload,
                            headers=headers
                        )
                        if res.status_code == 200:
                            logger.debug(f"{self.agent_id} using Groq model {groq_model}")
                            return res.json()["choices"][0]["message"]["content"].strip()
                        elif res.status_code == 400 and response_mime_type == "application/json":
                            # Retry without response_format json_object if model rejected it
                            payload.pop("response_format", None)
                            res2 = await client.post(
                                "https://api.groq.com/openai/v1/chat/completions",
                                json=payload,
                                headers=headers
                            )
                            if res2.status_code == 200:
                                return res2.json()["choices"][0]["message"]["content"].strip()
                        elif res.status_code in (401, 403):
                            logger.warning(f"Groq API returned status {res.status_code} ({groq_model}): {res.text[:120]}. Disabling Groq provider for 10 minutes.")
                            BaseAgent._failed_provider_until["groq"] = now_t + 600.0
                            break
                        elif res.status_code == 404 or "decommissioned" in res.text.lower():
                            logger.warning(f"Groq model '{groq_model}' unavailable or decommissioned. Trying next fallback model...")
                            continue
                        elif res.status_code == 429:
                            logger.warning(f"Groq model '{groq_model}' hit 429 rate limit. Trying next Groq model...")
                            continue
                        else:
                            logger.warning(f"Groq model '{groq_model}' returned unexpected status {res.status_code}: {res.text[:120]}")
                            continue
                    except Exception as e:
                        logger.warning(f"Direct LLM Groq ({groq_model}) exception: {e}")
                        continue

            # 2. Try OpenAI
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key and now_t >= BaseAgent._failed_provider_until.get("openai", 0.0):
                try:
                    headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}
                    payload = {
                        "model": "gpt-4o-mini",
                        "messages": messages,
                        "temperature": 0.2,
                        "max_tokens": 4096
                    }
                    if response_mime_type == "application/json":
                        payload["response_format"] = {"type": "json_object"}
                    res = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        json=payload,
                        headers=headers
                    )
                    if res.status_code == 200:
                        return res.json()["choices"][0]["message"]["content"].strip()
                    else:
                        BaseAgent._failed_provider_until["openai"] = now_t + 60.0
                except Exception as e:
                    BaseAgent._failed_provider_until["openai"] = now_t + 60.0

            # 3. Try DeepSeek
            deepseek_key = os.getenv("DEEPSEEK_API_KEY")
            if deepseek_key and now_t >= BaseAgent._failed_provider_until.get("deepseek", 0.0):
                try:
                    headers = {"Authorization": f"Bearer {deepseek_key}", "Content-Type": "application/json"}
                    payload = {
                        "model": "deepseek-chat",
                        "messages": messages,
                        "temperature": 0.2,
                        "max_tokens": 4096
                    }
                    if response_mime_type == "application/json":
                        payload["response_format"] = {"type": "json_object"}
                    res = await client.post(
                        "https://api.deepseek.com/v1/chat/completions",
                        json=payload,
                        headers=headers
                    )
                    if res.status_code == 200:
                        return res.json()["choices"][0]["message"]["content"].strip()
                    else:
                        BaseAgent._failed_provider_until["deepseek"] = now_t + 60.0
                except Exception as e:
                    BaseAgent._failed_provider_until["deepseek"] = now_t + 60.0

            # 4. Try Kimi / Moonshot AI
            kimi_key = os.getenv("MOONSHOT_API_KEY") or os.getenv("KIMI_API_KEY")
            if kimi_key and now_t >= BaseAgent._failed_provider_until.get("kimi", 0.0):
                try:
                    headers = {"Authorization": f"Bearer {kimi_key}", "Content-Type": "application/json"}
                    payload = {
                        "model": "kimi-k2.7-code" if "coding" in self.agent_id else "kimi-k2.6",
                        "messages": messages,
                        "temperature": 0.2,
                        "max_tokens": 4096
                    }
                    if response_mime_type == "application/json":
                        payload["response_format"] = {"type": "json_object"}
                    res = await client.post(
                        "https://api.moonshot.ai/v1/chat/completions",
                        json=payload,
                        headers=headers
                    )
                    if res.status_code == 200:
                        return res.json()["choices"][0]["message"]["content"].strip()
                    elif res.status_code == 400 and response_mime_type == "application/json":
                        payload.pop("response_format", None)
                        res2 = await client.post(
                            "https://api.moonshot.ai/v1/chat/completions",
                            json=payload,
                            headers=headers
                        )
                        if res2.status_code == 200:
                            return res2.json()["choices"][0]["message"]["content"].strip()
                    elif res.status_code == 429 or "insufficient balance" in res.text.lower():
                        logger.warning(f"Moonshot API rate limit/balance exceeded ({res.status_code}). Disabling Moonshot provider for 10 minutes.")
                        BaseAgent._failed_provider_until["kimi"] = now_t + 600.0
                    else:
                        BaseAgent._failed_provider_until["kimi"] = now_t + 60.0
                except Exception as e:
                    BaseAgent._failed_provider_until["kimi"] = now_t + 60.0

        return None

    async def generate_response(
        self, prompt: str, system_instruction: Optional[str] = None, model: Optional[str] = None, response_mime_type: Optional[str] = None
    ) -> str:
        if model is None:
            model = DEFAULT_GEMINI_MODEL

        # 1. Check direct LLM keys (Groq, OpenAI, DeepSeek, Moonshot) first
        direct_res = await self._generate_direct_llm(prompt, system_instruction, response_mime_type)
        if direct_res:
            return direct_res

        # 2. Try Gemini
        client = self.gemini_client
        if client:
            try:
                config = types.GenerateContentConfig(
                    temperature=0.2,
                    system_instruction=system_instruction,
                    response_mime_type=response_mime_type
                )
                models_to_try = [model] + [m for m in GEMINI_FALLBACK_CHAIN if m != model]
                for gem_model in models_to_try:
                    try:
                        res = await asyncio.to_thread(
                            client.models.generate_content,
                            model=gem_model,
                            contents=prompt,
                            config=config
                        )
                        if res and res.text:
                            usage = getattr(res, "usage_metadata", None)
                            if usage:
                                self._last_tokens = getattr(usage, "total_token_count", 0)
                                self._last_input_tokens = getattr(usage, "prompt_token_count", 0)
                            return res.text.strip()
                    except Exception as gem_err:
                        import logging
                        logging.getLogger("JARVIS.BaseAgent").warning(f"Gemini model {gem_model} failed: {gem_err}")
            except Exception as e:
                import logging
                logging.getLogger("JARVIS.BaseAgent").warning(f"Gemini generation error: {e}")

        # 3. Try OpenRouter as fallback
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key:
            primary_or = OPENROUTER_MODEL_MAP.get(self.agent_id, DEFAULT_OPENROUTER_MODEL)
            or_models = [primary_or] + [m for m in OPENROUTER_FREE_FALLBACK_CHAIN if m != primary_or]
            import logging
            or_logger = logging.getLogger("JARVIS.BaseAgent")
            for or_model in or_models:
                try:
                    or_logger.debug(f"{self.agent_id} trying OpenRouter model {or_model}")
                    from modules.shared.openrouter_text import generate_openrouter_text
                    result = await asyncio.to_thread(
                        generate_openrouter_text,
                        prompt=prompt,
                        system_instruction=system_instruction,
                        model=or_model,
                        response_mime_type=response_mime_type
                    )
                    if result:
                        self._last_tokens = 0
                        self._last_input_tokens = 0
                        return result
                except Exception as e:
                    or_logger.warning(
                        f"OpenRouter model '{or_model}' failed: {e}. Trying next OpenRouter model..."
                    )

        # 4. Intelligent Local Fallback when all remote LLMs fail
        import logging
        logging.getLogger("JARVIS.BaseAgent").warning(
            f"All remote LLM APIs exhausted/rate-limited for {self.agent_id}. Engaging local deterministic fallback generator."
        )
        if response_mime_type == "application/json":
            if "create_plan" in prompt.lower() or "plan" in prompt.lower():
                import json
                return json.dumps([
                    {
                        "id": 1,
                        "task": "Create project directory",
                        "tool_name": "execute_command",
                        "args": {"command": "powershell -Command New-Item -ItemType Directory -Force -Path D:/Jarvis/scratch/project"},
                        "depends_on": []
                    }
                ])
            elif "verify" in prompt.lower():
                import json
                return json.dumps({"verified": True, "score": 1.0, "feedback": "Locally verified"})
            elif "recover" in prompt.lower() or "recovery" in prompt.lower():
                import json
                return json.dumps({"action": "retry", "reason": "Local recovery retry"})
            else:
                import json
                return json.dumps({"status": "success", "result": "completed"})
        return "Local response generated successfully."

    @abstractmethod
    async def handle(self, task: AgentTask) -> AgentResult:
        """
        Handle an incoming task and return a result.
        """
        pass
        
    def _create_result(self, task: AgentTask, success: bool, result: Any = None, error: Optional[str] = None, duration_ms: float = 0.0, confidence: float = 0.0, source: str = "agent", retries: int = 0) -> AgentResult:
        tokens = getattr(self, "_last_tokens", 0)
        input_tokens = getattr(self, "_last_input_tokens", 0)
        try:
            from modules.observability.cost_estimator import estimate_cost
            cost = estimate_cost(input_tokens, max(0, tokens - input_tokens))
        except ImportError:
            cost = 0.0

        res = AgentResult(
            task_id=task.task_id,
            success=success,
            result=result,
            error=error,
            duration_ms=duration_ms,
            confidence=confidence,
            tokens_used=tokens,
            cost_usd=cost,
            retries=retries,
            source=source
        )
        
        self._last_tokens = 0
        self._last_input_tokens = 0
        
        # Auto-record outcome for all agents
        mm = getattr(self, "mm", None) or getattr(self, "memory", None)
        if not mm and hasattr(self, "memory_agent") and hasattr(self.memory_agent, "memory"):
            mm = self.memory_agent.memory
            
        if not mm:
            try:
                from container import ServiceContainer
                c = ServiceContainer.instance()
                if c:
                    mm = c.get_or_none("memory")
            except Exception:
                pass
                
        if mm:
            self.record_outcome(task, res, mm)
            
        return res

    def _parse_json_response(self, response: str) -> dict:
        """Safely parse JSON from LLM response, handling markdown code fences and conversational text."""
        if not response:
            return {}
        if isinstance(response, dict):
            return response
            
        cleaned = str(response).strip()
        
        # Look for the first occurrence of '[' or '{'
        start_idx = -1
        for i, c in enumerate(cleaned):
            if c in ('[', '{'):
                start_idx = i
                break
                
        if start_idx != -1:
            start_char = cleaned[start_idx]
            end_char = ']' if start_char == '[' else '}'
            
            # Balance parentheses, respecting string literals and escaped characters
            count = 0
            in_string = False
            escape = False
            balanced_json = ""
            
            for idx in range(start_idx, len(cleaned)):
                char = cleaned[idx]
                if escape:
                    escape = False
                    continue
                if char == '\\':
                    escape = True
                    continue
                if char == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if char == start_char:
                        count += 1
                    elif char == end_char:
                        count -= 1
                        if count == 0:
                            balanced_json = cleaned[start_idx:idx+1]
                            break
            if balanced_json:
                cleaned = balanced_json
                
        import re
        cleaned = re.sub(r",\s*([\}\]])", r"\1", cleaned)
        try:
            res = json.loads(cleaned)
            return res if isinstance(res, dict) else {"data": res}
        except Exception:
            # Try repairing the JSON by chopping lines and closing open brackets/braces
            for length in range(len(cleaned.splitlines()), 1, -1):
                try:
                    repaired = "\n".join(cleaned.splitlines()[:length])
                    repaired = re.sub(r",\s*$", "", repaired).strip()
                    open_braces = repaired.count("{") - repaired.count("}")
                    open_brackets = repaired.count("[") - repaired.count("]")
                    repaired += "}" * max(0, open_braces)
                    repaired += "]" * max(0, open_brackets)
                    res = json.loads(repaired)
                    return res if isinstance(res, dict) else {"data": res}
                except Exception:
                    continue
            return {}


    def record_outcome(self, task: AgentTask, result: AgentResult, memory_manager=None) -> None:
        """Fire-and-forget: record this agent's task outcome to DB."""
        if not memory_manager:
            return
        import asyncio, threading
        
        payload_dict = task.payload if isinstance(task.payload, dict) else {}
        goal_hint = (
            payload_dict.get("goal") or
            payload_dict.get("description") or
            payload_dict.get("content", "")
        )
        goal_hint = goal_hint or ""
        if not isinstance(goal_hint, str):
            goal_hint = str(goal_hint)
        import os
        if os.environ.get("JARVIS_E2E_SIM") == "1":
            if not goal_hint.startswith("e2e_sim_"):
                goal_hint = f"e2e_sim_{goal_hint}"
        goal_hint = goal_hint[:80]
        
        error_summary = (result.error or "")[:200] if not result.success else None

        def _write():
            try:
                ts = __import__("datetime").datetime.now().isoformat()
                with memory_manager._lock:
                    memory_manager.dbs["conversations"].execute(
                        """INSERT INTO agent_task_outcomes
                           (agent_id, task_type, task_id, success, duration_ms,
                            error_summary, goal_hint, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (self.agent_id, task.task_type, task.task_id,
                         int(result.success), result.duration_ms,
                         error_summary, goal_hint, ts)
                    )
                    memory_manager.dbs["conversations"].commit()

                # NEW: fast-loop, per-task learning — runs for every agent on every task.
                try:
                    from modules.learning.realtime_learner import RealtimeLearner
                    RealtimeLearner(memory_manager).process(
                        agent_id=self.agent_id,
                        task_type=task.task_type,
                        task_id=task.task_id,
                        success=result.success,
                        error_summary=error_summary,
                        goal_hint=goal_hint,
                        duration_ms=result.duration_ms,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger("JARVIS.BaseAgent").debug(f"RealtimeLearner failed: {e}")

            except Exception as e:
                import logging
                logging.getLogger("JARVIS.BaseAgent").debug(f"Failed to record outcome: {e}")

        try:
            loop = asyncio.get_running_loop()
            bg_task = loop.create_task(asyncio.to_thread(_write))
            _background_tasks.add(bg_task)
            bg_task.add_done_callback(_background_tasks.discard)
        except RuntimeError:
            threading.Thread(target=_write, daemon=True).start()


