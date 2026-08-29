import os
import logging
import asyncio
import tempfile
import json
try:
    import pyautogui
except Exception:
    pyautogui = None
from typing import Optional, Dict, Any
from google import genai
from google.genai import types
from tools.builtin.base import JarvisToolset
from config.settings import DEFAULT_GEMINI_MODEL, GEMINI_FALLBACK_CHAIN, OPENROUTER_FREE_FALLBACK_CHAIN

# ── Module-level shared singletons ──────────────────────────────────────────
# Instantiated once at module load; all skill classes share the same object.
# Previously each skill class had its own _shared_file_mgr / _shared_folder_mgr
# which caused 15 separate FileManager + FolderManager inits on startup (~15s).
_module_file_mgr = None
_module_folder_mgr = None

def _get_module_file_mgr():
    from container import ServiceContainer
    container = ServiceContainer.instance()
    if container:
        try:
            return container.get("file_manager")
        except KeyError:
            pass
    global _module_file_mgr
    if _module_file_mgr is None:
        from modules.filesystem.file_manager import FileManager
        _module_file_mgr = FileManager()
    return _module_file_mgr

def _get_module_folder_mgr():
    from container import ServiceContainer
    container = ServiceContainer.instance()
    if container:
        try:
            return container.get("folder_manager")
        except KeyError:
            pass
    global _module_folder_mgr
    if _module_folder_mgr is None:
        from modules.filesystem.folder_manager import FolderManager
        _module_folder_mgr = FolderManager(file_mgr=_get_module_file_mgr())
    return _module_folder_mgr

_active_resource_tasks = {}


