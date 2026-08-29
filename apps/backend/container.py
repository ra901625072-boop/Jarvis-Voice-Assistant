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


class _FailedService:
    """Sentinel cached when a service factory fails, preventing repeated retries."""
    def __init__(self, error: Exception):
        self.error = error
    def __repr__(self):
        return f"<FailedService: {self.error}>"


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
        self._startup_order: list[tuple[int, str]] = []
        self._shutdown_order: list[str] = []
        self._service_locks: Dict[str, threading.Lock] = {}

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

    def get(self, name: str) -> Any:
        """
        Get or lazily create a singleton service by name.

        Raises KeyError if name is not registered.
        """
        if name not in self._factories:
            raise KeyError(f"ServiceContainer: no service registered for '{name}'")

        # 1. Thread-safe check of already initialized services
        with self._lock:
            if name in self._services:
                svc = self._services[name]
                if isinstance(svc, _FailedService):
                    raise RuntimeError(f"Service '{name}' previously failed to initialize: {svc.error}")
                return svc
            
            # Retrieve or create lock for this specific service
            if name not in self._service_locks:
                self._service_locks[name] = threading.Lock()
            svc_lock = self._service_locks[name]

        # 2. Acquire per-service lock outside the main lock to prevent concurrent initialization deadlock
        with svc_lock:
            # Double-check inside the main lock
            with self._lock:
                if name in self._services:
                    svc = self._services[name]
                    if isinstance(svc, _FailedService):
                        raise RuntimeError(f"Service '{name}' previously failed to initialize: {svc.error}")
                    return svc

            logger.debug(f"Lazily initializing service: '{name}'")
            try:
                service = self._factories[name]()
                with self._lock:
                    self._services[name] = service
                return service
            except Exception as e:
                with self._lock:
                    self._services[name] = _FailedService(e)
                raise

    def has(self, name: str) -> bool:
        """Check if a service is registered and not failed."""
        with self._lock:
            if name not in self._factories:
                return False
            svc = self._services.get(name)
            return not isinstance(svc, _FailedService)

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    def get_or_none(self, name: str) -> Any:
        """Like get(), but returns None if the service is not available."""
        try:
            return self.get(name)
        except Exception as e:
            logger.debug(f"get_or_none('{name}') returned None: {e}")
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
                with self._lock:
                    self._services[name] = _FailedService(e)

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
                except Exception as e:
                    logger.warning(f"Error cleaning up service '{name}': {e}")


