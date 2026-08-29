"""
replanner.py — Dynamic Replanning and Error Diagnosis Engine for Jarvis.
Provides automated failure classification, localized retry/adaptation,
subtree invalidation and grafting, and global strategy pivoting.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from modules.planning.task_graph import TaskGraph, TaskNode, TaskStatus, RiskLevel

logger = logging.getLogger("JARVIS.Replanner")


class ErrorCategory(str, Enum):
    TRANSIENT = "transient"                       # Timeout, rate limit, socket/network reset, temporary lock
    PARAMETER_FORMAT = "parameter_format"         # Bad JSON, missing required argument, type mismatch
    RESOURCE_NOT_FOUND = "resource_not_found"     # File missing, URL 404, DOM element / selector not found
    PERMISSION_DENIED = "permission_denied"       # OS Access Denied, SecurityManager Tier blocked, HITL required
    VERIFICATION_FAILED = "verification_failed"   # Output exists but didn't meet Definition of Done
    TOOL_CRASH = "tool_crash"                     # Unhandled exception inside tool logic
    FATAL = "fatal"                               # Unrecoverable system or environment failure
    UNKNOWN = "unknown"


class ReplanStrategy(str, Enum):
    LOCAL_RETRY = "local_retry"         # Retry the same node with backoff
    LOCAL_ADAPT = "local_adapt"         # Modify node parameters or fallback to an alternate tool
    SUBTREE_REPLAN = "subtree_replan"   # Invalidate downstream tasks and graft a recovery subgraph
    GLOBAL_REPLAN = "global_replan"     # Re-synthesize the entire workflow
    ESCALATE = "escalate"               # Request human intervention / permission approval


@dataclass
class FailureDiagnosis:
    category: ErrorCategory
    root_cause: str
    recommended_strategy: ReplanStrategy
    can_retry: bool = True
    retry_delay_seconds: float = 1.0
    suggested_fix: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class Replanner:
    """
    Diagnoses task execution failures and adapts the TaskGraph dynamically.
    """
    def __init__(self, memory_manager=None, llm_client=None):
        self.memory_manager = memory_manager
        self.llm_client = llm_client

    def diagnose_failure(
        self,
        node: TaskNode,
        error_msg: str,
        execution_context: Optional[Dict[str, Any]] = None
    ) -> FailureDiagnosis:
        """
        Classifies errors into taxonomy categories and determines the optimal recovery strategy.
        """
        err_lower = (error_msg or "").lower()
        node_attempts = node.attempt_count

        # 1. Transient network / timeout errors
        if any(w in err_lower for w in ["timeout", "timed out", "connection reset", "rate limit", "429", "503", "temporarily unavailable", "econnreset"]):
            if node_attempts < node.max_retries:
                delay = min(2.0 ** node_attempts, 10.0)
                return FailureDiagnosis(
                    category=ErrorCategory.TRANSIENT,
                    root_cause=f"Transient network or timeout error: {error_msg}",
                    recommended_strategy=ReplanStrategy.LOCAL_RETRY,
                    can_retry=True,
                    retry_delay_seconds=delay,
                    suggested_fix="Retry after exponential backoff delay."
                )
            else:
                return FailureDiagnosis(
                    category=ErrorCategory.TRANSIENT,
                    root_cause=f"Exceeded max retries ({node.max_retries}) on transient error.",
                    recommended_strategy=ReplanStrategy.SUBTREE_REPLAN,
                    can_retry=False,
                    suggested_fix="Inject fallback source or alternate network tool."
                )

        # 2. Permission / Security blocks
        if any(w in err_lower for w in ["permission denied", "access denied", "forbidden", "unauthorized", "tier_forbidden", "approval required"]):
            return FailureDiagnosis(
                category=ErrorCategory.PERMISSION_DENIED,
                root_cause=f"Security or permission boundary triggered: {error_msg}",
                recommended_strategy=ReplanStrategy.ESCALATE,
                can_retry=False,
                suggested_fix="Escalate to user for explicit authorization."
            )

        # 3. Missing resources / File not found / DOM element not found
        if any(w in err_lower for w in ["filenotfounderror", "no such file", "not found", "404", "element not found", "cannot locate element", "selector not found"]):
            return FailureDiagnosis(
                category=ErrorCategory.RESOURCE_NOT_FOUND,
                root_cause=f"Required target resource was not found: {error_msg}",
                recommended_strategy=ReplanStrategy.SUBTREE_REPLAN,
                can_retry=True,
                suggested_fix="Inject discovery, file creation, or visual search prerequisite task."
            )

        # 4. Parameter / JSON formatting errors
        if any(w in err_lower for w in ["jsondecodeerror", "validation error", "missing argument", "invalid argument", "unexpected keyword", "typeerror", "valueerror"]):
            if node_attempts < 2:
                return FailureDiagnosis(
                    category=ErrorCategory.PARAMETER_FORMAT,
                    root_cause=f"Tool invocation parameters were invalid: {error_msg}",
                    recommended_strategy=ReplanStrategy.LOCAL_ADAPT,
                    can_retry=True,
                    suggested_fix="Re-format arguments according to tool schema."
                )
            else:
                return FailureDiagnosis(
                    category=ErrorCategory.PARAMETER_FORMAT,
                    root_cause=f"Parameter adaptation failed after {node_attempts} attempts.",
                    recommended_strategy=ReplanStrategy.SUBTREE_REPLAN,
                    can_retry=False
                )

        # 5. Verification failure (Definition of Done not met)
        if any(w in err_lower for w in ["verification failed", "definition of done", "outcome mismatch", "check failed"]):
            return FailureDiagnosis(
                category=ErrorCategory.VERIFICATION_FAILED,
                root_cause=f"Task completed execution but failed validation: {error_msg}",
                recommended_strategy=ReplanStrategy.SUBTREE_REPLAN,
                can_retry=True,
                suggested_fix="Re-execute with corrective parameters or run auxiliary repair task."
            )

        # 6. Default / Unknown
        if node_attempts < node.max_retries:
            return FailureDiagnosis(
                category=ErrorCategory.UNKNOWN,
                root_cause=error_msg or "Unknown execution failure",
                recommended_strategy=ReplanStrategy.LOCAL_RETRY,
                can_retry=True,
                retry_delay_seconds=1.0
            )
        else:
            return FailureDiagnosis(
                category=ErrorCategory.FATAL,
                root_cause=f"Fatal failure after {node_attempts} attempts: {error_msg}",
                recommended_strategy=ReplanStrategy.GLOBAL_REPLAN,
                can_retry=False,
                suggested_fix="Re-synthesize overall plan or notify user."
            )

    def apply_recovery(
        self,
        graph: TaskGraph,
        failed_task_id: str,
        diagnosis: FailureDiagnosis,
        recovery_nodes: Optional[List[TaskNode]] = None
    ) -> Tuple[TaskGraph, ReplanStrategy]:
        """
        Applies the diagnosed recovery strategy directly to the TaskGraph.
        Returns the updated TaskGraph and the strategy applied.
        """
        node = graph.get_node(failed_task_id)
        if not node:
            logger.error(f"Cannot apply recovery on missing node: {failed_task_id}")
            return graph, ReplanStrategy.ESCALATE

        strategy = diagnosis.recommended_strategy
        node.attempt_count += 1
        node.error = diagnosis.root_cause

        logger.info(f"Applying recovery strategy '{strategy.value}' on task '{failed_task_id}' (attempt {node.attempt_count})")

        if strategy == ReplanStrategy.LOCAL_RETRY:
            node.status = TaskStatus.READY
            
        elif strategy == ReplanStrategy.LOCAL_ADAPT:
            node.status = TaskStatus.READY
            if diagnosis.details.get("adjusted_args"):
                node.args.update(diagnosis.details["adjusted_args"])
            if diagnosis.details.get("alternate_tool"):
                node.tool_name = diagnosis.details["alternate_tool"]

        elif strategy == ReplanStrategy.SUBTREE_REPLAN:
            # 1. Invalidate subtree from the failed node onwards
            graph.invalidate_subtree(failed_task_id, include_root=True)
            
            # 2. If recovery nodes are provided, graft them into the graph
            if recovery_nodes:
                for rnode in recovery_nodes:
                    graph.add_node(rnode)
                # Rewire the failed node to depend on the last recovery node
                last_recovery_id = recovery_nodes[-1].task_id
                if last_recovery_id != node.task_id and last_recovery_id not in node.dependencies:
                    graph.add_dependency(node.task_id, last_recovery_id)
                    
            node.status = TaskStatus.READY

        elif strategy == ReplanStrategy.GLOBAL_REPLAN:
            # Mark all incomplete nodes for global regeneration
            for n in graph.nodes.values():
                if n.status != TaskStatus.COMPLETED:
                    n.status = TaskStatus.INVALIDATED

        elif strategy == ReplanStrategy.ESCALATE:
            node.status = TaskStatus.FAILED

        # Log pattern to memory if available
        self._record_failure_lesson(failed_task_id, node.title, diagnosis)

        return graph, strategy

    def _record_failure_lesson(self, task_id: str, title: str, diagnosis: FailureDiagnosis):
        """Persists the failure diagnosis and recovery pattern to memory."""
        if not self.memory_manager:
            return
        try:
            lesson_entry = {
                "task_id": task_id,
                "task_title": title,
                "category": diagnosis.category.value,
                "root_cause": diagnosis.root_cause,
                "strategy": diagnosis.recommended_strategy.value,
                "suggested_fix": diagnosis.suggested_fix
            }
            if hasattr(self.memory_manager, "add_lesson"):
                self.memory_manager.add_lesson(lesson_entry)
            logger.debug(f"Saved failure lesson for task {task_id}")
        except Exception as e:
            logger.warning(f"Could not persist failure lesson: {e}")
