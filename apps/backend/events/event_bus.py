import asyncio
import logging
import uuid
from typing import Callable, Dict, List, Any, Optional, Awaitable
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("JARVIS.EventBus")

@dataclass
class BaseEvent:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    channel: str = "default"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    sender: str = "system"
    payload: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TaskEvent(BaseEvent):
    task_id: str = ""
    task_name: str = ""
    agent_id: str = ""
    status: str = "pending"
    progress: int = 0
    channel: str = "task_events"

@dataclass
class VoiceEvent(BaseEvent):
    text: str = ""
    is_final: bool = True
    intent: Optional[str] = None
    channel: str = "voice_events"

@dataclass
class BrowserEvent(BaseEvent):
    url: str = ""
    action: str = ""
    channel: str = "browser_events"

EventHandler = Callable[[BaseEvent], Awaitable[None]]

class EventBus:
    """
    Centralized Async Pub/Sub Event Bus for JARVIS Multi-Agent Operating System.
    Decouples agents, scheduler, orchestrator, and UI dashboards.
    """
    _instance: Optional["EventBus"] = None

    def __init__(self):
        self._subscribers: Dict[str, List[EventHandler]] = {}
        self._wildcard_subscribers: List[EventHandler] = []
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "EventBus":
        if cls._instance is None:
            cls._instance = EventBus()
        return cls._instance

    def subscribe(self, channel: str, handler: EventHandler) -> None:
        """Subscribe an async handler to a specific channel (or '*' for all)."""
        if channel == "*":
            if handler not in self._wildcard_subscribers:
                self._wildcard_subscribers.append(handler)
                logger.debug("Registered wildcard event subscriber.")
            return

        if channel not in self._subscribers:
            self._subscribers[channel] = []
        if handler not in self._subscribers[channel]:
            self._subscribers[channel].append(handler)
            logger.debug(f"Registered subscriber for channel '{channel}'")

    def unsubscribe(self, channel: str, handler: EventHandler) -> None:
        """Unsubscribe a handler from a channel."""
        if channel == "*":
            if handler in self._wildcard_subscribers:
                self._wildcard_subscribers.remove(handler)
            return

        if channel in self._subscribers and handler in self._subscribers[channel]:
            self._subscribers[channel].remove(handler)

    async def publish(self, event_or_channel: Any, payload: Any = None) -> None:
        """Publish an event asynchronously to all registered subscribers for the event's channel."""
        if isinstance(event_or_channel, BaseEvent):
            event = event_or_channel
            channel = event.channel
        else:
            channel = str(event_or_channel)
            p = payload if isinstance(payload, dict) else ({"data": payload} if payload is not None else {})
            event = BaseEvent(channel=channel, payload=p)

        handlers: List[EventHandler] = []

        if channel in self._subscribers:
            handlers.extend(self._subscribers[channel])
        handlers.extend(self._wildcard_subscribers)

        if not handlers:
            return

        # Fire handlers concurrently without letting one failure break others
        tasks = []
        for handler in handlers:
            tasks.append(asyncio.create_task(self._safe_invoke(handler, event)))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_invoke(self, handler: EventHandler, event: BaseEvent) -> None:
        try:
            await handler(event)
        except Exception as e:
            logger.exception(f"Error executing event subscriber for event {event.event_id} on channel {event.channel}: {e}")
