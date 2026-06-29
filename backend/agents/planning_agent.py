import logging
import json
from typing import Optional, List, Dict, Any
from agents.base_agent import BaseAgent
from agents.types import AgentTask, AgentResult
from modules.planning.task_planner import TaskPlannerTools
from modules.core.state_manager import SubTask
from modules.planning.dag_compiler import DAGCompiler

logger = logging.getLogger("JARVIS.PlanningAgent")

class PlanningAgent(BaseAgent):
    """
    Decomposes goals into executable DAGs.
    Wraps TaskPlannerTools + DAGCompiler + ActionVerifier.
    Absorbs GoalExecutionSkill logic.
    """
    def __init__(self, memory_agent, bus):
        super().__init__(agent_id="planning_agent")
        self.memory_agent = memory_agent
        self.bus = bus
        # TaskPlannerTools expects a memory object
        memory_mgr = memory_agent.memory if hasattr(memory_agent, "memory") else None
        self.planner = TaskPlannerTools(memory=memory_mgr)
        self.bus.register(self.agent_id, self.handle)

    async def _generate_plan(self, goal: str, context_str: str) -> List[SubTask]:
        prompt = f"""
        You are JARVIS's Task Planner compiler. Given a high-level goal: "{goal}", compile a detailed step-by-step task plan to achieve it.
        
        Execution context to consider:
        {context_str}

        Available tools you can target:
        - 'create_folder' with args: {{"path": "absolute_folder_path"}}
        - 'create_file' with args: {{"path": "absolute_file_path", "content": "file_contents"}}
        - 'run_terminal_command' with args: {{"command": "shell_command_string", "cwd": "optional_working_directory"}}
        - 'open_url' with args: {{"url": "web_url_string"}}
        - 'close_website' with args: {{"domain_or_title": "string"}}
        
        Break the goal down into a dependency-aware JSON array of subtasks.
        For each subtask, specify:
        - 'id': integer unique ID (starting at 1)
        - 'task': descriptive task string
        - 'tool_name': name of the tool to use (must be one of the tools listed above)
        - 'args': dict of arguments matching the tool signature
        - 'depends_on': list of IDs of tasks that must finish before this task starts (empty list if no dependencies)
        
        Ensure paths use forward slashes (e.g. d:/Jarvis/...) for cross-platform compatibility.
        Return ONLY raw JSON, do not include markdown block formatting (do NOT wrap in ```json).
        """

        subtasks_response = await self.generate_response(prompt, response_mime_type="application/json")
        try:
            parsed = self._parse_json_response(subtasks_response)
        except Exception as pe:
            logger.warning(f"Failed to parse subtask plan as JSON: {subtasks_response}. Error: {pe}")
            clean_prompt = f"Convert this text to a valid JSON array of tasks. Text:\n{subtasks_response}"
            clean_res = await self.generate_response(clean_prompt, response_mime_type="application/json")
            parsed = self._parse_json_response(clean_res)

        subtasks = []
        for i, item in enumerate(parsed):
            task_id = item.get("id", i+1)
            desc = item.get("task", item.get("description", "Unknown task"))
            deps = item.get("depends_on", [])
            tool_name = item.get("tool_name", item.get("tool"))
            tool_args = item.get("args", item.get("arguments", item.get("params", {})))
            verify_type = item.get("verify_condition_type", item.get("verify_type"))
            verify_target = item.get("verify_target")
            subtasks.append(SubTask(
                description=desc, 
                task_id=task_id, 
                dependencies=deps, 
                tool_name=tool_name, 
                args=tool_args,
                verify_condition_type=verify_type,
                verify_target=verify_target
            ))
            
        return DAGCompiler.compile_dependencies(subtasks)


    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "create_plan":
                goal = payload.get("goal", "")
                context_str = payload.get("context", "")
                
                # Check static intent plan router first
                subtasks = self.planner.match_static_intent(goal)
                if subtasks:
                    logger.info(f"Fast Intent Plan Router matched goal: '{goal}'")
                else:
                    # Dynamically generate plan
                    subtasks = await self._generate_plan(goal, context_str)

                # Format as AgentPlan list (dictionaries)
                agent_plan = [st.__dict__ for st in subtasks]
                
                # Side effect: register in state manager (from original behavior)
                self.planner.state_manager.set_plan(goal, subtasks)
                
                return self._create_result(task, success=True, result={"plan": agent_plan})
                
            elif task_type == "replan":
                failed_task = payload.get("failed_task", {})
                error = payload.get("error", "")
                
                # Stub for now
                return self._create_result(task, success=True, result={"plan": []})
                
            else:
                return self._create_result(
                    task, 
                    success=False, 
                    error=f"PlanningAgent does not support task type '{task_type}'"
                )
        except Exception as e:
            logger.exception(f"PlanningAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))
