"""
container.py — ServiceContainer: Dependency-Injection wiring for all singletons.

Replaces the old GlobalRegistry class-based singleton that instantiated services
at class-definition time (which caused silent failures if vision libraries weren't
available at import).

Usage:
    # In agent.py at startup:
    container = ServiceContainer()
    await container.startup()

    # Anywhere:
    container = ServiceContainer.instance()
    memory = container.get("memory")
"""
import logging
import threading
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("JARVIS.Container")


class ServiceContainer:
    """
    Lightweight dependency-injection container with lazy initialization.

    Services are registered as factories (callables that return the service
    object).  The first call to get() invokes the factory and caches the
    result.  Subsequent calls return the cached singleton.
    """

    _instance: Optional["ServiceContainer"] = None
    _instance_lock = threading.Lock()

    # ── Singleton accessor ────────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> Optional["ServiceContainer"]:
        """Return the current container instance, or None if not yet created."""
        return cls._instance

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def __init__(self) -> None:
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._services: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._startup_order: list[str] = []
        self._shutdown_order: list[str] = []

        # Register this instance as the global singleton
        with ServiceContainer._instance_lock:
            ServiceContainer._instance = self

    def register(
        self,
        name: str,
        factory: Callable[[], Any],
        startup_priority: int = 50,
    ) -> None:
        """
        Register a lazy factory for a named service.

        Args:
            name:             Service identifier used in get().
            factory:          Zero-argument callable that creates the service.
            startup_priority: Lower = earlier in startup order (default 50).
        """
        with self._lock:
            self._factories[name] = factory
            self._startup_order.append((startup_priority, name))
            self._startup_order.sort()

    def get(self, name: str) -> Any:
        """
        Get or lazily create a singleton service by name.

        Raises KeyError if name is not registered.
        """
        with self._lock:
            if name in self._services:
                return self._services[name]
            if name not in self._factories:
                raise KeyError(f"ServiceContainer: no service registered for '{name}'")
            logger.debug(f"Lazily initializing service: '{name}'")
            service = self._factories[name]()
            self._services[name] = service
            return service

    def get_or_none(self, name: str) -> Any:
        """Like get(), but returns None if the service is not registered."""
        try:
            return self.get(name)
        except KeyError:
            return None

    async def startup(self) -> None:
        """Initialize all services in priority order (eager startup)."""
        sorted_names = [name for _, name in sorted(self._startup_order)]
        for name in sorted_names:
            try:
                self.get(name)
                logger.info(f"Service '{name}' initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize service '{name}': {e}")

    async def shutdown(self) -> None:
        """
        Graceful teardown in reverse startup order.
        Calls shutdown() on services that support it.
        """
        sorted_names = [name for _, name in sorted(self._startup_order)]
        for name in reversed(sorted_names):
            service = self._services.get(name)
            if service is None:
                continue
            if hasattr(service, "shutdown"):
                try:
                    service.shutdown()
                    logger.info(f"Service '{name}' shut down.")
                except Exception as e:
                    logger.warning(f"Error shutting down service '{name}': {e}")
            elif hasattr(service, "cleanup"):
                try:
                    service.cleanup()
                except Exception:
                    pass


