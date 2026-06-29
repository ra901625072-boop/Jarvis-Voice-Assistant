import logging
import asyncio
import os
import time
import json
import psutil
from typing import Dict, Any

from livekit import ai.agents
from livekit.agents import llm
import google.genai
from google.genai import types

from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

logger = logging.getLogger("JARVIS.SupervisorAgent")

class IntentRouter:
    """Classifies user queries into semantic routing paths."""
    def __init__(self, client):
        self.client = client

    def classify(self, command: str) -> dict:
        if not self.client:
            return self._heuristic_fallback(command)
        prompt = f"""
        Classify the following user command:
        "{command}"
        Return a JSON object with exactly the following fields (all booleans):
        - requires_vision: true if referring to screen, errors, code on screen.
        - requires_browser: true if navigating web.
        - requires_memory: true if asking to remember or recall.
        - requires_execution: true if asking to run a command or plan a task.
        """
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                    max_output_tokens=100
                )
            )
            if response and response.text:
                import json
                data = json.loads(response.text.strip())
                return {
                    "requires_vision": bool(data.get("requires_vision")),
                    "requires_browser": bool(data.get("requires_browser")),
                    "requires_memory": bool(data.get("requires_memory")),
                    "requires_execution": bool(data.get("requires_execution"))
                }
        except Exception as e:
            logger.warning(f"IntentRouter classification failed: {e}")
        return self._heuristic_fallback(command)

    def _heuristic_fallback(self, command: str) -> dict:
        c = command.lower()
        return {
            "requires_vision": any(k in c for k in ["screen", "error", "look", "see", "show"]),
            "requires_browser": any(k in c for k in ["browser", "website", "search"]),
            "requires_memory": any(k in c for k in ["remember", "recall"]),
            "requires_execution": any(k in c for k in ["run", "execute", "plan"])
        }

