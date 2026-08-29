import threading
import time
from collections import deque
from modules.task.events import task_event_bus

class StatusBoard:
    def __init__(self):
        self._lock = threading.Lock()
        self._active_tasks = {}  # task_id -> task_dict
        self._finished_tasks = deque(maxlen=20)  # deque of task_dict
        
        # Subscribe to the event bus
        task_event_bus.subscribe(self.handle_event)

    def handle_event(self, event: dict):
        if not isinstance(event, dict):
            return
        with self._lock:
            task_id = event.get("task_id")
            status = event.get("status")
            if not task_id or not status:
                return
            
            # Update state
            if status in ("completed", "failed", "cancelled"):
                if task_id in self._active_tasks:
                    task = self._active_tasks.pop(task_id)
                    task.update(event)
                    self._finished_tasks.append(task)
                else:
                    self._finished_tasks.append(event)
            else:
                self._active_tasks[task_id] = event

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "active": list(self._active_tasks.values()),
                "finished": list(self._finished_tasks)
            }

    def render_context(self, max_items: int = 5) -> str:
        with self._lock:
            # Active tasks
            active_strs = []
            for t in list(self._active_tasks.values())[:max_items]:
                label = t.get("label") or f"{t['task_type']} task"
                progress = t.get("progress", 0)
                status = t.get("status", "queued")
                if status == "running":
                    active_strs.append(f"{label} ({progress}%)")
                else:
                    active_strs.append(f"{label} ({status})")

            # Finished tasks (recent)
            finished_strs = []
            now = time.time()
            # finished_tasks is a deque, order is oldest to newest, so we reverse it to show most recent first
            recent_finished = list(self._finished_tasks)
            recent_finished.reverse()
            for t in recent_finished[:max_items]:
                label = t.get("label") or f"{t['task_type']} task"
                status = t.get("status")
                ts = t.get("timestamp", now)
                diff = int(now - ts)
                if diff < 0:
                    diff = 0
                if diff < 60:
                    time_str = f"{diff}s ago"
                else:
                    time_str = f"{diff // 60}m ago"
                finished_strs.append(f"{label} {status} {time_str}")

            parts = []
            if active_strs:
                parts.append("Currently running: " + ", ".join(active_strs) + ".")
            if finished_strs:
                parts.append("Recently finished: " + ", ".join(finished_strs) + ".")
                
            if not parts:
                return "No active or recent background tasks."
            return "\n".join(parts)
