"""
toolsets/vision_tools.py — VisionTools toolset.

Phase 3.6: VisionTools no longer owns CognitiveCoordinator or ExecutiveController.
All goal/cognitive tools have been moved to MemoryTools.

Phase 5.4: ScreenObserver is event-driven — started on first vision query,
auto-stopped after 30 seconds of no vision tool calls. Feature-flagged behind
JARVIS_LAZY_VISION=true (default true since skills.md recommends it).
"""
import json
import logging
import os
import threading
import time
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.security.manager import SecurityManager

_logger = logging.getLogger("JARVIS.VisionTools")

# Use lazy ScreenObserver by default (feature flag)
_LAZY_VISION = os.environ.get("JARVIS_LAZY_VISION", "true").lower() != "false"
_IDLE_TIMEOUT = 15  # seconds before auto-stopping the observer


class VisionTools(JarvisToolset):
    """
    VisionTools is the function tool suite exposed to the LiveKit LLM agent.
    Delegates queries to the global VisionManager in a thread-isolated manner.

    Phase 3.6: CognitiveCoordinator and ExecutiveController ownership removed.
    Those tools now live in MemoryTools where they belong.
    """

    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self._vision_manager = None
        self._last_vision_call: float = 0.0
        self._idle_timer: threading.Timer | None = None
        self._idle_lock = threading.Lock()

    @property
    def agent_bus(self):
        if not hasattr(self, '_agent_bus_cached'):
            from container import ServiceContainer
            container = ServiceContainer.instance()
            self._agent_bus_cached = container.get("agent_bus") if container else None
        return self._agent_bus_cached

    def _start_observer(self) -> None:
        """Start the ScreenObserver if not already running."""
        from container import ServiceContainer
        container = ServiceContainer.instance()
        observer = container.get("screen_observer") if container else None
        if observer and not (observer._daemon_thread and observer._daemon_thread.is_alive()):
            observer.start_observer(interval=0.2)
            _logger.info("ScreenObserver started lazily on first vision query.")

    def _schedule_idle_stop(self) -> None:
        """Reset the idle countdown timer. Observer stops after IDLE_TIMEOUT seconds of no calls."""
        if not _LAZY_VISION:
            return
        with self._idle_lock:
            if self._idle_timer:
                self._idle_timer.cancel()

            def _stop():
                try:
                    from container import ServiceContainer
                    container = ServiceContainer.instance()
                    observer = container.get("screen_observer") if container else None
                    if observer:
                        observer.stop_observer()
                        _logger.info("ScreenObserver auto-stopped after idle timeout.")
                except Exception:
                    pass

            self._idle_timer = threading.Timer(_IDLE_TIMEOUT, _stop)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    @llm.function_tool(
        description=(
            "Captures the screen or active window on-demand and analyzes it to answer queries. "
            "Use this when the user asks questions about their screen contents, "
            "terminal errors, code tracebacks, visual layouts, open application details, "
            "or buttons to click."
        )
    )
    async def analyze_screen_on_demand(self, query: str) -> str:
        """
        Captures the screen or active window and analyzes it based on the query.
        Runs in background thread pool via safe_execute.

        Phase 5.4: Lazily starts ScreenObserver and resets idle timer.
        """
        bus = self.agent_bus
        if bus is None:
            return "Error: AgentBus is not available."

        _logger.info(f"LLM Agent triggered analyze_screen_on_demand for query: '{query}'")

        # Lazy-start the ScreenObserver on first vision call
        if _LAZY_VISION:
            self._start_observer()
        self._last_vision_call = time.monotonic()
        self._schedule_idle_stop()

        # Publish immediate status update to the room for visual feedback
        if self.room:
            try:
                payload = json.dumps({"type": "status", "message": "Analyzing your screen..."})
                await self.room.local_participant.publish_data(payload.encode("utf-8"))
            except Exception as e:
                _logger.warning(f"Failed to publish screen analysis status payload: {e}")

        from ai.agents.types import AgentTask
        import uuid
        
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="analyze_screen",
            payload={"query": query},
            origin_agent="supervisor",
            target_agent="vision_agent"
        )
        
        # We can't await safe_execute with bus.dispatch directly if safe_execute is for synchronous tools,
        # but dispatch is async. If safe_execute wraps sync functions, we can just await dispatch.
        result = await bus.dispatch(task)
        if result.success:
            return result.result.get("analysis", "Error: No analysis returned from Vision Agent.")
        return f"Error: {result.error}"

    @llm.function_tool(
        description=(
            "Captures the screen and overlays numeric bounding-box marks (Set-of-Marks Grounding) "
            "on interactive UI elements to accurately locate buttons, inputs, and clickable icons."
        )
    )
    async def analyze_screen_with_som(self, query: str) -> str:
        bus = self.agent_bus
        if bus is None:
            return "Error: AgentBus is not available."

        _logger.info(f"LLM Agent triggered analyze_screen_with_som for query: '{query}'")

        if _LAZY_VISION:
            self._start_observer()
        self._last_vision_call = time.monotonic()
        self._schedule_idle_stop()

        from ai.agents.types import AgentTask
        import uuid

        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="analyze_screen",
            payload={"query": query, "use_som_grounding": True},
            origin_agent="supervisor",
            target_agent="vision_agent"
        )

        result = await bus.dispatch(task)
        if result.success:
            return result.result.get("analysis", "Error: No analysis returned from Vision Agent.")
        return f"Error: {result.error}"

