import logging
import json
import threading
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger("JARVIS.StateManager")

class AgentState(Enum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    REPLANNING = "REPLANNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class SubTask:
    def __init__(self, description: str, task_id: int = None, tool_name: Optional[str] = None, dependencies: List[int] = None):
        self.id = task_id if task_id is not None else id(self)
        self.description = description
        self.tool_name = tool_name
        self.dependencies = dependencies or []
        self.status = "pending"  # pending, in_progress, completed, failed
        self.result: Optional[str] = None
        self.error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "tool_name": self.tool_name,
            "status": self.status,
            "result": self.result,
            "error": self.error
        }

class Plan:
    def __init__(self, goal: str, subtasks: List[SubTask]):
        self.goal = goal
        self.subtasks = subtasks
        self.created_at = datetime.now()
        self.status = "active"  # active, completed, failed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "subtasks": [t.to_dict() for t in self.subtasks]
        }

class AgentStateManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AgentStateManager, cls).__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        self.agent_state: AgentState = AgentState.IDLE
        self.current_goal: Optional[str] = None
        self.active_plan: Optional[Plan] = None
        self.current_task_idx: int = -1
        self.screen_context: Dict[str, Any] = {}
        self.execution_history: List[Dict[str, Any]] = []
        self._state_lock = threading.Lock()
        logger.info("AgentStateManager initialized.")

    def set_plan(self, goal: str, subtasks: List[SubTask]):
        with self._state_lock:
            self.current_goal = goal
            self.active_plan = Plan(goal, subtasks)
            self.current_task_idx = 0
            self.execution_history.append({
                "timestamp": datetime.now().isoformat(),
                "event": "plan_created",
                "goal": goal,
                "subtasks_count": len(subtasks)
            })
            logger.info(f"New plan set for goal: {goal}")

    def get_next_task(self) -> Optional[SubTask]:
        with self._state_lock:
            if not self.active_plan or self.active_plan.status != "active":
                return None
            
            # Find a pending task whose dependencies are all completed
            task_status_map = {t.id: t.status for t in self.active_plan.subtasks}
            
            for i, task in enumerate(self.active_plan.subtasks):
                if task.status == "pending":
                    can_run = True
                    for dep_id in task.dependencies:
                        if task_status_map.get(dep_id) != "completed":
                            can_run = False
                            break
                    if can_run:
                        task.status = "in_progress"
                        self.current_task_idx = i
                        return task
                        
            # If no task can run, check if all are completed or blocked
            all_done = all(t.status in ("completed", "blocked") for t in self.active_plan.subtasks)
            if all_done:
                self.active_plan.status = "completed"
            return None

    def update_task_status(self, task: SubTask, status: str, result: str = None, error: str = None):
        with self._state_lock:
            task.status = status
            task.result = result
            task.error = error
            self.execution_history.append({
                "timestamp": datetime.now().isoformat(),
                "event": "task_updated",
                "task": task.description,
                "status": status,
                "result": result,
                "error": error
            })
            if status == "failed":
                if self.active_plan:
                    self.active_plan.status = "failed"
                    # Cascade failure to dependent tasks
                    self._cascade_block(task.id)
            logger.info(f"Task '{task.description}' marked as {status}.")

    def _cascade_block(self, failed_task_id: int):
        """Recursively marks dependent tasks as blocked."""
        for t in self.active_plan.subtasks:
            if t.status == "pending" and failed_task_id in t.dependencies:
                t.status = "blocked"
                t.error = f"Blocked by failure of task {failed_task_id}"
                logger.info(f"Task '{t.description}' marked as blocked.")
                self._cascade_block(t.id)

    def update_screen_context(self, window_title: str, ui_elements: List[str] = None):
        with self._state_lock:
            self.screen_context = {
                "window_title": window_title,
                "ui_elements": ui_elements or [],
                "timestamp": datetime.now().isoformat()
            }

    def get_state_summary(self) -> str:
        with self._state_lock:
            summary = f"Agent Phase: {self.agent_state.value}\n"
            
            if not self.active_plan:
                return summary + "No active plan."
            
            summary += f"Current Goal: {self.current_goal}\n"
            summary += f"Plan Status: {self.active_plan.status}\n"
            summary += "Tasks:\n"
            for i, t in enumerate(self.active_plan.subtasks):
                marker = "->" if i == self.current_task_idx else "  "
                summary += f"{marker} [{t.status.upper()}] {t.description}\n"
            
            if self.screen_context:
                summary += f"\nCurrent Window: {self.screen_context.get('window_title')}"
                
            return summary

    def clear_state(self):
        with self._state_lock:
            self.agent_state = AgentState.IDLE
            self.current_goal = None
            self.active_plan = None
            self.current_task_idx = -1
            self.screen_context = {}
            logger.info("Agent state cleared.")

    def set_agent_state(self, new_state: AgentState):
        with self._state_lock:
            logger.info(f"Agent state transitioning: {self.agent_state.value} -> {new_state.value}")
            self.agent_state = new_state

    # ------------------------------------------------------------------ #
    # Crash-safe persistence                                               #
    # ------------------------------------------------------------------ #

    def persist_state(self, memory_manager) -> None:
        """
        Checkpoint the current plan and goal to SQLite via MemoryManager.
        Call this after every task status change for crash safety.
        """
        try:
            with self._state_lock:
                plan_dict = self.active_plan.to_dict() if self.active_plan else None
                history   = list(self.execution_history[-50:])  # keep last 50
                screen    = dict(self.screen_context)
                goal      = self.current_goal
            memory_manager.persist_agent_state(goal, plan_dict, history, screen)
        except Exception as e:
            logger.warning(f"Failed to persist agent state: {e}")

    def restore_state(self, memory_manager) -> bool:
        """
        Restore the last checkpointed state from SQLite.
        Returns True if a state was found and loaded.
        """
        try:
            saved = memory_manager.restore_agent_state()
            if not saved:
                logger.info("No persisted agent state found.")
                return False

            with self._state_lock:
                self.current_goal       = saved.get("current_goal")
                self.execution_history  = saved.get("history", [])
                self.screen_context     = saved.get("screen_context") or {}

                plan_data = saved.get("active_plan")
                if plan_data and plan_data.get("goal"):
                    subtasks = [
                        SubTask(description=t["description"])
                        for t in plan_data.get("subtasks", [])
                    ]
                    for i, t in enumerate(subtasks):
                        t.status = plan_data["subtasks"][i].get("status", "pending")
                        t.result = plan_data["subtasks"][i].get("result")
                        t.error  = plan_data["subtasks"][i].get("error")
                    self.active_plan = Plan(plan_data["goal"], subtasks)
                    self.active_plan.status = plan_data.get("status", "active")
                    # Find first pending task index
                    self.current_task_idx = next(
                        (i for i, t in enumerate(subtasks) if t.status == "pending"), -1
                    )

            saved_at = saved.get("saved_at", "unknown")
            logger.info(f"Agent state restored from checkpoint ({saved_at}).")
            return True
        except Exception as e:
            logger.error(f"Failed to restore agent state: {e}")
            return False
