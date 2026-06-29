from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from enum import Enum

class TaskPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4

@dataclass
class AgentTask:
    task_id: str                    # UUID
    task_type: str                  # e.g. "create_plan", "fix_screen_error"
    payload: Dict[str, Any]         # Task-specific parameters
    origin_agent: str               # Who sent this
    target_agent: str               # Who should handle it
    priority: TaskPriority = TaskPriority.NORMAL
    timeout_seconds: float = 30.0
    parent_task_id: Optional[str] = None  # For sub-tasks

@dataclass
class AgentResult:
    task_id: str
    success: bool
    result: Any                     # JSON-serialisable
    error: Optional[str] = None
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
