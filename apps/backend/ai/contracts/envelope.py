"""
envelope.py — Versioned inter-agent envelope structures and contract definitions.
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional, List, Union
from enum import Enum
import time
import uuid
import json

class MessageKind(str, Enum):
    TASK_REQUEST = "task_request"
    PROGRESS_UPDATE = "progress_update"
    PARTIAL_RESULT = "partial_result"
    VERIFICATION_REPORT = "verification_report"
    FAILURE_REPORT = "failure_report"
    HANDOFF = "handoff_packet"
    CANCEL = "cancel_signal"

class TaskPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4

class ExecutionContext(str, Enum):
    FOREGROUND = "foreground"  # Visual, user-facing, on-screen interaction
    BACKGROUND = "background"  # Silent, headless, background processing
    AUTO = "auto"              # Inferred automatically by TaskVisibilityEngine

@dataclass
class AgentTask:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_type: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    origin_agent: str = "coordinator"
    target_agent: str = "broadcast"
    priority: TaskPriority = TaskPriority.NORMAL
    timeout_seconds: Optional[float] = None
    parent_task_id: Optional[str] = None
    dispatch_chain: List[str] = field(default_factory=list)
    execution_context: str = "auto"
    
    # ── Multi-Agent Swarm Enveloping ──────────────────────────────────────────
    correlation_id: str = ""
    idempotency_key: str = ""
    success_criteria: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"


    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if isinstance(self.priority, TaskPriority):
            data["priority"] = self.priority.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentTask":
        d = dict(data)
        if "priority" in d and isinstance(d["priority"], int):
            d["priority"] = TaskPriority(d["priority"])
        return cls(**d)

@dataclass
class AgentResult:
    task_id: str
    success: bool
    result: Any
    error: Optional[str] = None
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── Confidence & Telemetry envelope ──────────────────────────────────────
    confidence: float = 0.0       # 0.0–1.0, agent's self-assessed certainty
    tokens_used: int = 0          # LLM tokens consumed
    cost_usd: float = 0.0         # estimated cost
    retries: int = 0              # retry count
    source: str = "agent"         # "memory", "cache", "llm", "tool", "static"
    error_category: Optional[str] = None  # e.g. "timeout", "tool_failure", "verification_failed"
    schema_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentResult":
        return cls(**data)

@dataclass
class VerificationReport:
    task_id: str
    verified: bool
    score: float = 1.0
    feedback: str = ""
    criteria_results: Dict[str, bool] = field(default_factory=dict)
    schema_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationReport":
        return cls(**data)

@dataclass
class HandoffPacket:
    from_agent: str
    to_agent: str
    reason: str
    context_delta: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HandoffPacket":
        return cls(**data)

@dataclass
class Envelope:
    kind: MessageKind
    correlation_id: str
    payload: Dict[str, Any]
    sender: str
    target: str
    schema_version: str = "1.0"
    timestamp_ms: float = field(default_factory=lambda: time.time() * 1000.0)
    idempotency_key: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value if isinstance(self.kind, MessageKind) else self.kind,
            "correlation_id": self.correlation_id,
            "payload": self.payload,
            "sender": self.sender,
            "target": self.target,
            "schema_version": self.schema_version,
            "timestamp_ms": self.timestamp_ms,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Envelope":
        d = dict(data)
        if "kind" in d and isinstance(d["kind"], str):
            d["kind"] = MessageKind(d["kind"])
        return cls(**d)

class AgentTaskTypes:
    # Memory
    RETRIEVE_CONTEXT = "retrieve_context"
    STORE_EPISODIC = "store_episodic"
    RECORD_EXECUTION_REPORT = "record_execution_report"
    RUN_MAINTENANCE = "run_maintenance"
    HEALTH_CHECK = "health_check"
    RETRIEVE_WORKFLOW = "retrieve_workflow"
    RETRIEVE_UNRELIABLE_TOOLS = "retrieve_unreliable_tools"
    RETRIEVE_AGENT_STATS = "retrieve_agent_stats"

    # Planning & Execution
    CREATE_PLAN = "create_plan"
    REPLAN = "replan"
    EXECUTE_PLAN = "execute_plan"
    GET_WORLD_STATE = "get_world_state"

    # Verification & Recovery
    VERIFY_RESULT = "verify_result"
    RECOVER_FAILURE = "recover_failure"
    DIAGNOSE_ERROR = "diagnose_error"
    APPLY_SELF_HEALING = "apply_self_healing"
    VERIFY_FIX = "verify_fix"

    # Communication
    SPEAK = "speak"

    # Worker flows
    AUTOMATE_WEB_FLOW = "automate_web_flow"
    CALL_API = "call_api"
    WEBHOOK_FLOW = "webhook_flow"
    CALL_GRAPHQL = "call_graphql"
    AUTHENTICATE = "authenticate"
    CONNECT_SERVICE = "connect_service"
    SYNC_DATA = "sync_data"
    WRITE_CODE = "write_code"
    REFACTOR_CODE = "refactor_code"
    BUILD_PROJECT = "build_project"
    ANALYZE_SCREEN = "analyze_screen"
    FIND_UI_ELEMENT = "find_ui_element"
    READ_SCREEN_TEXT = "read_screen_text"
    LOCATE_ORDINAL_ELEMENT = "locate_ordinal_element"
    COUNT_VISIBLE_ITEMS = "count_visible_items"
    DIFF_SCREEN_STATE = "diff_screen_state"
    RUN_GROUNDED_TASK = "run_grounded_task"
    ROUTE_SUBTASK = "route_subtask"

    # Coordinator
    GENERATE_CONTEXT = "generate_context"
    SELECT_AGENT = "select_agent"
    ANALYZE_FAILURE = "analyze_failure"
    COORDINATE_FLOW = "coordinate_flow"
    ARBITRATE = "arbitrate"
    EXECUTE_GOAL = "execute_goal"

    # Language
    DETECT_LANGUAGE = "detect_language"
    TRANSLATE_TEXT = "translate_text"
    EXTRACT_DOCUMENT_DATA = "extract_document_data"
    SET_LANGUAGE_PREFERENCE = "set_language_preference"
    GET_LANGUAGE_PREFERENCE = "get_language_preference"

    # Learning Agent
    ANALYZE_OUTCOME = "analyze_outcome"
    REVIEW_FAILURE_PATTERN = "review_failure_pattern"
    REVIEW_SUCCESS_PATTERN = "review_success_pattern"
    EVALUATE_AGENT_CAPABILITY = "evaluate_agent_capability"
    GENERATE_CURRICULUM = "generate_curriculum"
    PROPOSE_PROMPT_PATCH = "propose_prompt_patch"
    PROPOSE_ROUTING_CHANGE = "propose_routing_change"
    BUILD_REGRESSION_CASE = "build_regression_case"
    SUMMARIZE_LEARNING_CYCLE = "summarize_learning_cycle"
    AUDIT_LEARNING_HEALTH = "audit_learning_health"

    # UI/UX Design
    DESIGN_REVIEW = "design_review"
    GENERATE_WIREFRAME = "generate_wireframe"
    GENERATE_HIFI_SPEC = "generate_hifi_spec"
    AUDIT_ACCESSIBILITY = "audit_accessibility"
    GENERATE_DESIGN_TOKENS = "generate_design_tokens"
    DESIGN_RESEARCH = "design_research"
