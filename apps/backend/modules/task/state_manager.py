import logging
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

class CancellationToken:
    """
    Thread-safe CancellationToken to abort running tool operations, loops, or wait states.
    """
    def __init__(self):
        self._is_cancelled = False
        self._callbacks = []
        self._lock = threading.Lock()

    def cancel(self):
        with self._lock:
            if self._is_cancelled:
                return
            self._is_cancelled = True
        logger.info("Cancellation token triggered.")
        for cb in self._callbacks:
            try:
                cb()
            except Exception as e:
                logger.error(f"Error in cancellation callback: {e}")

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._is_cancelled

    def register_callback(self, callback):
        with self._lock:
            if self._is_cancelled:
                try:
                    callback()
                except Exception as e:
                    logger.error(f"Error executing callback on cancelled token: {e}")
            else:
                self._callbacks.append(callback)

class SubTask:
    def __init__(self, description: str, task_id: int = None, tool_name: Optional[str] = None, dependencies: List[int] = None, args: Optional[Dict[str, Any]] = None, verify_condition_type: Optional[str] = None, verify_target: Optional[str] = None, execution_mode: str = "deterministic", grounding_hint: Optional[Dict[str, Any]] = None, critical: bool = True, attempt_count: int = 0, failure_category: Optional[str] = None, execution_context: str = "auto"):
        self.id = task_id if task_id is not None else id(self)
        self.description = description
        self.tool_name = tool_name
        self.dependencies = dependencies or []
        self.args = args or {}
        self.verify_condition_type = verify_condition_type
        self.verify_target = verify_target
        self.status = "pending"  # pending, in_progress, completed, failed
        self.result: Optional[str] = None
        self.error: Optional[str] = None
        self.execution_mode = execution_mode
        self.grounding_hint = grounding_hint
        self.critical = critical
        self.attempt_count = attempt_count
        self.failure_category = failure_category
        self.execution_context = execution_context

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "tool_name": self.tool_name,
            "dependencies": self.dependencies,
            "args": self.args,
            "verify_condition_type": self.verify_condition_type,
            "verify_target": self.verify_target,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "execution_mode": self.execution_mode,
            "grounding_hint": self.grounding_hint,
            "critical": self.critical,
            "attempt_count": self.attempt_count,
            "failure_category": self.failure_category,
            "execution_context": self.execution_context
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
    """
    AgentStateManager coordinates active execution flows, subtask progress, and transient session states.

    SYSTEM PROMPT:
    Initialize or query AgentStateManager to set goals, fetch the next executable task, transition execution phases, or persist/restore checkpoints.

    SHORT DESCRIPTION:
    Central singleton managing current objectives, active multi-step plans, cascade blockers, window contexts, and execution logs.

    PROCESS:
    1. Holds and updates the global agent execution status (IDLE, PLANNING, EXECUTING, etc.).
    2. Builds plans, tracks subtasks indices, and resolves dependency chains to return next runnable tasks.
    3. Handles task completion statuses, cascades failure states to downstream dependencies, and updates logs.
    4. Serializes active goals, plans, history lists, and screen maps to SQLite databases for recovery, or deserializes them.

    FLOW:
    Caller -> set_plan() -> get_next_task() -> update_task_status() -> persist_state() -> MemoryManager -> SQLite -> Caller
    """

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
        self.recovery_attempts: int = 0
        self.cancel_token = CancellationToken()
        self._state_lock = threading.Lock()
        logger.info("AgentStateManager initialized.")

    def set_plan(self, goal: str, subtasks: List[SubTask], is_replan: bool = False):
        with self._state_lock:
            if not is_replan:
                self.recovery_attempts = 0
            self.cancel_token.cancel() # Cancel any old tasks
            self.cancel_token = CancellationToken() # Fresh token
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
        self._auto_persist()

    def _auto_persist(self):
        try:
            from container import ServiceContainer
            mem = ServiceContainer.instance().get_or_none("memory")
            if mem:
                self.persist_state(mem)
        except Exception:
            pass

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
                        res_task = task
                        break
                    else:
                        res_task = None
            else:
                res_task = None
                        
            # If no task can run, check if all are completed or blocked
            all_done = all(t.status in ("completed", "blocked") for t in self.active_plan.subtasks)
            if all_done:
                self.active_plan.status = "completed"
            
        if res_task:
            self._auto_persist()
        return res_task

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
        self._auto_persist()


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
            self.cancel_token.cancel()
            self.cancel_token = CancellationToken()
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
            try:
                from container import ServiceContainer
                observer = ServiceContainer.instance().get_or_none("screen_observer")
                if observer:
                    observer.set_frequency(new_state.value)
            except Exception as e:
                logger.debug(f"Failed to dynamically adjust ScreenObserver frequency: {e}")

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
                    subtasks = []
                    for t in plan_data.get("subtasks", []):
                        subtasks.append(SubTask(
                            description=t.get("description", ""),
                            task_id=t.get("id"),
                            tool_name=t.get("tool_name"),
                            dependencies=t.get("dependencies", []),
                            args=t.get("args", {}),
                            verify_condition_type=t.get("verify_condition_type"),
                            verify_target=t.get("verify_target"),
                            execution_mode=t.get("execution_mode", "deterministic"),
                            grounding_hint=t.get("grounding_hint"),
                            critical=t.get("critical", True),
                            attempt_count=t.get("attempt_count", 0),
                            failure_category=t.get("failure_category")
                        ))
                    for i, t in enumerate(subtasks):
                        pt = plan_data["subtasks"][i]
                        t.status = pt.get("status", "pending")
                        t.result = pt.get("result")
                        t.error  = pt.get("error")
                        t.attempt_count = pt.get("attempt_count", 0)
                        t.failure_category = pt.get("failure_category")
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