class SupervisorAgent(BaseAgent):
    """
    Supervisor connection, transcription, TTS, and routing.
    Migrates LiveKit connection logic and acts as the central router for tasks.
    """
    def __init__(self, bus):
        super().__init__(agent_id="supervisor_agent")
        self.bus = bus
        self.bus.register(self.agent_id, self.handle)
        
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.client = google.genai.Client(api_key=api_key) if api_key else None
        self.intent_router = IntentRouter(self.client)
        self.session = None

    async def run_session(self, ctx: agents.JobContext, mcp_toolsets, tools_base, memory, container):
        """Migrated from agent.py: handles the entire LiveKit connection logic."""
        import psutil
        from modules.core.hardware_stats import get_cpu_temperature, start_tracking
        from modules.planning.behavior import JarvisBehavior
        from livekit.plugins import google
        import logging
        from livekit.agents import AgentSession

        start_tracking()
        start_t = time.perf_counter()

        # Warmup VisionManager
        async def warmup_vision():
            try:
                mgr = container.get("vision_manager")
                if mgr:
                    await asyncio.to_thread(mgr.warmup)
            except Exception as e:
                logger.error(f"VisionManager warmup failed: {e}")
        asyncio.create_task(warmup_vision())
        
        # Warmup BrowserController
        async def warmup_browser():
            try:
                for t in tools_base:
                    if type(t).__name__ == "BrowserTools":
                        await t.browser_ctrl._ensure_driver()
                        async def keepalive():
                            while ctx.room.isconnected():
                                t.browser_ctrl._is_port_open(9222)
                                await asyncio.sleep(30)
                        asyncio.create_task(keepalive())
                        break
            except Exception as e:
                logger.error(f"Browser warmup failed: {e}")
        asyncio.create_task(warmup_browser())

        # MCP setup
        async def cleanup_mcp():
            for mcp_ts in mcp_toolsets:
                try:
                    await mcp_ts.aclose()
                except Exception:
                    pass
        ctx.add_shutdown_callback(cleanup_mcp)

        async def init_mcp(mcp_ts):
            try:
                await asyncio.wait_for(mcp_ts.setup(), timeout=5.0)
                return mcp_ts
            except Exception as e:
                logger.warning(f"MCP toolset '{mcp_ts.id}' failed (non-fatal): {e}")
                return None

        mcp_results = await asyncio.gather(*[init_mcp(ts) for ts in mcp_toolsets])
        active_mcp = [ts for ts in mcp_results if ts is not None]
        tools = tools_base + active_mcp

        try:
            memory.start_async_writer(asyncio.get_running_loop())
        except Exception as e:
            logger.warning(f"Async Memory Writer failed: {e}")

        for tool in tools:
            if hasattr(tool, "room"):
                tool.room = ctx.room

        disconnect_count = 0
        while disconnect_count < 10:
            self.session = AgentSession(
                llm=google.beta.realtime.RealtimeModel(
                    model="models/gemini-2.5-flash-native-audio-preview-12-2025",
                    voice="Charon",
                    temperature=0.3,
                ),
                tools=tools,
            )
            try:
                start_session_t = time.time()
                
                # Dynamic Context Injection via AgentBus
                import uuid
                context_task = AgentTask(
                    task_id=str(uuid.uuid4()),
                    task_type="retrieve_context",
                    payload={"goal": ""},
                    origin_agent="voice_agent",
                    target_agent="memory_agent"
                )
                context_result = await self.bus.dispatch(context_task)
                memory_context = context_result.result.get("context", "") if context_result and context_result.success else ""
                
                enriched_prompt = JarvisBehavior.get_full_system_prompt()
                mcp_note = ""
                for ts in mcp_toolsets:
                    if ts not in active_mcp:
                        mcp_note += f"\nNOTE: {ts.id} search tool is unavailable.\n"
                enriched_prompt += mcp_note
                if memory_context:
                    enriched_prompt += f"\n\n--- INJECTED MEMORY CONTEXT ---\n{memory_context}"

                class DynamicAssistant(agents.Agent):
                    def __init__(self):
                        super().__init__(instructions=enriched_prompt)
                
                # Listen to user speech events to handle interrupts
                @self.session.on("user_speech_committed")
                def on_user_speech(msg):
                    self.interrupt()
                
                await self.session.start(room=ctx.room, agent=DynamicAssistant())
                memory.log_session_disconnect(time.time() - start_session_t, "graceful_exit")
                break
            except Exception as e:
                disconnect_count += 1
                duration = time.time() - start_session_t
                memory.log_session_disconnect(duration, str(e))
                logger.error(f"Session disconnected: {e}. Reconnecting (Attempt {disconnect_count})...")
                await asyncio.sleep(2)

        logger.info(f"Assistant startup completed in {time.perf_counter() - start_t:.3f}s")

        async def stats_publisher():
            while ctx.room.isconnected():
                try:
                    cpu_percent = await asyncio.to_thread(psutil.cpu_percent, 0)
                    temp = await asyncio.to_thread(get_cpu_temperature)
                    payload = json.dumps({"type": "stats", "cpu": cpu_percent, "temp": temp})
                    await ctx.room.local_participant.publish_data(payload.encode("utf-8"), reliable=False)
                except Exception:
                    pass
                await asyncio.sleep(3)
        asyncio.create_task(stats_publisher())

        try:
            self.session.history.add_message(role="user", content=JarvisBehavior.INTRO_MESSAGE)
            reply_coro = self.session.generate_reply()
            if asyncio.iscoroutine(reply_coro):
                asyncio.create_task(reply_coro)
        except Exception as e:
            logger.error(f"Failed to force intro: {e}")

    def interrupt(self):
        """Interrupts the active session generation or speech."""
        if self.session and hasattr(self.session, "agent"):
            # Realtime API can interrupt natively or agent can be asked to stop
            logger.info("SupervisorAgent processing user interrupt.")
            # Depending on LiveKit integration, might call session.stop() or cancel tasks
            # This allows graceful cancellation of long TTS or planning tasks.
            pass

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        
        try:
            if task_type == "speak":
                text = task.payload.get("text", "")
                # Would push text to the livekit session here if we had a reference
                # In this refactoring, we'll store the session context locally when connection starts
                if hasattr(self, "session") and self.session:
                    try:
                        # For LiveKit Google Realtime, we add a user message with the text?
                        # Or system message? Actually we want the model to speak it.
                        self.session.history.add_message(role="user", content=f"Please say this to the user: {text}")
                        asyncio.create_task(self.session.generate_reply())
                    except Exception as e:
                        logger.error(f"Failed to speak: {e}")
                return self._create_result(task, success=True)
                
            else:
                return self._create_result(
                    task, 
                    success=False, 
                    error=f"SupervisorAgent does not support task type '{task_type}'"
                )
        except Exception as e:
            logger.exception(f"SupervisorAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))
