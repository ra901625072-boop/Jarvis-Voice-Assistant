import asyncio
import logging
import time
from typing import Callable

logger = logging.getLogger("JARVIS.TaskEventBus")

class TaskEventBus:
    def __init__(self):
        self._subscribers = []
        self._loop = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        logger.info(f"TaskEventBus: loop reference set to {loop}")

    def subscribe(self, callback: Callable[[dict], None]):
        if callback not in self._subscribers:
            self._subscribers.append(callback)
            logger.debug("TaskEventBus: subscribed a new callback.")

    def unsubscribe(self, callback: Callable[[dict], None]):
        if callback in self._subscribers:
            self._subscribers.remove(callback)
            logger.debug("TaskEventBus: unsubscribed a callback.")

    def publish(self, event: dict):
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._notify, event)
        else:
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(self._notify, event)
            except RuntimeError:
                # No running event loop in this thread, notify synchronously
                self._notify(event)

    def _notify(self, event: dict):
        try:
            from events.event_bus import EventBus
            asyncio.create_task(EventBus.get_instance().publish("task_events", event))
        except Exception:
            pass

        for cb in self._subscribers:
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb(event))
                else:
                    cb(event)
            except Exception as e:
                logger.error(f"Error in TaskEventBus subscriber callback: {e}", exc_info=True)

task_event_bus = TaskEventBus()
