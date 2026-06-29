import logging
from collections import deque
from typing import List, Dict, Set
from modules.core.state_manager import SubTask

logger = logging.getLogger("JARVIS.DAGCompiler")

class DAGCompiler:
    """
    DAGCompiler parses, validates, and topologically sorts a collection of SubTasks with dependencies.
    """
    @staticmethod
    def validate_and_sort(subtasks: List[SubTask]) -> List[SubTask]:
        """
        Validates the subtask dependency graph for circular dependencies.
        Returns a topologically sorted list of SubTasks if valid, or raises a ValueError.
        """
        # Build adjacency list and in-degrees
        graph: Dict[int, List[int]] = {}
        in_degree: Dict[int, int] = {}
        task_map: Dict[int, SubTask] = {}
        
        for task in subtasks:
            task_map[task.id] = task
            if task.id not in graph:
                graph[task.id] = []
            if task.id not in in_degree:
                in_degree[task.id] = 0
                
            for dep_id in task.dependencies:
                if dep_id not in graph:
                    graph[dep_id] = []
                graph[dep_id].append(task.id)
                in_degree[task.id] += 1

        # DFS Cycle Detection
        visited: Dict[int, int] = {} # 0=unvisited, 1=visiting, 2=visited
        
        def has_cycle(node_id: int) -> bool:
            visited[node_id] = 1 # visiting
            for neighbor in graph.get(node_id, []):
                if visited.get(neighbor, 0) == 1:
                    return True
                elif visited.get(neighbor, 0) == 0:
                    if has_cycle(neighbor):
                        return True
            visited[node_id] = 2 # visited
            return False

        for node_id in list(task_map.keys()):
            if visited.get(node_id, 0) == 0:
                if has_cycle(node_id):
                    logger.error(f"Circular dependency detected in plan involving node {node_id}.")
                    raise ValueError("Circular dependency detected in the plan.")

        # Kahn's Algorithm for Topological Sort using deque for O(1) pops
        queue = deque(t_id for t_id in task_map if in_degree[t_id] == 0)
        sorted_ids = []

        # Sort initial queue to maintain stable starting order
        queue = deque(sorted(queue))

        while queue:
            node_id = queue.popleft()  # O(1) instead of list.pop(0) O(n)
            sorted_ids.append(node_id)

            for neighbor in graph.get(node_id, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
                    
        if len(sorted_ids) != len(subtasks):
            raise ValueError("Invalid DAG structure or unreachable nodes.")
            
        sorted_tasks = [task_map[t_id] for t_id in sorted_ids]
        return sorted_tasks

    @staticmethod
    def get_independent_groups(subtasks: List[SubTask]) -> List[List[SubTask]]:
        """
        Groups subtasks into lists that can be executed in parallel phases.
        Phase 0 contains all tasks with no dependencies.
        Phase 1 contains tasks that depend only on Phase 0, etc.
        """
        # Validate first
        sorted_tasks = DAGCompiler.validate_and_sort(subtasks)
        
        # Track depth/layer for each node
        depths: Dict[int, int] = {}
        task_map = {t.id: t for t in subtasks}
        
        for task in sorted_tasks:
            if not task.dependencies:
                depths[task.id] = 0
            else:
                max_dep_depth = max(depths.get(dep_id, 0) for dep_id in task.dependencies)
                depths[task.id] = max_dep_depth + 1
                
        # Group by depth
        max_depth = max(depths.values()) if depths else -1
        groups: List[List[SubTask]] = [[] for _ in range(max_depth + 1)]
        
        for task_id, depth in depths.items():
            groups[depth].append(task_map[task_id])
            
        return groups

    @staticmethod
    def compile_dependencies(subtasks: List[SubTask]) -> List[SubTask]:
        """
        Infers dependencies between subtasks dynamically based on their descriptions,
        tool inputs/outputs, and sequential relationships if not explicitly specified.
        """
        for i, task in enumerate(subtasks):
            if task.dependencies:
                continue
                
            desc_lower = task.description.lower()
            tool_lower = (task.tool_name or "").lower()
            
            # Check all preceding tasks to see if this task depends on them
            for prev_task in subtasks[:i]:
                prev_desc_lower = prev_task.description.lower()
                prev_tool_lower = (prev_task.tool_name or "").lower()
                
                # Rule 1: Browser search / navigation depends on opening browser
                if any(k in desc_lower or k in tool_lower for k in ["search", "url", "click_dom", "fill_form"]):
                    if any(k in prev_desc_lower or k in prev_tool_lower for k in ["open_url", "chrome", "edge", "browser"]):
                        task.dependencies.append(prev_task.id)
                        break
                        
                # Rule 2: File operations (write/read/delete/move) depend on file creation / foldering
                if any(k in desc_lower or k in tool_lower for k in ["read_file", "write_file", "delete", "move"]):
                    if any(k in prev_desc_lower or k in prev_tool_lower for k in ["create_file", "create_folder"]):
                        task.dependencies.append(prev_task.id)
                        break
                        
                # Rule 3: Typing or clicking in a window depends on focusing/opening it
                if any(k in desc_lower or k in tool_lower for k in ["type_text", "click_mouse", "press_key"]):
                    if any(k in prev_desc_lower or k in prev_tool_lower for k in ["open_application", "focus_window"]):
                        task.dependencies.append(prev_task.id)
                        break
        return subtasks
