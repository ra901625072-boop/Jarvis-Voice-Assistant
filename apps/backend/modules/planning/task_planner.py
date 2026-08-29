import logging
import json
import time
from typing import Optional, List
from livekit.agents import llm
from modules.task.state_manager import AgentStateManager, SubTask, AgentState
from modules.memory.manager import MemoryManager
from modules.execution.tool_router import ToolRouter
from modules.execution.success_patterns import SuccessLearner
from ai.agents.types import AgentTask

logger = logging.getLogger("JARVIS.TaskPlanner")

class TaskPlannerTools(llm.Toolset):
    """
    TaskPlannerTools provides agent actions for managing, scheduling, evaluating, and recovering multi-step plans.

    SYSTEM PROMPT:
    Always utilize TaskPlannerTools to structure multi-step goals, track task progress, and dynamically recover when a task fails. Retrieve execution context before building plans.

    SHORT DESCRIPTION:
    Manages structured task plans, plan verification, next-task lookups, and replanning logic.

    PROCESS:
    1. Loads execution context (lessons learned, success patterns, tool reliability) from the coordinator.
    2. Builds dependency-aware task graphs and validates them using CognitiveCoordinator.
    3. Handles status updates (completed, failed), starts background timers, and triggers deterministic or LLM-based replanning on failures.

    FLOW:
    Agent -> get_execution_context()/create_plan() -> CognitiveCoordinator -> AgentStateManager -> Agent
    """
    def __init__(self, memory: MemoryManager = None):
        super().__init__(id=self.__class__.__name__.lower())
        self.state_manager = AgentStateManager()
        self.memory = memory
        self.coordinator = None
        self.tool_router = ToolRouter(memory.lifecycle.tool_memory) if memory and hasattr(memory, 'lifecycle') else None
        self.success_learner = SuccessLearner(memory) if memory else None
        self._plan_start_time: float = 0.0  # track execution time

    @llm.function_tool(description="Prepare for planning by retrieving past workflows, known tool risks, and lessons learned for a specific goal. ALWAYS call this before create_plan.")
    async def get_execution_context(self, goal: str) -> str:
        self.state_manager.set_agent_state(AgentState.PLANNING)
        from container import ServiceContainer
        bus = ServiceContainer.instance().get_or_none("agent_bus")
        if not bus:
            return "Cognitive Coordinator is not available."
        import uuid
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="generate_context",
            payload={"goal": goal},
            origin_agent="planning_agent",
            target_agent="coordinator_agent"
        )
        res = await bus.dispatch(task)
        if res.success:
            return res.result.get("context", "")
        else:
            return f"Error generating context: {res.error}"

    def match_static_intent(self, goal: str) -> Optional[List[SubTask]]:
        """Matches static single-step deterministic intents using TaskClassifier."""
        from modules.routing.task_classifier import TaskClassifier
        report = TaskClassifier.classify(goal)
        if report.fast_subtasks:
            subtasks = []
            for st in report.fast_subtasks:
                subtasks.append(SubTask(
                    description=st.get("description", goal),
                    task_id=st.get("id", 1),
                    tool_name=st.get("tool_name"),
                    args=st.get("args", {}),
                    dependencies=st.get("dependencies", []),
                    verify_condition_type=st.get("verify_condition_type"),
                    verify_target=st.get("verify_target"),
                ))
            return subtasks
        return None

    @llm.function_tool(
        description=(
            "Create a step-by-step plan for a goal. For common commands (e.g., set volume, open notepad), "
            "you can omit subtasks_json. For complex multi-step goals, subtasks_json is REQUIRED and "
            "MUST be a JSON array of objects representing steps. Each step object MUST contain: "
            "'id' (int), 'task' (string description), 'tool_name' (string name of the exact tool to run, "
            "e.g., 'open_url', 'automate_desktop_flow', 'search_google'), and 'args' (dict of arguments for that tool, "
            "e.g., {'url': 'https://example.com'} or {'goal': 'analyze page text'}). "
            "Specify dependencies using 'depends_on' (list of dependent step IDs)."
        )
    )
    async def create_plan(self, goal: str, subtasks_json: Optional[str] = None) -> str:
        """
        subtasks_json should be a JSON array of objects with dependencies.
        Example: [{"id": 1, "task": "Open Chrome", "tool_name": "open_url", "args": {"url": "https://google.com"}}, {"id": 2, "task": "Search", "depends_on": [1]}]
        For backwards compatibility, an array of strings is also supported.
        """
        try:
            subtasks = []
            
            # Check static intent plan router first
            static_subtasks = self.match_static_intent(goal)
            if static_subtasks:
                logger.info(f"Fast Intent Plan Router matched goal: '{goal}'")
                subtasks = static_subtasks
                eval_warning = "Static template matched (safe plan)."
            else:
                if not subtasks_json:
                    subtasks = [SubTask(description=goal, task_id=1)]
                    eval_warning = "Dynamic plan fallback (single-step goal)."
                else:
                    tasks_list = json.loads(subtasks_json)
                    if not isinstance(tasks_list, list):
                        return "Error: subtasks_json must be a JSON array."
                    
                for i, item in enumerate(tasks_list):
                    if isinstance(item, str):
                        desc = item
                        if not desc or desc.strip().lower() in ("unknown task", "", "none", "null"):
                            return f"Error: Invalid subtask description '{desc}' in plan step {i+1}."
                        subtasks.append(SubTask(description=desc, task_id=i+1))
                    elif isinstance(item, dict):
                        task_id = item.get("id", i+1)
                        desc = item.get("task", item.get("description")) or ""
                        if not desc or desc.strip().lower() in ("unknown task", "", "none", "null"):
                            return f"Error: Invalid subtask description '{desc}' in plan step {i+1}."
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
                    else:
                        return "Error: Invalid format in subtasks_json."
                
                # Compile dependencies dynamically using DAGCompiler
                from modules.planning.dag_compiler import DAGCompiler
                subtasks = DAGCompiler.compile_dependencies(subtasks)

                # Evaluate plan via coordinator
                eval_warning = "Plan accepted."
                from container import ServiceContainer
                bus = ServiceContainer.instance().get_or_none("agent_bus")
                if bus:
                    import uuid
                    eval_task = AgentTask(
                        task_id=str(uuid.uuid4()),
                        task_type="evaluate_plan",
                        payload={
                            "goal": goal,
                            "plan_descriptions": [t.description for t in subtasks]
                        },
                        origin_agent="planning_agent",
                        target_agent="coordinator_agent"
                    )
                    eval_res = await bus.dispatch(eval_task)
                    if eval_res.success:
                        eval_warning = eval_res.result.get("evaluation", "Plan accepted.")
                    
            self.state_manager.set_plan(goal, subtasks)
            self._plan_start_time = time.time()  # start timing
            
            self.state_manager.set_agent_state(AgentState.EXECUTING)
            if self.memory:
                self.state_manager.persist_state(self.memory)
            
            # Start background execution using parallel DAGScheduler
            scheduler_started = False
            try:
                import asyncio
                from container import ServiceContainer
                container = ServiceContainer.instance()
                tools_list = container.get_or_none("tools") if container else None
                if tools_list:
                    from modules.execution.execution_engine import ExecutionEngine
                    from modules.planning.task_scheduler import DAGScheduler
                    
                    engine = ExecutionEngine(tools_list)
                    scheduler = DAGScheduler(engine, self.memory)
                    # Stash the live scheduler instance on the container so other
                    # components can look it up later if needed (write-only today).
                    container._services["scheduler"] = scheduler
                    
                    async def run_scheduler_bg():
                        try:
                            # Short delay to allow current LLM tool call response to finalize and stream
                            await asyncio.sleep(0.5)
                            await scheduler.execute_plan()
                        except Exception as ex:
                            logger.error(f"Error executing plan in background: {ex}")
                            
                    asyncio.create_task(run_scheduler_bg())
                    scheduler_started = True
                    logger.info("DAG Scheduler launched in background task successfully.")
            except Exception as se:
                logger.warning(f"Could not initialize background DAG Scheduler: {se}. Bypassing background execution.")
 
            summary = self.state_manager.get_state_summary()
            start_status = "Background execution started." if scheduler_started else "Ready to execute."
            return f"Plan created successfully. Evaluation: {eval_warning}\nStatus: {start_status}\nState:\n{summary}"
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
        active_task = None
        with self.state_manager._state_lock:
            idx = self.state_manager.current_task_idx
            plan = self.state_manager.active_plan
            if not plan or idx < 0 or idx >= len(plan.subtasks):
                return "Error: No active task to mark as completed."

            # Find the in-progress task while lock is held
            for t in plan.subtasks:
                if t.status == "in_progress":
                    active_task = t
                    break

            if not active_task:
                return "Error: No task is currently in_progress. Did you call get_next_task?"

            # Update status atomically while lock is still held
            active_task.status = "completed"
            active_task.result = result

        if self.memory:
            self.state_manager.persist_state(self.memory)
        return f"Task '{active_task.description}' marked as completed. Use get_next_task to fetch the next step."

    @llm.function_tool(description="Mark the current active subtask as failed. The agent will need to replan.")
    async def mark_task_failed(self, error_reason: str) -> str:
        active_task = None
        with self.state_manager._state_lock:
            plan = self.state_manager.active_plan
            if not plan:
                return "Error: No active plan."

            # Find the in-progress task while lock is held
            for t in plan.subtasks:
                if t.status == "in_progress":
                    active_task = t
                    break

            if not active_task:
                return "Error: No task is currently in_progress."

            # Update status atomically while lock is still held
            active_task.status = "failed"
            active_task.error = error_reason

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
        from container import ServiceContainer
        bus = ServiceContainer.instance().get_or_none("agent_bus")
        if bus:
            goal_str = self.state_manager.current_goal or "unknown"
            self.state_manager.set_agent_state(AgentState.RECOVERING)
            
            import uuid
            recovery_task = AgentTask(
                task_id=str(uuid.uuid4()),
                task_type="recover_failure",
                payload={
                    "goal": goal_str,
                    "failed_task_description": active_task.description,
                    "error_context": error_reason,
                    "agent_id": "planning_agent",
                    "task_type": "planning"
                },
                origin_agent="planning_agent",
                target_agent="recovery_agent"
            )
            recovery_res = await bus.dispatch(recovery_task)
            if recovery_res.success:
                action = recovery_res.result.get("action", "escalate")
                reason = recovery_res.result.get("reason", "")
                replan_directive = f"Recovery Decision: {action.upper()}\nReason: {reason}"

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
        from container import ServiceContainer
        bus = ServiceContainer.instance().get_or_none("agent_bus")
        if not bus:
            return "Cognitive Coordinator is not available."
        goal_str = self.state_manager.current_goal or "unknown"
        import uuid
        task = AgentTask(
            task_id=str(uuid.uuid4()),
            task_type="recover_failure",
            payload={
                "goal": goal_str,
                "failed_task_description": failed_task,
                "error_context": error_reason,
                "agent_id": "planning_agent",
                "task_type": "planning"
            },
            origin_agent="planning_agent",
            target_agent="recovery_agent"
        )
        res = await bus.dispatch(task)
        if res.success:
            action = res.result.get("action", "escalate")
            reason = res.result.get("reason", "")
            return f"Recovery Decision: {action.upper()}\nReason: {reason}"
        else:
            return f"Error analyzing failure: {res.error}"

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
