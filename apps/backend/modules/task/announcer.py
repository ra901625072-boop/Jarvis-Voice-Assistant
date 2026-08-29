import asyncio
import logging
import os
import uuid
import time
from typing import List

from modules.task.events import task_event_bus
from container import ServiceContainer
from ai.agents.types import AgentTask, TaskPriority

logger = logging.getLogger("JARVIS.TaskAnnouncer")

class TaskAnnouncer:
    def __init__(self):
        self._buffer = []
        self._timer_task = None
        self._last_progress = {}  # task_id -> last announced progress milestone
        
        # Subscribe to the task event bus
        task_event_bus.subscribe(self.handle_event)
        logger.info("TaskAnnouncer initialized and subscribed to TaskEventBus.")

    def handle_event(self, event: dict):
        try:
            proactive_enabled = os.getenv("JARVIS_PROACTIVE_SPEECH_ENABLED", "true").lower() == "true"
            if not proactive_enabled:
                return

            status = event.get("status")
            announce = event.get("announce", True)
            priority = event.get("priority", "normal")
            task_id = event.get("task_id")
            
            # Failures always announce regardless of announce=False
            if status == "failed":
                announce = True
                if priority in ("low", "normal"):
                    priority = "high"

            execution_ctx = str(event.get("execution_context", "auto")).lower()
            if execution_ctx == "background" and status == "progress":
                return

            if not announce:
                return

            # Progress filtering
            if status == "progress":
                progress = event.get("progress", 0)
                milestones_str = os.getenv("JARVIS_ANNOUNCE_MILESTONES", "25,50,75,100")
                try:
                    milestones = [int(x.strip()) for x in milestones_str.split(",") if x.strip().isdigit()]
                except Exception:
                    milestones = [25, 50, 75, 100]
                
                last_announced = self._last_progress.get(task_id, -1)
                matching_milestone = None
                for m in sorted(milestones):
                    if progress >= m > last_announced:
                        matching_milestone = m
                
                if matching_milestone is None:
                    return
                
                self._last_progress[task_id] = matching_milestone
                # Use a copy of event to add progress milestone metadata
                event = dict(event)
                event["progress_milestone"] = matching_milestone

            elif status in ("completed", "failed", "cancelled"):
                self._last_progress.pop(task_id, None)

            # Add to queue buffer and reset debounce timer
            self._buffer.append(event)
            
            batch_window = float(os.getenv("JARVIS_ANNOUNCE_BATCH_WINDOW_SEC", "1.5"))
            if self._timer_task and not self._timer_task.done():
                # Let current timer run (debounce grouping window)
                pass
            else:
                self._timer_task = asyncio.create_task(self._wait_and_dispatch(batch_window))

        except Exception as e:
            logger.error(f"Error handling event in TaskAnnouncer: {e}", exc_info=True)

    async def _wait_and_dispatch(self, delay: float):
        await asyncio.sleep(delay)
        
        events_to_announce = list(self._buffer)
        self._buffer.clear()
        
        if not events_to_announce:
            return

        # Determine highest priority
        max_priority_str = "low"
        priority_order = {"low": 0, "normal": 1, "high": 2, "critical": 3}
        for e in events_to_announce:
            p = e.get("priority", "normal")
            if priority_order.get(p, 1) > priority_order.get(max_priority_str, 0):
                max_priority_str = p

        announcement_text = self._build_announcement(events_to_announce)
        if not announcement_text:
            return

        priority_map = {
            "low": TaskPriority.LOW,
            "normal": TaskPriority.NORMAL,
            "high": TaskPriority.HIGH,
            "critical": TaskPriority.CRITICAL
        }
        task_priority = priority_map.get(max_priority_str, TaskPriority.NORMAL)
        
        # Extract associated background task IDs
        bg_task_ids = [e["task_id"] for e in events_to_announce]

        logger.info(f"TaskAnnouncer: speaking '{announcement_text}' with priority {task_priority}")
        
        container = ServiceContainer.instance()
        if container:
            try:
                bus = container.get("agent_bus")
                task = AgentTask(
                    task_id=f"speak_{uuid.uuid4().hex[:8]}",
                    task_type="speak",
                    payload={
                        "text": announcement_text, 
                        "priority": max_priority_str,
                        "bg_task_ids": bg_task_ids
                    },
                    origin_agent="task_announcer",
                    target_agent="supervisor_agent",
                    priority=task_priority
                )
                asyncio.create_task(bus.dispatch(task))
            except Exception as e:
                logger.error(f"Failed to dispatch speak task via AgentBus: {e}", exc_info=True)

    def _build_announcement(self, events: List[dict]) -> str:
        if len(events) == 1:
            e = events[0]
            label = e.get("label") or f"{e['task_type']} task"
            status = e.get("status")
            if status == "running":
                return f"Starting the task: {label}."
            elif status == "progress":
                return f"{label} is {e.get('progress_milestone', e.get('progress'))}% complete."
            elif status == "completed":
                return f"Done: {label} completed successfully."
            elif status == "failed":
                err = e.get("error") or "Unknown error"
                return f"Heads up, the task {label} failed: {err}."
            elif status == "cancelled":
                return f"Task {label} was cancelled."
            return f"Task {label} status is now {status}."

        # Multiple events batching
        by_status = {}
        for e in events:
            status = e.get("status")
            by_status.setdefault(status, []).append(e)

        sentences = []
        for status, evs in by_status.items():
            labels = [e.get("label") or f"{e['task_type']} task" for e in evs]
            if len(labels) == 1:
                label_str = labels[0]
            elif len(labels) == 2:
                label_str = f"{labels[0]} and {labels[1]}"
            else:
                label_str = ", ".join(labels[:-1]) + f", and {labels[-1]}"

            if status == "running":
                sentences.append(f"Started {len(evs)} tasks: {label_str}.")
            elif status == "progress":
                sentences.append(f"Progress updates for {label_str} are available.")
            elif status == "completed":
                sentences.append(f"{label_str} completed successfully.")
            elif status == "failed":
                sentences.append(f"Heads up, {len(evs)} tasks failed: {label_str}.")
            elif status == "cancelled":
                sentences.append(f"Cancelled tasks: {label_str}.")

        return " ".join(sentences)
