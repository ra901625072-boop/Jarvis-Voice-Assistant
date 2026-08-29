import logging
from typing import List
from modules.task.state_manager import SubTask
from modules.planning.task_graph import TaskGraph

logger = logging.getLogger("JARVIS.DAGCompiler")

class DAGCompiler:
    """
    DAGCompiler parses, validates, and topologically sorts a collection of SubTasks with dependencies.
    Bridges legacy SubTask structures with the high-performance TaskGraph engine.
    """
    @staticmethod
    def validate_and_sort(subtasks: List[SubTask]) -> List[SubTask]:
        """
        Validates the subtask dependency graph for circular dependencies.
        Returns a topologically sorted list of SubTasks if valid, or raises a ValueError.
        """
        if not subtasks:
            return []
        graph = TaskGraph.from_subtasks(subtasks)
        return graph.to_subtasks()

    @staticmethod
    def get_independent_groups(subtasks: List[SubTask]) -> List[List[SubTask]]:
        """
        Groups subtasks into lists that can be executed in parallel phases.
        Phase 0 contains all tasks with no dependencies.
        Phase 1 contains tasks that depend only on Phase 0, etc.
        """
        if not subtasks:
            return []
        graph = TaskGraph.from_subtasks(subtasks)
        layers = graph.get_parallel_layers()
        groups: List[List[SubTask]] = []
        for layer in layers:
            groups.append([node.to_legacy_subtask() for node in layer])
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
                if any(k in desc_lower or k in tool_lower for k in ["read_file", "write_file", "delete", "move", "write the python code", "write python", "write code"]):
                    if any(k in prev_desc_lower or k in prev_tool_lower for k in ["create_file", "create_folder"]):
                        task.dependencies.append(prev_task.id)
                        break
                        
                # Rule 3: Typing or clicking in a window depends on focusing/opening it
                if any(k in desc_lower or k in tool_lower for k in ["type_text", "click_mouse", "press_key"]):
                    if any(k in prev_desc_lower or k in prev_tool_lower for k in ["open_application", "focus_window"]):
                        task.dependencies.append(prev_task.id)
                        break

                # Rule 4: Executing a script or terminal command depends on preceding file creation or code writing tasks
                if any(k in desc_lower or k in tool_lower for k in ["run", "execute", "command", "terminal", "python"]):
                    if any(k in prev_desc_lower or k in prev_tool_lower for k in ["create_file", "write", "code"]):
                        task.dependencies.append(prev_task.id)
                        break
        return subtasks
