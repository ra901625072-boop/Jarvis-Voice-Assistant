import logging
import json
import time
from livekit.agents import llm
from modules.core.state_manager import AgentStateManager, SubTask, AgentState
from modules.core.memory_manager import MemoryManager
from modules.core.cognitive_coordinator import CognitiveCoordinator
from modules.execution.tool_router import ToolRouter
from modules.execution.success_patterns import SuccessLearner

logger = logging.getLogger("JARVIS.TaskPlanner")

class TaskPlannerTools(llm.Toolset):
    def __init__(self, memory: MemoryManager = None):
        super().__init__(id=self.__class__.__name__.lower())
        self.state_manager = AgentStateManager()
        self.memory = memory
        self.coordinator = CognitiveCoordinator(memory) if memory else None
        self.tool_router = ToolRouter(memory.lifecycle.tool_memory) if memory and hasattr(memory, 'lifecycle') else None
        self.success_learner = SuccessLearner(memory) if memory else None
        self._plan_start_time: float = 0.0  # track execution time

    @llm.function_tool(description="Prepare for planning by retrieving past workflows, known tool risks, and lessons learned for a specific goal. ALWAYS call this before create_plan.")
    async def get_execution_context(self, goal: str) -> str:
        self.state_manager.set_agent_state(AgentState.PLANNING)
        if not self.coordinator:
            return "Cognitive Coordinator is not available."
        return self.coordinator.generate_execution_context(goal)

    @llm.function_tool(description="Create a step-by-step plan for a complex, multi-step goal. Use this before executing complex requests.")
    async def create_plan(self, goal: str, subtasks_json: str) -> str:
        """
        subtasks_json should be a JSON array of objects with dependencies.
        Example: [{"id": 1, "task": "Open Chrome"}, {"id": 2, "task": "Search", "depends_on": [1]}]
        For backwards compatibility, an array of strings is also supported.
        """
        try:
            tasks_list = json.loads(subtasks_json)
            if not isinstance(tasks_list, list):
                return "Error: subtasks_json must be a JSON array."
                
            subtasks = []
            for i, item in enumerate(tasks_list):
                if isinstance(item, str):
                    subtasks.append(SubTask(description=item, task_id=i+1))
                elif isinstance(item, dict):
                    task_id = item.get("id", i+1)
                    desc = item.get("task", item.get("description", "Unknown task"))
                    deps = item.get("depends_on", [])
                    subtasks.append(SubTask(description=desc, task_id=task_id, dependencies=deps))
                else:
                    return "Error: Invalid format in subtasks_json."
            self.state_manager.set_plan(goal, subtasks)
            self._plan_start_time = time.time()  # start timing
            
            # Evaluate plan via coordinator
            eval_warning = "Plan accepted."
            if self.coordinator:
                eval_warning = self.coordinator.evaluate_plan(goal, [t.description for t in subtasks])
                
            self.state_manager.set_agent_state(AgentState.EXECUTING)
            if self.memory:
                self.state_manager.persist_state(self.memory)
            
            summary = self.state_manager.get_state_summary()
            return f"Plan created successfully. Evaluation: {eval_warning}\nYou can now execute the first task. State:\n{summary}"
        except json.JSONDecodeError:
            return "Error: Failed to parse subtasks_json. Please provide a valid JSON array."
        except Exception as e:
            return f"Error creating plan: {e}"

    @llm.function_tool(description="Get the current active plan, goal, and task execution state.")
    async def get_current_plan(self) -> str:
        summary = self.state_manager.get_state_summary()
        return summary

    @llm.function_tool(description="Get the next pending subtask to execute from the active plan.")
    async def get_next_task(self) -> str:
        task = self.state_manager.get_next_task()
        if not task:
            state = self.state_manager.active_plan
            if state and state.status == "completed":
                # Plan completed — save workflow and record stats
                goal = self.state_manager.current_goal or "unknown"
                subtasks = [t.description for t in self.state_manager.active_plan.subtasks]
                exec_ms = int((time.time() - self._plan_start_time) * 1000) if self._plan_start_time else 0

                if self.success_learner:
                    self.success_learner.learn_from_success(goal, self.state_manager.active_plan.subtasks)
                    
                if self.memory and hasattr(self.memory, 'save_workflow'):
                    self.memory.save_workflow(goal, subtasks)
                if self.memory and hasattr(self.memory, 'update_workflow_stats'):
                    self.memory.update_workflow_stats(goal, success=True, exec_time_ms=exec_ms)
                    # Also store as episodic memory
                    self.memory.store_episodic(
                        f"Successfully completed plan: {goal} in {exec_ms}ms",
                        project=self.memory._scorer.detect_project(goal),
                        importance=6,
                    )

                self.state_manager.clear_state()
                self._plan_start_time = 0.0
                self.state_manager.set_agent_state(AgentState.COMPLETED)
                if self.memory:
                    self.state_manager.persist_state(self.memory)
                return "All tasks in the active plan are completed. The plan has been cleared."
            return "No active plan or pending tasks."
            
        return f"Next task to execute: '{task.description}'. Please perform this action using your tools, then call mark_task_completed or mark_task_failed."

    @llm.function_tool(description="Mark the current active subtask as successfully completed.")
    async def mark_task_completed(self, result: str = "Success") -> str:
        with self.state_manager._state_lock:
            idx = self.state_manager.current_task_idx
            plan = self.state_manager.active_plan
            if not plan or idx < 0 or idx >= len(plan.subtasks):
                return "Error: No active task to mark as completed."
                
            # The current task index might have been advanced by get_next_task, 
            # so the active task is actually the one we just fetched.
            # get_next_task sets status to "in_progress". Let's find it.
            active_task = None
            for t in plan.subtasks:
                if t.status == "in_progress":
                    active_task = t
                    break
                    
            if not active_task:
                 return "Error: No task is currently in_progress. Did you call get_next_task?"
                 
        self.state_manager.update_task_status(active_task, "completed", result=result)
        if self.memory:
            self.state_manager.persist_state(self.memory)
        return f"Task '{active_task.description}' marked as completed. Use get_next_task to fetch the next step."

    @llm.function_tool(description="Mark the current active subtask as failed. The agent will need to replan.")
    async def mark_task_failed(self, error_reason: str) -> str:
        with self.state_manager._state_lock:
            plan = self.state_manager.active_plan
            if not plan:
                return "Error: No active plan."
                
            active_task = None
            for t in plan.subtasks:
                if t.status == "in_progress":
                    active_task = t
                    break
                    
            if not active_task:
                 return "Error: No task is currently in_progress."
                 
        self.state_manager.update_task_status(active_task, "failed", error=error_reason)

        # Record failure in workflow_stats
        if self.memory and hasattr(self.memory, 'update_workflow_stats'):
            goal = self.state_manager.current_goal or "unknown"
            exec_ms = int((time.time() - self._plan_start_time) * 1000) if self._plan_start_time else 0
            self.memory.update_workflow_stats(goal, success=False, exec_time_ms=exec_ms, error=error_reason)
            # Store failure as episodic memory
            self.memory.store_episodic(
                f"Plan failed at step '{active_task.description}': {error_reason[:120]}",
                project=self.memory._scorer.detect_project(goal),
                importance=5,
            )

        # Cognitive Coordinator Replanning & Recovery
        replan_directive = ""
        if self.coordinator:
            goal_str = self.state_manager.current_goal or "unknown"
            
            self.state_manager.set_agent_state(AgentState.RECOVERING)
            # First, attempt predefined deterministic recovery
            recovery_directive = self.coordinator.recovery_engine.attempt_recovery(
                failed_task=active_task.description,
                error_reason=error_reason
            )
            
            if recovery_directive:
                replan_directive = f"--- DETERMINISTIC RECOVERY STRATEGY ---\n{recovery_directive}"
            else:
                self.state_manager.set_agent_state(AgentState.REPLANNING)
                # Fallback to LLM cognitive failure analysis
                replan_directive = self.coordinator.analyze_failure_and_replan(
                    goal=goal_str,
                    failed_task=active_task.description,
                    error_reason=error_reason
                )

        if self.memory:
            self.state_manager.persist_state(self.memory)

        return (
            f"Task '{active_task.description}' marked as failed due to: {error_reason}. "
            f"The active plan is now in a failed state.\n\n"
            f"{replan_directive}"
        )

    @llm.function_tool(description="Cancel and clear the current active plan.")
    async def cancel_plan(self) -> str:
        self.state_manager.clear_state()
        self._plan_start_time = 0.0
        if self.memory:
            self.state_manager.persist_state(self.memory)
        return "The active plan has been cancelled and cleared."

    @llm.function_tool(description="Analyze a failed task execution and get alternative strategies or past lessons for replanning.")
    async def analyze_and_replan(self, failed_task: str, error_reason: str) -> str:
        if not self.coordinator:
            return "Cognitive Coordinator is not available."
        goal_str = self.state_manager.current_goal or "unknown"
        return self.coordinator.analyze_failure_and_replan(goal_str, failed_task, error_reason)

    @llm.function_tool(description="Check the success rate and performance stats for a type of goal JARVIS has run before.")
    async def get_workflow_reliability(self, goal_pattern: str) -> str:
        """Returns historical success/fail stats for a specific workflow goal."""
        if not self.memory or not hasattr(self.memory, 'get_workflow_stats'):
            return "Workflow statistics are not available."
        stats = self.memory.get_workflow_stats(goal_pattern)
        if not stats:
            return f"No historical data found for goal: '{goal_pattern}'."
        return (
            f"Workflow stats for '{goal_pattern}':\n"
            f"  - Success rate:      {stats['success_rate']}%\n"
            f"  - Successes:         {stats['success_count']}\n"
            f"  - Failures:          {stats['fail_count']}\n"
            f"  - Avg exec time:     {stats['avg_exec_time_ms']}ms"
        )

    @llm.function_tool(
        description="Ask the Tool Router for the most reliable specific tool for a generic capability. "
                    "Use this when planning if you are unsure which tool to select. "
                    "Capabilities: 'web_search', 'browser_automation', 'file_read', 'ui_click'."
    )
    async def get_optimal_tool(self, capability: str) -> str:
        if not self.tool_router:
            return capability
        return self.tool_router.get_optimal_tool(capability)