def build_container() -> ServiceContainer:
    """
    Build and return a fully configured ServiceContainer for JARVIS.

    All services are registered here with their factories and priorities.
    Call container.startup() to eagerly initialize them.
    """
    import os

    # Phase 0: Foundations
    from events.bus import AgentBus

    container = ServiceContainer()

    # ── Priority 5: Agents ────────────────────────────────────────────────────
    container.register("agent_bus", lambda: AgentBus(), startup_priority=5)

    # ── Priority 10: Infrastructure ───────────────────────────────────────────

    container.register("security", lambda: _make_security(), startup_priority=10)
    container.register("world_state", lambda: _make_world_state(), startup_priority=10)

    # ── Priority 20: Memory (requires security) ───────────────────────────────

    container.register("memory", lambda: _make_memory(), startup_priority=20)

    # ── Priority 25: Memory Agent ─────────────────────────────────────────────

    container.register(
        "memory_agent",
        lambda: _make_memory_agent(
            container.get("memory"),
            container.get("agent_bus")
        ),
        startup_priority=25,
    )

    # ── Priority 26: Planning Agent ───────────────────────────────────────────

    container.register(
        "planning_agent",
        lambda: _make_planning_agent(
            container.get("memory_agent"),
            container.get("agent_bus")
        ),
        startup_priority=26,
    )

    # ── Priority 30: Vision / screen observation ──────────────────────────────

    container.register(
        "screen_observer",
        lambda: _make_screen_observer(),
        startup_priority=30,
    )
    container.register(
        "ui_mapper",
        lambda: _make_ui_mapper(container.get("screen_observer")),
        startup_priority=31,
    )
    container.register(
        "action_verifier",
        lambda: _make_action_verifier(container.get("screen_observer")),
        startup_priority=32,
    )
    container.register(
        "vision_manager",
        lambda: _make_vision_manager(container.get("memory")),
        startup_priority=33,
    )

    # ── Priority 35: Vision Agent ─────────────────────────────────────────────

    container.register(
        "vision_agent",
        lambda: _make_vision_agent(
            container.get("vision_manager"),
            container.get("agent_bus")
        ),
        startup_priority=35,
    )

    # ── Priority 40: Execution layer ──────────────────────────────────────────

    container.register(
        "verification",
        lambda: _make_verification(container.get("world_state")),
        startup_priority=40,
    )

    # ── Priority 45: Execution Agent ──────────────────────────────────────────

    container.register(
        "execution_agent",
        lambda: _make_execution_agent(
            container.get_or_none("tools"),
            container.get("memory_agent"),
            container.get("agent_bus"),
            container.get("security")
        ),
        startup_priority=45,
    )

    # ── Priority 46: Supervisor Agent ─────────────────────────────────────────

    container.register(
        "supervisor_agent",
        lambda: _make_supervisor_agent(container.get("agent_bus")),
        startup_priority=46,
    )

    # ── Priority 46.5: Coordinator Agent ──────────────────────────────────────

    container.register(
        "coordinator_agent",
        lambda: _make_coordinator_agent(container.get("agent_bus"), container.get_or_none("memory")),
        startup_priority=46.5,
    )

    # ── Priority 47: Coding Agent ─────────────────────────────────────────────

    container.register(
        "coding_agent",
        lambda: _make_coding_agent(
            container.get("agent_bus"),
            container.get_or_none("tools")
        ),
        startup_priority=47,
    )

    # ── Priority 48: Debugging Agent ──────────────────────────────────────────

    container.register(
        "debugging_agent",
        lambda: _make_debugging_agent(container.get("agent_bus")),
        startup_priority=48,
    )

    # ── Priority 49: Browser Agent ────────────────────────────────────────────

    container.register(
        "browser_agent",
        lambda: _make_browser_agent(
            container.get("agent_bus"),
            container.get_or_none("tools")
        ),
        startup_priority=49,
    )

    # ── Priority 49.1: Verification Agent ─────────────────────────────────────

    container.register(
        "verification_agent",
        lambda: _make_verification_agent(container.get("agent_bus")),
        startup_priority=49.1,
    )

    # ── Priority 49.2: Recovery Agent ─────────────────────────────────────────

    container.register(
        "recovery_agent",
        lambda: _make_recovery_agent(container.get("agent_bus")),
        startup_priority=49.2,
    )

    # ── Priority 49.3: Integration Agent ──────────────────────────────────────

    container.register(
        "integration_agent",
        lambda: _make_integration_agent(container.get("agent_bus")),
        startup_priority=49.3,
    )

    # ── Priority 50: File management ──────────────────────────────────────────

    container.register("file_manager", lambda: _make_file_manager(), startup_priority=50)
    container.register(
        "folder_manager",
        lambda: _make_folder_manager(container.get("file_manager")),
        startup_priority=51,
    )
    container.register("task_manager", lambda: _make_task_manager(), startup_priority=52)

    return container