def build_container() -> ServiceContainer:
    """
    Build and return a fully configured ServiceContainer for JARVIS.

    All services are registered here with their factories and priorities.
    Call container.startup() to eagerly initialize them.
    """

    # Phase 0: Foundations

    container = ServiceContainer()

    # ── Priority 2-3: Multi-Agent OS Engine Foundations ─────────────────────
    from events.event_bus import EventBus
    container.register("event_bus", lambda: EventBus.get_instance(), startup_priority=2)

    from modules.memory.shared_context import SharedContextStore
    container.register("shared_context", lambda: SharedContextStore.get_instance(), startup_priority=2)

    from core.scheduler import PriorityTaskScheduler
    container.register("scheduler", lambda: PriorityTaskScheduler.get_instance(), startup_priority=3)

    from core.orchestrator import MasterOrchestrator
    container.register("orchestrator", lambda: MasterOrchestrator.get_instance(), startup_priority=3)

    from ai.agents.voice.voice_listener import VoiceListenerPipeline
    container.register("voice_listener", lambda: VoiceListenerPipeline.get_instance(), startup_priority=3)

    # ── Priority 5: Observability & Agents ────────────────────────────────────
    from modules.observability.trace_store import TraceStore
    container.register("trace_store", lambda: TraceStore(), startup_priority=5)
    
    import os
    USE_REDIS_BUS = os.getenv("JARVIS_REDIS_BUS", "false").lower() == "true"
    
    if USE_REDIS_BUS:
        from modules.bus.redis_bus import RedisBus
        container.register("agent_bus", lambda: RedisBus(os.getenv("REDIS_URL", "redis://localhost:6379")), startup_priority=5)
    else:
        from modules.bus.agent_bus import AgentBus
        container.register("agent_bus", lambda: AgentBus(), startup_priority=5)

    # ── Priority 4-7: Task Event Bus, Status Board, Task Announcer ───────────
    from modules.task.events import task_event_bus
    container.register("task_event_bus", lambda: task_event_bus, startup_priority=4)

    from modules.task.status_board import StatusBoard
    container.register("status_board", lambda: StatusBoard(), startup_priority=6)

    from modules.task.announcer import TaskAnnouncer
    container.register("task_announcer", lambda: TaskAnnouncer(), startup_priority=7)

    # ── Priority 10: Infrastructure ───────────────────────────────────────────
    from modules.approval.approval_store import ApprovalStore
    container.register("approval_store", lambda: ApprovalStore(), startup_priority=10)

    from modules.approval.engine import ApprovalEngine
    container.register(
        "approval_engine",
        lambda: ApprovalEngine(
            approval_store=container.get("approval_store"),
            task_event_bus=container.get("task_event_bus")
        ),
        startup_priority=10
    )

    from modules.security.credential_vault import CredentialVault
    container.register("credential_vault", lambda: CredentialVault(), startup_priority=10)

    from modules.controls.browser_controller import BrowserController
    container.register("browser_controller", lambda: BrowserController(), startup_priority=10)

    from modules.controls.window_controller import WindowController
    container.register("window_controller", lambda: WindowController(), startup_priority=10)

    from modules.controls.app_controller import AppController
    container.register("app_controller", lambda: AppController(), startup_priority=10)

    from modules.controls.system_controller import SystemController
    container.register("system_controller", lambda: SystemController(), startup_priority=10)

    container.register("security", lambda: _make_security(), startup_priority=10)
    container.register("world_state", lambda: _make_world_state(), startup_priority=10)

    # ── Priority 15: Behavior & Persona Engine ────────────────────────────────
    from modules.behavior import JarvisBehavior
    container.register("behavior_engine", lambda: JarvisBehavior, startup_priority=15)
    container.register("persona_engine", lambda: JarvisBehavior.get_persona_engine(), startup_priority=15)
    container.register("prompt_composer", lambda: JarvisBehavior.get_composer(), startup_priority=15)
    container.register(
        "adaptive_behavior_controller",
        lambda: _make_adaptive_behavior_controller(container.get_or_none("memory")),
        startup_priority=15,
    )

    # ── Priority 20: Memory (requires security) ───────────────────────────────

    container.register("memory", lambda: _make_memory(), startup_priority=20)

    # ── Priority 21: Session Manager ──────────────────────────────────────────

    container.register("session_manager", lambda: _make_session_manager(container.get("memory")), startup_priority=21)

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
    container.register(
        "indic_ocr_service",
        lambda: _make_indic_ocr_service(),
        startup_priority=33.5,
    )
    container.register(
        "translation_service",
        lambda: _make_translation_service(),
        startup_priority=33.6,
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

    # ── Priority 44: Tools Base Placeholder ───────────────────────────────────

    container.register(
        "tools",
        lambda: [],  # placeholder; agent.py will override with real list
        startup_priority=44,
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
    # Note: CoordinatorAgent intentionally omits itself and supervisor_agent
    # from its available_agents list to prevent self-referential routing loops.

    container.register(
        "coordinator_agent",
        lambda: _make_coordinator_agent(container.get("agent_bus"), container.get_or_none("memory")),
        startup_priority=46.5,
    )

    # ── Priority 47: Coding Agent ─────────────────────────────────────────────

    container.register(
        "coding_agent",
        lambda: _make_coding_agent(
            container.get("agent_bus")
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
            container.get("agent_bus")
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
        lambda: _make_recovery_agent(container.get("agent_bus"), container.get("memory")),
        startup_priority=49.2,
    )

    # ── Priority 49.3: Integration Agent ──────────────────────────────────────

    container.register(
        "integration_agent",
        lambda: _make_integration_agent(container.get("agent_bus")),
        startup_priority=49.3,
    )

    # ── Priority 49.4: Interaction Agent ──────────────────────────────────────

    container.register(
        "interaction_agent",
        lambda: _make_interaction_agent(container.get("agent_bus")),
        startup_priority=49.4,
    )

    # ── Priority 49.5: Language Agent ─────────────────────────────────────────

    container.register(
        "language_agent",
        lambda: _make_language_agent(container.get("agent_bus"), container.get_or_none("memory")),
        startup_priority=49.5,
    )

    container.register(
        "deep_research_agent",
        lambda: _make_deep_research_agent(container.get("memory_agent"), container.get("agent_bus")),
        startup_priority=49.6,
    )

    container.register(
        "learning_agent",
        lambda: _make_learning_agent(container.get("agent_bus"), container.get_or_none("memory")),
        startup_priority=49.7,
    )

    # ── Priority 49.8: UI/UX Designer Agent ───────────────────────────────────

    container.register(
        "ui_ux_agent",
        lambda: _make_ui_ux_agent(container.get("agent_bus"), container.get_or_none("memory")),
        startup_priority=49.8,
    )

    # ── Priority 49.85: Social Ecosystem (Contact Graph, Persona Engine, Scheduler) ──

    container.register(
        "contact_graph",
        lambda: _make_contact_graph(),
        startup_priority=49.85,
    )
    container.register(
        "persona_style_engine",
        lambda: _make_persona_style_engine(),
        startup_priority=49.86,
    )
    container.register(
        "social_scheduler",
        lambda: _make_social_scheduler(),
        startup_priority=49.87,
    )

    # ── Priority 49.9: Social Media Agent ─────────────────────────────────────

    container.register(
        "social_media_agent",
        lambda: _make_social_media_agent(
            bus=container.get("agent_bus"),
            browser_controller=container.get_or_none("browser_controller"),
            vision_agent=container.get_or_none("vision_agent"),
            credential_vault=container.get_or_none("credential_vault"),
            approval_engine=container.get_or_none("approval_engine"),
            contact_graph=container.get_or_none("contact_graph"),
            persona_style_engine=container.get_or_none("persona_style_engine"),
            social_scheduler=container.get_or_none("social_scheduler"),
        ),
        startup_priority=49.9,
    )

    container.register(
        "whatsapp_agent",
        lambda: _make_whatsapp_agent(
            bus=container.get("agent_bus"),
            whatsapp_adapter=container.get_or_none("social_media_agent").adapters.get("whatsapp") if container.get_or_none("social_media_agent") else None,
            vision_agent=container.get_or_none("vision_agent"),
            contact_graph=container.get_or_none("contact_graph"),
            persona_style_engine=container.get_or_none("persona_style_engine"),
            memory_manager=container.get_or_none("memory_manager"),
            approval_engine=container.get_or_none("approval_engine"),
            scheduler=container.get_or_none("social_scheduler"),
        ),
        startup_priority=49.92,
    )

    container.register(
        "gmail_agent",
        lambda: _make_gmail_agent(
            bus=container.get("agent_bus"),
            gmail_adapter=container.get_or_none("social_media_agent").adapters.get("gmail") if container.get_or_none("social_media_agent") else None,
            contact_graph=container.get_or_none("contact_graph"),
            persona_style_engine=container.get_or_none("persona_style_engine"),
            memory_manager=container.get_or_none("memory_manager"),
            approval_engine=container.get_or_none("approval_engine"),
            scheduler=container.get_or_none("social_scheduler"),
        ),
        startup_priority=49.93,
    )

    container.register(
        "instagram_agent",
        lambda: _make_instagram_agent(
            bus=container.get("agent_bus"),
            instagram_adapter=container.get_or_none("social_media_agent").adapters.get("instagram") if container.get_or_none("social_media_agent") else None,
            vision_agent=container.get_or_none("vision_agent"),
            contact_graph=container.get_or_none("contact_graph"),
            memory_manager=container.get_or_none("memory_manager"),
            approval_engine=container.get_or_none("approval_engine"),
            scheduler=container.get_or_none("social_scheduler"),
        ),
        startup_priority=49.94,
    )

    container.register(
        "social_watcher",
        lambda: _make_social_watcher(
            social_media_agent=container.get_or_none("social_media_agent"),
            contact_graph=container.get_or_none("contact_graph"),
        ),
        startup_priority=49.95,
    )

    # ── Priority 50: File management ──────────────────────────────────────────

    container.register("file_manager", lambda: _make_file_manager(), startup_priority=50)
    container.register(
        "folder_manager",
        lambda: _make_folder_manager(container.get("file_manager")),
        startup_priority=51,
    )
    container.register(
        "semantic_engine",
        lambda: _make_semantic_engine(container.get("file_manager")),
        startup_priority=51.5,
    )
    container.register(
        "directory_watcher_manager",
        lambda: _make_directory_watcher_manager(
            container.get("file_manager"), container.get("semantic_engine")
        ),
        startup_priority=51.8,
    )
    container.register(
        "file_discovery_agent",
        lambda: _make_file_discovery_agent(
            container.get("file_manager"),
            container.get("file_manager").learning_engine,
            container.get("semantic_engine")
        ),
        startup_priority=51.9,
    )
    container.register("task_manager", lambda: _make_task_manager(), startup_priority=52)

    return container


# ── Private factory functions ─────────────────────────────────────────────────

def _make_security():
    from modules.security.manager import SecurityManager
    return SecurityManager()


def _make_adaptive_behavior_controller(memory):
    from modules.behavior.adaptive import AdaptiveBehaviorController
    return AdaptiveBehaviorController(memory_manager=memory)


def _make_world_state():
    from modules.execution.world_state import WorldStateManager
    return WorldStateManager()


def _make_memory():
    from modules.memory.manager import MemoryManager
    mm = MemoryManager()
    mm.initialize_minimal()
    return mm


def _make_session_manager(memory):
    from modules.shared.session_manager import SessionManager
    return SessionManager(memory=memory)


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

def _make_coding_agent(bus):
    from ai.agents.coding.agent import CodingAgent
    return CodingAgent(bus=bus)

def _make_debugging_agent(bus):
    from ai.agents.debugging.agent import DebuggingAgent
    return DebuggingAgent(bus=bus)

def _make_browser_agent(bus):
    from ai.agents.browser.agent import BrowserAgent
    return BrowserAgent(bus=bus)

def _make_verification_agent(bus):
    from ai.agents.verification.agent import VerificationAgent
    return VerificationAgent(bus=bus)

def _make_recovery_agent(bus, memory=None):
    from ai.agents.recovery.agent import RecoveryAgent
    return RecoveryAgent(bus=bus, memory=memory)

def _make_integration_agent(bus):
    from ai.agents.integration.agent import IntegrationAgent
    return IntegrationAgent(bus=bus)

def _make_interaction_agent(bus):
    from ai.agents.interaction.agent import InteractionAgent
    return InteractionAgent(bus=bus)

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
            "recovery_agent", "interaction_agent", "language_agent",
            "ui_ux_agent", "social_media_agent", "whatsapp_agent",
            "gmail_agent", "instagram_agent"
        ],
        memory_manager=memory_manager
    )

def _make_contact_graph():
    from modules.social.contact_graph import ContactGraphManager
    return ContactGraphManager()

def _make_persona_style_engine():
    from modules.social.persona_style_engine import PersonaStyleEngine
    return PersonaStyleEngine()

def _make_social_scheduler():
    from modules.social.scheduler import SocialScheduler
    return SocialScheduler()

def _make_social_watcher(social_media_agent=None, contact_graph=None):
    from modules.social.watcher_service import SocialWatcherService
    return SocialWatcherService(social_media_agent=social_media_agent, contact_graph=contact_graph)

def _make_social_media_agent(
    bus,
    browser_controller=None,
    vision_agent=None,
    credential_vault=None,
    approval_engine=None,
    contact_graph=None,
    persona_style_engine=None,
    social_scheduler=None
):
    from ai.agents.social_media.agent import SocialMediaAgent
    return SocialMediaAgent(
        bus=bus,
        browser_controller=browser_controller,
        vision_agent=vision_agent,
        credential_vault=credential_vault,
        approval_engine=approval_engine,
        contact_graph=contact_graph,
        persona_style_engine=persona_style_engine,
        social_scheduler=social_scheduler
    )

def _make_whatsapp_agent(
    bus,
    whatsapp_adapter=None,
    vision_agent=None,
    contact_graph=None,
    persona_style_engine=None,
    memory_manager=None,
    approval_engine=None,
    scheduler=None
):
    from ai.agents.whatsapp.agent import WhatsAppAgent
    return WhatsAppAgent(
        bus=bus,
        whatsapp_adapter=whatsapp_adapter,
        vision_agent=vision_agent,
        contact_graph=contact_graph,
        persona_style_engine=persona_style_engine,
        memory_manager=memory_manager,
        approval_engine=approval_engine,
        scheduler=scheduler
    )

def _make_gmail_agent(
    bus,
    gmail_adapter=None,
    contact_graph=None,
    persona_style_engine=None,
    memory_manager=None,
    approval_engine=None,
    scheduler=None
):
    from ai.agents.gmail.agent import GmailAgent
    return GmailAgent(
        bus=bus,
        gmail_adapter=gmail_adapter,
        contact_graph=contact_graph,
        persona_style_engine=persona_style_engine,
        memory_manager=memory_manager,
        approval_engine=approval_engine,
        scheduler=scheduler
    )

def _make_instagram_agent(
    bus,
    instagram_adapter=None,
    vision_agent=None,
    contact_graph=None,
    memory_manager=None,
    approval_engine=None,
    scheduler=None
):
    from ai.agents.instagram.agent import InstagramAgent
    return InstagramAgent(
        bus=bus,
        instagram_adapter=instagram_adapter,
        vision_agent=vision_agent,
        contact_graph=contact_graph,
        memory_manager=memory_manager,
        approval_engine=approval_engine,
        scheduler=scheduler
    )

def _make_indic_ocr_service():
    from modules.language.indic_ocr_service import IndicOCRService
    return IndicOCRService()

def _make_translation_service():
    from modules.language.translation_service import TranslationService
    return TranslationService()

def _make_language_agent(bus, memory):
    from ai.agents.language.agent import LanguageAgent
    return LanguageAgent(bus, memory)

def _make_deep_research_agent(memory_agent, bus):
    from ai.agents.research.agent import DeepResearchAgent
    return DeepResearchAgent(memory_agent=memory_agent, bus=bus)

def _make_learning_agent(bus, memory):
    from ai.agents.learning.agent import LearningAgent
    return LearningAgent(bus=bus, memory=memory)

def _make_ui_ux_agent(bus, memory):
    from ai.agents.ui_ux.agent import UIUXDesignerAgent
    return UIUXDesignerAgent(bus=bus, memory=memory)

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


def _make_semantic_engine(file_mgr):
    from modules.filesystem.semantic_engine import SemanticEngine
    import os
    db_dir = os.path.dirname(file_mgr.db_path)
    return SemanticEngine(db_dir)


class DirectoryWatcherManager:
    def __init__(self, watchers):
        self.watchers = watchers

    def shutdown(self):
        for w in self.watchers:
            try:
                w.stop()
            except Exception as e:
                logger.error(f"Failed to stop DirectoryWatcher: {e}")


def _make_directory_watcher_manager(file_mgr, semantic_engine):
    from modules.filesystem.directory_watcher import DirectoryWatcher
    import os
    paths = file_mgr.indexer.get_default_paths()
    watchers = []
    for path in paths:
        if os.path.exists(path):
            try:
                watcher = DirectoryWatcher(path, semantic_engine)
                watcher.start()
                watchers.append(watcher)
            except Exception as e:
                logger.error(f"Failed to start DirectoryWatcher for {path}: {e}")
    return DirectoryWatcherManager(watchers)


def _make_file_discovery_agent(file_mgr, learning_engine, semantic_engine):
    from modules.skills.file_discovery_agent import FileDiscoveryAgent
    return FileDiscoveryAgent(file_mgr, learning_engine, semantic_engine)


