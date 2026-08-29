"""
task_graph.py — Directed Acyclic Graph (DAG) Engine for Jarvis Planning Agent.
Provides strongly typed TaskNode, TaskStatus, TaskGraph management,
topological sorting, cycle detection, parallel layering, and subtree invalidation.
"""
from __future__ import annotations
import logging
from collections import deque
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union
from datetime import datetime

logger = logging.getLogger("JARVIS.TaskGraph")


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    INVALIDATED = "invalidated"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class TaskNode:
    """
    Strongly typed executable task node inside the TaskGraph.
    """
    task_id: str
    title: str
    description: str = ""
    agent: str = "execution_agent"
    tool_name: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    expected_outputs: List[str] = field(default_factory=list)
    definition_of_done: List[str] = field(default_factory=list)
    verify_condition_type: Optional[str] = None
    verify_target: Optional[str] = None
    execution_context: str = "auto"
    risk_level: RiskLevel = RiskLevel.LOW
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    attempt_count: int = 0
    max_retries: int = 3
    critical: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.task_id = str(self.task_id)
        self.dependencies = [str(dep) for dep in self.dependencies]
        if isinstance(self.status, str) and not isinstance(self.status, TaskStatus):
            try:
                self.status = TaskStatus(self.status.lower())
            except ValueError:
                self.status = TaskStatus.PENDING
        if isinstance(self.risk_level, str) and not isinstance(self.risk_level, RiskLevel):
            try:
                self.risk_level = RiskLevel(self.risk_level.lower())
            except ValueError:
                self.risk_level = RiskLevel.LOW

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value if isinstance(self.status, TaskStatus) else str(self.status)
        data["risk_level"] = self.risk_level.value if isinstance(self.risk_level, RiskLevel) else str(self.risk_level)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskNode:
        d = dict(data)
        if "id" in d and "task_id" not in d:
            d["task_id"] = str(d.pop("id"))
        if "task" in d and "title" not in d:
            d["title"] = d.pop("task")
        if "depends_on" in d and "dependencies" not in d:
            d["dependencies"] = d.pop("depends_on")
        
        # Filter unknown keys to avoid TypeError on extra fields
        known_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in d.items() if k in known_keys}
        if "title" not in filtered:
            filtered["title"] = filtered.get("description", filtered.get("task_id", "Task"))
        return cls(**filtered)

    def to_legacy_subtask(self) -> Any:
        """Converts TaskNode to legacy SubTask format for backwards compatibility."""
        from modules.task.state_manager import SubTask
        try:
            int_id = int(self.task_id)
        except ValueError:
            int_id = hash(self.task_id) % 1000000
            
        int_deps = []
        for dep in self.dependencies:
            try:
                int_deps.append(int(dep))
            except ValueError:
                int_deps.append(hash(dep) % 1000000)

        subtask = SubTask(
            description=self.title or self.description,
            task_id=int_id,
            tool_name=self.tool_name,
            dependencies=int_deps,
            args=self.args,
            verify_condition_type=self.verify_condition_type,
            verify_target=self.verify_target,
            critical=self.critical,
            attempt_count=self.attempt_count,
            execution_context=self.execution_context
        )
        subtask.status = self.status.value if isinstance(self.status, TaskStatus) else str(self.status)
        subtask.result = str(self.result) if self.result is not None else None
        subtask.error = self.error
        return subtask

    @classmethod
    def from_legacy_subtask(cls, subtask: Any) -> TaskNode:
        """Constructs a TaskNode from a legacy SubTask."""
        return cls(
            task_id=str(subtask.id),
            title=subtask.description,
            description=subtask.description,
            tool_name=subtask.tool_name,
            dependencies=[str(d) for d in subtask.dependencies],
            args=subtask.args or {},
            verify_condition_type=subtask.verify_condition_type,
            verify_target=subtask.verify_target,
            execution_context=getattr(subtask, "execution_context", "auto"),
            critical=getattr(subtask, "critical", True),
            attempt_count=getattr(subtask, "attempt_count", 0),
            status=TaskStatus(subtask.status.lower()) if hasattr(subtask, "status") and subtask.status in TaskStatus._value2member_map_ else TaskStatus.PENDING,
            result=getattr(subtask, "result", None),
            error=getattr(subtask, "error", None)
        )