class BaseSkill(JarvisToolset):
    """
    Base class for all JARVIS high-level autonomous skills.
    Provides standard utilities for image analysis, text generation, screen capturing,
    and process execution.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None):
        # Initialize JarvisToolset with the lowercase class name as the toolset ID
        super().__init__(security=security, room=room)
        self.memory = memory
        self.verification = verification
        self.logger = logging.getLogger(f"JARVIS.Skills.{self.__class__.__name__}")

    def _get_agent_bus(self):
        """Retrieve the global AgentBus instance from the container."""
        from container import ServiceContainer
        container = ServiceContainer.instance()
        if not container:
            return None
        return container.get_or_none("agent_bus")

    async def cancel_active_task(self, resource_key: str):
        """Cancel any active task currently operating on the specified resource_key."""
        import asyncio
        norm_key = os.path.normpath(os.path.abspath(resource_key))
        current_task = asyncio.current_task()
        
        if norm_key in _active_resource_tasks:
            prev_task = _active_resource_tasks[norm_key]
            if prev_task and not prev_task.done() and prev_task != current_task:
                self.logger.info(
                    f"Interruption or cancellation detected for resource {resource_key}! "
                    f"Cancelling previous running task: {prev_task.get_name() if hasattr(prev_task, 'get_name') else prev_task}"
                )
                prev_task.cancel()
                try:
                    # Await it to ensure it completes its cancellation cleanup
                    await prev_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    self.logger.warning(f"Exception while cancelling previous task: {e}")

    def register_active_task(self, resource_key: str):
        """Register the current task as active for the specified resource_key."""
        import asyncio
        norm_key = os.path.normpath(os.path.abspath(resource_key))
        _active_resource_tasks[norm_key] = asyncio.current_task()

    def unregister_active_task(self, resource_key: str):
        """Unregister the current task for the specified resource_key."""
        import asyncio
        norm_key = os.path.normpath(os.path.abspath(resource_key))
        current_task = asyncio.current_task()
        if _active_resource_tasks.get(norm_key) == current_task:
            _active_resource_tasks.pop(norm_key, None)

    @property
    def file_mgr(self):
        """Shared module-level FileManager — all skill classes use the same instance."""
        return _get_module_file_mgr()

    @property
    def folder_mgr(self):
        """Shared module-level FolderManager — all skill classes use the same instance."""
        return _get_module_folder_mgr()

    def clean_and_parse_json(self, text: str) -> Any:
        """Cleans markdown code block wrappers and parses JSON from Gemini responses."""
        if not text:
            raise ValueError("Empty response text")
        import re
        clean = text.strip()
        fence_match = re.search(r"```(?:json)?\s*([\{\[].*?[\}\]])\s*```", clean, re.DOTALL)
        if fence_match:
            clean = fence_match.group(1)
        else:
            first_obj = clean.find("{")
            first_arr = clean.find("[")
            start = -1
            if first_obj != -1 and first_arr != -1:
                start = min(first_obj, first_arr)
            elif first_obj != -1:
                start = first_obj
            elif first_arr != -1:
                start = first_arr
            
            if start != -1:
                last_obj = clean.rfind("}")
                last_arr = clean.rfind("]")
                end = max(last_obj, last_arr)
                if end > start:
                    clean = clean[start:end+1]

        clean = re.sub(r",\s*([\}\]])", r"\1", clean)
        try:
            return json.loads(clean)
        except Exception:
            lines = clean.splitlines()
            if len(lines) > 2:
                repaired = "\n".join(lines[:-1])
                repaired = re.sub(r",\s*$", "", repaired).strip()
                open_braces = repaired.count("{") - repaired.count("}")
                repaired += "}" * max(0, open_braces)
                return json.loads(repaired)
            raise

    @property
    def gemini_client(self) -> Optional[genai.Client]:
        """Lazy-loaded, class-level cached Gemini API client. Creates only one per process."""
        if not hasattr(BaseSkill, "_gemini_client_instance"):
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            BaseSkill._gemini_client_instance = genai.Client(api_key=api_key) if api_key else None
        return BaseSkill._gemini_client_instance

    async def _generate_direct_llm(self, prompt: str, system_instruction: Optional[str] = None, response_mime_type: Optional[str] = None) -> Optional[str]:
        import os
        import requests
        import asyncio
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        
        # 1. Try Groq
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            import logging
            logger = logging.getLogger("JARVIS.BaseSkill")
            for groq_model in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b", "qwen/qwen3.8-27b", "groq/compound"]:
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
                        "max_tokens": 1500
                    }
                    # Disable strict JSON mode for Groq to avoid 400 validation failures on formatting.
                    # Our clean/fallback JSON parsers will extract the JSON blocks reliably.
                    res = await asyncio.to_thread(
                        requests.post,
                        "https://api.groq.com/openai/v1/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=60
                    )
                    if res.status_code == 200:
                        return res.json()["choices"][0]["message"]["content"].strip()
                    elif res.status_code == 429:
                        logger.warning(f"Direct LLM Groq ({groq_model}) rate limited (429). Retrying in 2.5 seconds...")
                        await asyncio.sleep(2.5)
                        res = await asyncio.to_thread(
                            requests.post,
                            "https://api.groq.com/openai/v1/chat/completions",
                            json=payload,
                            headers=headers,
                            timeout=60
                        )
                        if res.status_code == 200:
                            return res.json()["choices"][0]["message"]["content"].strip()
                    logger.warning(f"Direct LLM Groq ({groq_model}) status {res.status_code}: {res.text}")
                except Exception as e:
                    logger.warning(f"Direct LLM Groq ({groq_model}) exception: {e}")
                
        # 2. Try OpenAI
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 1500
                }
                if response_mime_type == "application/json":
                    payload["response_format"] = {"type": "json_object"}
                res = await asyncio.to_thread(
                    requests.post,
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=60
                )
                if res.status_code == 200:
                    return res.json()["choices"][0]["message"]["content"].strip()
                else:
                    import logging
                    logging.getLogger("JARVIS.BaseSkill").warning(f"Direct LLM OpenAI status {res.status_code}: {res.text}")
            except Exception as e:
                import logging
                logging.getLogger("JARVIS.BaseSkill").warning(f"Direct LLM OpenAI exception: {e}")

        # 3. Try DeepSeek
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key:
            try:
                headers = {"Authorization": f"Bearer {deepseek_key}", "Content-Type": "application/json"}
                payload = {
                    "model": "deepseek-chat",
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": 1500
                }
                if response_mime_type == "application/json":
                    payload["response_format"] = {"type": "json_object"}
                res = await asyncio.to_thread(
                    requests.post,
                    "https://api.deepseek.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=60
                )
                if res.status_code == 200:
                    return res.json()["choices"][0]["message"]["content"].strip()
                else:
                    import logging
                    logging.getLogger("JARVIS.BaseSkill").warning(f"Direct LLM DeepSeek status {res.status_code}: {res.text}")
            except Exception as e:
                import logging
                logging.getLogger("JARVIS.BaseSkill").warning(f"Direct LLM DeepSeek exception: {e}")

        return None

    async def generate_response(
        self, prompt: str, system_instruction: Optional[str] = None, model: Optional[str] = None, response_mime_type: Optional[str] = None
    ) -> str:
        """Call the Gemini API to generate text based on a prompt."""
        if model is None:
            model = DEFAULT_GEMINI_MODEL
        # Check direct LLM keys (OpenAI, Groq, DeepSeek) first to bypass all Gemini daily quota limits!
        direct_res = await self._generate_direct_llm(prompt, system_instruction, response_mime_type)
        if direct_res:
            return direct_res

        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key:
            try:
                # Route based on skill class name: debugging/self-healing skills use DeepSeek R1, others use Qwen3 Coder
                skill_name = self.__class__.__name__
                or_model = "deepseek/deepseek-r1" if ("Debugging" in skill_name or "SelfHealing" in skill_name) else "qwen/qwen3-coder"

                from modules.shared.openrouter_text import generate_openrouter_text
                result = await asyncio.to_thread(
                    generate_openrouter_text,
                    prompt=prompt,
                    system_instruction=system_instruction,
                    model=or_model,
                    response_mime_type=response_mime_type
                )
                return result
            except Exception as e:
                self.logger.warning(
                    f"OpenRouter query failed: {e}. Falling back to Gemini..."
                )

        client = self.gemini_client
        if not client:
            return "Error: Neither OpenRouter nor Gemini clients are initialized. Check API keys in environment."

        model_rotation = [model]
        for fb in GEMINI_FALLBACK_CHAIN:
            if fb != model and fb not in model_rotation:
                model_rotation.append(fb)

        last_err = None
        for attempt in range(len(model_rotation)):
            current_model = model_rotation[attempt % len(model_rotation)]
            try:
                config = types.GenerateContentConfig(
                    temperature=0.2,
                    system_instruction=system_instruction,
                    response_mime_type=response_mime_type
                )
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=current_model,
                    contents=prompt,
                    config=config
                )
                if response and response.text:
                    return response.text.strip()
                last_err = "Empty response from Gemini."
            except Exception as e:
                last_err = str(e)
                is_429 = "429" in last_err or "RESOURCE_EXHAUSTED" in last_err or "quota" in last_err.lower()
                is_503 = "503" in last_err or "UNAVAILABLE" in last_err or "demand" in last_err.lower()
                is_404 = "404" in last_err or "NOT_FOUND" in last_err or "not found" in last_err.lower()
                
                if is_429 or is_503 or is_404:
                    import re
                    wait_time = 0.0 if is_404 else 2.0
                    match = re.search(r"retry in (\d+\.?\d*)s", last_err)
                    if match:
                        wait_time = float(match.group(1)) + 0.5
                        if wait_time > 30.0:
                            wait_time = 30.0
                    self.logger.warning(f"BaseSkill: Rate limit/error on model '{current_model}' ({last_err[:80]}). Retrying in {wait_time:.2f}s...")
                    if wait_time > 0:
                        await asyncio.sleep(wait_time)
                else:
                    # If Gemini models failed/exhausted, attempt OpenRouter free model fallback before raising error
                    openrouter_key = os.getenv("OPENROUTER_API_KEY")
                    if openrouter_key:
                        free_models = OPENROUTER_FREE_FALLBACK_CHAIN
                        for or_model in free_models:
                            try:
                                from modules.shared.openrouter_text import generate_openrouter_text
                                self.logger.warning(f"BaseSkill: Trying OpenRouter model '{or_model}' fallback...")
                                res_text = await asyncio.to_thread(
                                    generate_openrouter_text,
                                    prompt=prompt,
                                    system_instruction=system_instruction,
                                    model=or_model,
                                    response_mime_type=response_mime_type
                                )
                                if res_text:
                                    return res_text
                            except Exception as or_err:
                                self.logger.warning(f"OpenRouter model '{or_model}' fallback failed: {or_err}")
                                continue
                    raise e
                    
        # Final fallback check if loop finished without raising
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key:
            free_models = OPENROUTER_FREE_FALLBACK_CHAIN
            for or_model in free_models:
                try:
                    from modules.shared.openrouter_text import generate_openrouter_text
                    self.logger.warning(f"BaseSkill: Trying OpenRouter model '{or_model}' fallback...")
                    res_text = await asyncio.to_thread(
                        generate_openrouter_text,
                        prompt=prompt,
                        system_instruction=system_instruction,
                        model=or_model,
                        response_mime_type=response_mime_type
                    )
                    if res_text:
                        return res_text
                except Exception as or_err:
                    self.logger.warning(f"OpenRouter model '{or_model}' fallback failed: {or_err}")
                    continue

        self.logger.error(f"Gemini API text generation error: {last_err}")
        return f"Error: {last_err}"

    async def analyze_image(
        self, image_path: str, prompt: str, model: Optional[str] = None, response_mime_type: Optional[str] = None
    ) -> str:
        """Call Vision API to analyze an image, trying OpenRouter Vision first and falling back to Gemini model rotation."""
        if model is None:
            model = DEFAULT_GEMINI_MODEL

        from PIL import Image
        import io, base64

        def _get_bytes():
            with Image.open(image_path) as pil_img:
                buf = io.BytesIO()
                pil_img.save(buf, format="JPEG", quality=85)
                return buf.getvalue()

        image_bytes = await asyncio.to_thread(_get_bytes)

        # 1. Try OpenRouter Vision if API key is present
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key:
            try:
                base64_image = base64.b64encode(image_bytes).decode("utf-8")
                from modules.vision.openrouter_vision import OpenRouterVisionClient
                or_client = OpenRouterVisionClient()
                or_res = await asyncio.to_thread(or_client.analyze_image, base64_image, prompt)
                if or_res and not str(or_res).startswith("Error:"):
                    return str(or_res).strip()
                self.logger.warning(f"OpenRouter Vision fallback returned error/empty: {or_res}. Falling back to Gemini...")
            except Exception as e:
                self.logger.warning(f"OpenRouter Vision query failed: {e}. Falling back to Gemini...")

        # 2. Try Gemini with model rotation on 429/quota exhaustion
        client = self.gemini_client
        if not client:
            return "Error: Neither OpenRouter nor Gemini clients are initialized. Check API keys."

        models_to_try = [model] + [m for m in GEMINI_FALLBACK_CHAIN if m != model]

        seen_models = []
        for m in models_to_try:
            if m not in seen_models:
                seen_models.append(m)

        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        text_part = types.Part.from_text(text=prompt)

        last_error = None
        for current_model in seen_models:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=current_model,
                    contents=[image_part, text_part],
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        response_mime_type=response_mime_type
                    )
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                last_error = str(e)
                if "429" in last_error or "RESOURCE_EXHAUSTED" in last_error or "quota" in last_error.lower():
                    self.logger.warning(f"Gemini Vision model '{current_model}' hit quota (429). Rotating to next model...")
                    await asyncio.sleep(1.0)
                    continue
                else:
                    self.logger.error(f"Gemini Vision model '{current_model}' error: {e}")
                    break

        return f"Error: Vision analysis failed across models. Last error: {last_error}"


    async def capture_screen(self) -> str:
        """Capture the screen and return the file path of the saved JPEG image."""
        temp_file = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        temp_path = temp_file.name
        temp_file.close()

        def _do_capture():
            screenshot = pyautogui.screenshot()
            screenshot = screenshot.convert("RGB")
            screenshot.thumbnail((1600, 900))
            screenshot.save(temp_path, "JPEG", quality=75, optimize=True)
            return temp_path

        path = await asyncio.to_thread(_do_capture)

        # Schedule automatic cleanup in background after 60 seconds to prevent temp file leaks
        async def _auto_cleanup():
            await asyncio.sleep(60.0)
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

        asyncio.create_task(_auto_cleanup())
        return path

    async def run_shell_command(self, cmd, cwd: Optional[str] = None, timeout: Optional[float] = 300.0) -> Dict[str, Any]:
        """Execute a system shell command or executable list and return stdout, stderr, and code."""
        try:
            if isinstance(cmd, list):
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd
                )
            
            try:
                if timeout:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                else:
                    stdout, stderr = await process.communicate()
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except Exception:
                    pass
                stdout, stderr = await process.communicate()
                return {
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace") + f"\nError: Command timed out after {timeout} seconds.",
                    "returncode": -1
                }
                
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": process.returncode
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": str(e),
                "returncode": -1
            }