# ── Private factory functions ─────────────────────────────────────────────────

def _make_security():
    from modules.core.security_manager import SecurityManager
    return SecurityManager()


def _make_world_state():
    from modules.execution.world_state import WorldStateManager
    return WorldStateManager()


def _make_memory():
    from modules.core.memory_manager import MemoryManager
    mm = MemoryManager()
    mm.initialize_minimal()
    return mm


def _make_memory_agent(memory, bus):
    from ai.agents.memory.agent import MemoryAgent
    return MemoryAgent(memory=memory, bus=bus)


def _make_planning_agent(memory_agent, bus):
    from ai.agents.planning.agent import PlanningAgent
    return PlanningAgent(memory_agent=memory_agent, bus=bus)


def _make_screen_observer():
    from modules.vision.screen_observer import ScreenObserver
    return ScreenObserver(cache_duration=3.0)


def _make_ui_mapper(observer):
    from modules.vision.ui_mapper import UIMapper
    return UIMapper(observer=observer)


def _make_action_verifier(observer):
    from modules.planning.action_verifier import ActionVerifier
    return ActionVerifier(observer=observer)


def _make_execution_agent(tools_list, memory_agent, bus, security):
    from ai.agents.execution.agent import ExecutionAgent
    return ExecutionAgent(tools_list=tools_list, memory_agent=memory_agent, bus=bus, security=security)

def _make_supervisor_agent(bus):
    from ai.agents.supervisor.agent import SupervisorAgent
    return SupervisorAgent(bus=bus)

def _make_coding_agent(bus, tools_list):
    from ai.agents.coding.agent import CodingAgent
    return CodingAgent(bus=bus, tools_list=tools_list)

def _make_debugging_agent(bus):
    from ai.agents.debugging.agent import DebuggingAgent
    return DebuggingAgent(bus=bus)

def _make_browser_agent(bus, tools_list):
    from ai.agents.browser.agent import BrowserAgent
    return BrowserAgent(bus=bus, tools_list=tools_list)

def _make_verification_agent(bus):
    from ai.agents.verification.agent import VerificationAgent
    return VerificationAgent(bus=bus)

def _make_recovery_agent(bus):
    from ai.agents.recovery.agent import RecoveryAgent
    return RecoveryAgent(bus=bus)

def _make_integration_agent(bus):
    from ai.agents.integration.agent import IntegrationAgent
    return IntegrationAgent(bus=bus)

def _make_vision_agent(vision_manager, bus):
    from ai.agents.vision.agent import VisionAgent
    return VisionAgent(vision_manager=vision_manager, bus=bus)

def _make_coordinator_agent(bus, memory_manager):
    from ai.agents.coordinator.agent import CoordinatorAgent
    return CoordinatorAgent(
        bus=bus, 
        available_agents=[
            "coding_agent", "browser_agent", "debugging_agent", 
            "execution_agent", "planning_agent", "vision_agent", 
            "memory_agent", "verification_agent", "integration_agent", 
            "recovery_agent"
        ],
        memory_manager=memory_manager
    )

def _make_vision_manager(memory):
    from modules.vision.vision_manager import VisionManager
    vm = VisionManager()
    if memory:
        vm.set_memory_manager(memory)
    return vm


def _make_verification(world_state):
    from modules.execution.verification_engine import VerificationEngine
    return VerificationEngine(world_state)


def _make_file_manager():
    from modules.filesystem.file_manager import FileManager
    return FileManager()


def _make_folder_manager(file_mgr):
    from modules.filesystem.folder_manager import FolderManager
    return FolderManager(file_mgr=file_mgr)


def _make_task_manager():
    from modules.planning.task_manager import BackgroundTaskManager
    mgr = BackgroundTaskManager()
    mgr.start()
    return mgr