class TaskGraph:
    """
    Dependency-aware Directed Acyclic Graph (DAG) for managing multi-agent tasks.
    Supports topological sorting, cycle detection, parallel layering,
    dynamic subtree invalidation, and subgraph grafting.
    """
    def __init__(self, goal: str = "", graph_id: Optional[str] = None):
        self.graph_id = graph_id or f"graph_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        self.goal = goal
        self.created_at = datetime.now()
        self.nodes: Dict[str, TaskNode] = {}
        # Forward edges: node_id -> set of dependent node_ids (nodes that depend on node_id)
        self.dependents: Dict[str, Set[str]] = {}
        # Reverse edges: node_id -> set of dependency node_ids (nodes that node_id depends on)
        self.dependencies: Dict[str, Set[str]] = {}

    def add_node(self, node: TaskNode) -> TaskNode:
        """Adds or updates a TaskNode in the graph and updates edge indexes."""
        task_id = str(node.task_id)
        self.nodes[task_id] = node
        
        if task_id not in self.dependents:
            self.dependents[task_id] = set()
        if task_id not in self.dependencies:
            self.dependencies[task_id] = set()

        for dep in node.dependencies:
            dep_id = str(dep)
            if dep_id not in self.dependents:
                self.dependents[dep_id] = set()
            self.dependents[dep_id].add(task_id)
            self.dependencies[task_id].add(dep_id)

        return node

    def add_dependency(self, task_id: str, dep_id: str):
        """Adds a dependency edge (task_id depends on dep_id)."""
        task_id = str(task_id)
        dep_id = str(dep_id)
        node = self.get_node(task_id)
        if node and dep_id not in node.dependencies:
            node.dependencies.append(dep_id)
        if dep_id not in self.dependents:
            self.dependents[dep_id] = set()
        self.dependents[dep_id].add(task_id)
        if task_id not in self.dependencies:
            self.dependencies[task_id] = set()
        self.dependencies[task_id].add(dep_id)

    def remove_node(self, task_id: str):
        """Removes a node and cleans up all associated edges."""
        task_id = str(task_id)
        if task_id not in self.nodes:
            return

        # Remove from nodes that depend on this node
        for dep_id in self.dependencies.get(task_id, set()):
            if dep_id in self.dependents:
                self.dependents[dep_id].discard(task_id)

        # Remove from nodes this node depends on
        for dependent_id in self.dependents.get(task_id, set()):
            if dependent_id in self.dependencies:
                self.dependencies[dependent_id].discard(task_id)
                # Also remove from TaskNode's internal list
                if dependent_id in self.nodes:
                    if task_id in self.nodes[dependent_id].dependencies:
                        self.nodes[dependent_id].dependencies.remove(task_id)

        self.nodes.pop(task_id, None)
        self.dependents.pop(task_id, None)
        self.dependencies.pop(task_id, None)

    def get_node(self, task_id: str) -> Optional[TaskNode]:
        return self.nodes.get(str(task_id))

    def update_node_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Any = None,
        error: Optional[str] = None
    ) -> Optional[TaskNode]:
        """Updates status, result, and error of a task node."""
        node = self.get_node(task_id)
        if not node:
            logger.warning(f"Attempted to update status on non-existent node: {task_id}")
            return None
        node.status = status
        if result is not None:
            node.result = result
        if error is not None:
            node.error = error
        return node

    def validate(self) -> bool:
        """
        Validates graph structure:
        1. Checks that all referenced dependencies exist in the graph.
        2. Detects circular dependencies using DFS graph coloring.
        Raises ValueError with clear diagnostics if invalid.
        """
        # 1. Check for missing dependency references
        for task_id, node in self.nodes.items():
            for dep_id in node.dependencies:
                if dep_id not in self.nodes:
                    raise ValueError(f"Task '{task_id}' depends on non-existent Task '{dep_id}'")

        # 2. Cycle detection via 3-color DFS
        visited: Dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=visited
        cycle_path: List[str] = []

        def dfs(curr_id: str) -> bool:
            visited[curr_id] = 1
            cycle_path.append(curr_id)
            for dep_id in self.nodes[curr_id].dependencies:
                state = visited.get(dep_id, 0)
                if state == 1:
                    cycle_path.append(dep_id)
                    return True
                if state == 0:
                    if dfs(dep_id):
                        return True
            cycle_path.pop()
            visited[curr_id] = 2
            return False

        for node_id in list(self.nodes.keys()):
            if visited.get(node_id, 0) == 0:
                if dfs(node_id):
                    cycle_str = " -> ".join(cycle_path)
                    logger.error(f"Circular dependency detected: {cycle_str}")
                    raise ValueError(f"Circular dependency detected in graph: {cycle_str}")

        return True

    def topological_sort(self) -> List[TaskNode]:
        """
        Returns a topologically sorted list of TaskNodes using Kahn's Algorithm.
        """
        self.validate()
        
        in_degree = {task_id: len(node.dependencies) for task_id, node in self.nodes.items()}
        queue = deque(sorted([task_id for task_id, deg in in_degree.items() if deg == 0]))
        sorted_nodes: List[TaskNode] = []

        while queue:
            curr_id = queue.popleft()
            sorted_nodes.append(self.nodes[curr_id])

            for dependent_id in sorted(self.dependents.get(curr_id, set())):
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)

        if len(sorted_nodes) != len(self.nodes):
            raise ValueError("Topological sort failed. Invalid DAG structure.")

        return sorted_nodes

    def get_parallel_layers(self) -> List[List[TaskNode]]:
        """
        Groups nodes into sequential layers (phases) where all nodes in a layer
        can execute in parallel because their dependencies are fully resolved in earlier layers.
        """
        sorted_nodes = self.topological_sort()
        depths: Dict[str, int] = {}

        for node in sorted_nodes:
            if not node.dependencies:
                depths[node.task_id] = 0
            else:
                max_dep_depth = max(depths.get(dep, 0) for dep in node.dependencies)
                depths[node.task_id] = max_dep_depth + 1

        if not depths:
            return []

        max_depth = max(depths.values())
        layers: List[List[TaskNode]] = [[] for _ in range(max_depth + 1)]
        for node in sorted_nodes:
            layers[depths[node.task_id]].append(node)

        return layers

    def get_ready_nodes(self) -> List[TaskNode]:
        """
        Returns all nodes that are currently PENDING or READY and whose
        upstream dependencies are ALL COMPLETED.
        """
        ready_nodes = []
        for task_id, node in self.nodes.items():
            if node.status in (TaskStatus.PENDING, TaskStatus.READY):
                deps_satisfied = True
                for dep_id in node.dependencies:
                    dep_node = self.nodes.get(dep_id)
                    if not dep_node or dep_node.status != TaskStatus.COMPLETED:
                        deps_satisfied = False
                        break
                if deps_satisfied:
                    ready_nodes.append(node)
        return ready_nodes

    def get_downstream_dependents(self, task_id: str) -> Set[str]:
        """
        Returns the set of all downstream transitive dependents of task_id.
        """
        task_id = str(task_id)
        visited = set()
        queue = deque([task_id])

        while queue:
            curr = queue.popleft()
            for dep in self.dependents.get(curr, set()):
                if dep not in visited:
                    visited.add(dep)
                    queue.append(dep)

        return visited

    def invalidate_subtree(self, task_id: str, include_root: bool = True) -> List[str]:
        """
        Marks task_id and all its downstream dependents as INVALIDATED / PENDING,
        clearing stale results and errors. Returns list of invalidated task IDs.
        """
        downstream = self.get_downstream_dependents(task_id)
        target_ids = list(downstream)
        if include_root:
            target_ids.insert(0, str(task_id))

        for tid in target_ids:
            node = self.get_node(tid)
            if node:
                node.status = TaskStatus.INVALIDATED
                node.result = None
                node.error = None

        logger.info(f"Invalidated subtree for root '{task_id}': {target_ids}")
        return target_ids

    def graft_subgraph(self, new_nodes: List[TaskNode], attach_to_id: Optional[str] = None):
        """
        Grafts a list of new nodes into the graph.
        If attach_to_id is provided, new nodes that have no explicit dependencies
        will depend on attach_to_id.
        """
        for node in new_nodes:
            if attach_to_id and not node.dependencies:
                node.dependencies = [str(attach_to_id)]
            self.add_node(node)

        self.validate()
        logger.info(f"Grafted {len(new_nodes)} nodes into TaskGraph.")

    def is_completed(self) -> bool:
        """Returns True if all nodes in the graph are COMPLETED or SKIPPED."""
        if not self.nodes:
            return False
        return all(n.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED) for n in self.nodes.values())

    def is_failed(self) -> bool:
        """Returns True if any critical node in the graph is FAILED or CANCELLED without recovery."""
        for n in self.nodes.values():
            if n.status in (TaskStatus.FAILED, TaskStatus.CANCELLED) and n.critical:
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "goal": self.goal,
            "created_at": self.created_at.isoformat(),
            "nodes": {tid: node.to_dict() for tid, node in self.nodes.items()},
            "is_completed": self.is_completed(),
            "is_failed": self.is_failed()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskGraph:
        graph = cls(
            goal=data.get("goal", ""),
            graph_id=data.get("graph_id")
        )
        nodes_dict = data.get("nodes", {})
        for tid, ndata in nodes_dict.items():
            graph.add_node(TaskNode.from_dict(ndata))
        return graph

    @classmethod
    def from_subtasks(cls, subtasks: List[Any], goal: str = "") -> TaskGraph:
        """Creates a TaskGraph from a list of legacy SubTasks."""
        graph = cls(goal=goal)
        for st in subtasks:
            graph.add_node(TaskNode.from_legacy_subtask(st))
        return graph

    def to_subtasks(self) -> List[Any]:
        """Converts all nodes in topological order back to legacy SubTasks."""
        sorted_nodes = self.topological_sort()
        return [node.to_legacy_subtask() for node in sorted_nodes]
