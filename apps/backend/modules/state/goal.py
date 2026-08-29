"""
goal.py — GoalState model for tracking active multi-step goal execution DAGs.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import time

class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    RECOVERING = "recovering"
    SKIPPED = "skipped"

@dataclass
class DAGNode:
    node_id: str
    task_type: str
    description: str
    payload: Dict[str, Any] = field(default_factory=dict)
    parent_ids: List[str] = field(default_factory=list)
    success_criteria: Dict[str, Any] = field(default_factory=dict)
    assigned_agent: Optional[str] = None
    status: NodeStatus = NodeStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    attempts: int = 0
    verification_score: float = 0.0

@dataclass
class GoalState:
    correlation_id: str
    user_goal: str
    nodes: Dict[str, DAGNode] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    is_completed: bool = False
    is_cancelled: bool = False

    def add_node(self, node: DAGNode):
        self.nodes[node.node_id] = node
        self.updated_at = time.time()

    def get_ready_nodes(self) -> List[DAGNode]:
        ready = []
        for node in self.nodes.values():
            if node.status != NodeStatus.PENDING:
                continue
            # Parents must all be completed
            parents_done = all(
                self.nodes.get(pid) and self.nodes[pid].status == NodeStatus.COMPLETED
                for pid in node.parent_ids
            )
            if parents_done:
                ready.append(node)
        return ready

    def mark_completed(self, node_id: str, result: Any):
        if node_id in self.nodes:
            self.nodes[node_id].status = NodeStatus.COMPLETED
            self.nodes[node_id].result = result
            self.updated_at = time.time()

    def mark_failed(self, node_id: str, error: str):
        if node_id in self.nodes:
            self.nodes[node_id].status = NodeStatus.FAILED
            self.nodes[node_id].error = error
            self.updated_at = time.time()
