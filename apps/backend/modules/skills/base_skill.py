import os
import logging
import asyncio
import tempfile
import json
import pyautogui
from typing import Optional, Dict, Any, List
from google import genai
from google.genai import types
from livekit.agents import llm
from tools.builtin.base import JarvisToolset

# ── Module-level shared singletons ──────────────────────────────────────────
# Instantiated once at module load; all skill classes share the same object.
# Previously each skill class had its own _shared_file_mgr / _shared_folder_mgr
# which caused 15 separate FileManager + FolderManager inits on startup (~15s).
_module_file_mgr = None
_module_folder_mgr = None

def _get_module_file_mgr():
    global _module_file_mgr
    if _module_file_mgr is None:
        from modules.filesystem.file_manager import FileManager
        _module_file_mgr = FileManager()
    return _module_file_mgr

def _get_module_folder_mgr():
    global _module_folder_mgr
    if _module_folder_mgr is None:
        from modules.filesystem.folder_manager import FolderManager
        _module_folder_mgr = FolderManager(file_mgr=_get_module_file_mgr())
    return _module_folder_mgr

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
        
        clean = text.strip()
        if clean.startswith("```"):
            first_nl = clean.find("\n")
            if first_nl != -1:
                clean = clean[first_nl:].strip()
            if clean.endswith("```"):
                clean = clean[:-3].strip()
                
        if clean.startswith("json\n"):
            clean = clean[5:].strip()
            
        return json.loads(clean)

    @property
    def gemini_client(self) -> Optional[genai.Client]:
        """Lazy-loaded, class-level cached Gemini API client. Creates only one per process."""
        if not hasattr(BaseSkill, "_gemini_client_instance"):
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            BaseSkill._gemini_client_instance = genai.Client(api_key=api_key) if api_key else None
        return BaseSkill._gemini_client_instance

    async def generate_response(
        self, prompt: str, system_instruction: Optional[str] = None, model: str = "gemini-2.5-flash", response_mime_type: Optional[str] = None
    ) -> str:
        """Call the Gemini API to generate text based on a prompt."""
        client = self.gemini_client
        if not client:
            return "Error: Gemini client not initialized. Check API keys in environment."

        try:
            config = types.GenerateContentConfig(
                temperature=0.2,
                system_instruction=system_instruction,
                response_mime_type=response_mime_type
            )
            # Run blocking call in thread pool to prevent blocking agent event loop
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=prompt,
                config=config
            )
            if response and response.text:
                return response.text.strip()
            return "Error: Empty response from Gemini."
        except Exception as e:
            self.logger.error(f"Gemini API text generation error: {e}")
            return f"Error: {e}"

    async def analyze_image(
        self, image_path: str, prompt: str, model: str = "gemini-2.5-flash", response_mime_type: Optional[str] = None
    ) -> str:
        """Call the Gemini Vision API to analyze an image with a custom prompt."""
        client = self.gemini_client
        if not client:
            return "Error: Gemini client not initialized. Check API keys in environment."

        try:
            from PIL import Image
            import io

            # Load and optimize image internally for transmission speed
            def _get_bytes():
                with Image.open(image_path) as pil_img:
                    buf = io.BytesIO()
                    pil_img.save(buf, format="JPEG", quality=85)
                    return buf.getvalue()

            image_bytes = await asyncio.to_thread(_get_bytes)
            image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
            text_part = types.Part.from_text(text=prompt)

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=[image_part, text_part],
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type=response_mime_type
                )
            )
            if response and response.text:
                return response.text.strip()
            return "Error: Empty response from Gemini."
        except Exception as e:
            self.logger.error(f"Gemini API vision analysis error: {e}")
            return f"Error: {e}"

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
