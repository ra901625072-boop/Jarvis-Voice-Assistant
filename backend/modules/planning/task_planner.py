import logging
import json
import time
from typing import Optional, List, Dict, Any
from livekit.agents import llm
from modules.core.state_manager import AgentStateManager, SubTask, AgentState
from modules.core.memory_manager import MemoryManager
from modules.execution.tool_router import ToolRouter
from modules.execution.success_patterns import SuccessLearner

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
        if not self.coordinator:
            return "Cognitive Coordinator is not available."
        return self.coordinator.generate_execution_context(goal)

    def match_static_intent(self, goal: str) -> Optional[List[SubTask]]:
        import re
        goal_lower = goal.strip().lower()
        
        # 1. System volume controls
        if goal_lower in ("mute", "mute audio", "mute system", "mute volume"):
            return [SubTask(
                description="Mute system audio",
                task_id=1,
                tool_name="mute_audio",
                args={}
            )]
        if goal_lower in ("unmute", "unmute audio", "unmute system", "unmute volume"):
            return [SubTask(
                description="Unmute system audio",
                task_id=1,
                tool_name="unmute_audio",
                args={}
            )]
        vol_match = re.match(r'^(?:set|change)?\s*(?:system\s+)?volume\s+(?:to\s+)?(\d+)%?$', goal_lower)
        if vol_match:
            try:
                level = int(vol_match.group(1))
                if 0 <= level <= 100:
                    return [SubTask(
                        description=f"Set system volume to {level}%",
                        task_id=1,
                        tool_name="set_volume",
                        args={"level": level}
                    )]
            except ValueError:
                pass
                
        # 2. Display brightness
        bright_match = re.match(r'^(?:set|change)?\s*(?:display\s+)?brightness\s+(?:to\s+)?(\d+)%?$', goal_lower)
        if bright_match:
            try:
                level = int(bright_match.group(1))
                if 0 <= level <= 100:
                    return [SubTask(
                        description=f"Set display brightness to {level}%",
                        task_id=1,
                        tool_name="set_brightness",
                        args={"level": level}
                    )]
            except ValueError:
                pass

        # 3. Take screenshot
        if goal_lower in ("take screenshot", "screenshot", "capture screen"):
            return [SubTask(
                description="Take system screenshot",
                task_id=1,
                tool_name="take_screenshot",
                args={}
            )]

        # 4. Open Settings
        if goal_lower in ("open settings", "launch settings", "settings"):
            return [SubTask(
                description="Open system settings",
                task_id=1,
                tool_name="open_settings",
                args={}
            )]

        # 5. Open Web URLs
        url_match = re.match(r'^(?:open|visit|go\s+to)\s+(https?://[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)$', goal_lower)
        if url_match:
            url_str = url_match.group(1).strip()
            # Canonicalize url
            if url_str in ("google", "google.com"):
                url = "https://www.google.com"
            elif url_str in ("youtube", "youtube.com"):
                url = "https://www.youtube.com"
            elif url_str in ("github", "github.com"):
                url = "https://github.com"
            elif url_str in ("wikipedia", "wikipedia.org"):
                url = "https://www.wikipedia.org"
            else:
                url = url_str if url_str.startswith(("http://", "https://")) else f"https://{url_str}"
            return [SubTask(
                description=f"Open URL: {url}",
                task_id=1,
                tool_name="open_url",
                args={"url": url},
                verify_condition_type="url_reachable",
                verify_target=url
            )]

        # Simple name-only URLs (e.g. "open google", "open youtube")
        for name, url in [("google", "https://www.google.com"), 
                          ("youtube", "https://www.youtube.com"), 
                          ("github", "https://github.com"), 
                          ("wikipedia", "https://www.wikipedia.org")]:
            if goal_lower == f"open {name}":
                return [SubTask(
                    description=f"Open URL: {url}",
                    task_id=1,
                    tool_name="open_url",
                    args={"url": url},
                    verify_condition_type="url_reachable",
                    verify_target=url
                )]

        # 6. YouTube video playback
        yt_match = re.match(r'^(?:play|watch)\s+(.+)\s+on\s+youtube$', goal_lower)
        if not yt_match:
            yt_match = re.match(r'^(?:play|watch)\s+youtube\s+for\s+(.+)$', goal_lower)
        if not yt_match:
            yt_match = re.match(r'^youtube\s+(?:play|watch)\s+(.+)$', goal_lower)
        if yt_match:
            query = yt_match.group(1).strip()
            return [SubTask(
                description=f"Play YouTube video for: {query}",
                task_id=1,
                tool_name="play_youtube",
                args={"query": query}
            )]

        # 7. Search Google
        search_match = re.match(r'^(?:search\s+google\s+for|search\s+for|google)\s+(.+)$', goal_lower)
        if search_match:
            query = search_match.group(1).strip()
            return [SubTask(
                description=f"Search Google for: {query}",
                task_id=1,
                tool_name="search_google",
                args={"query": query}
            )]

        # 8. Open Application
        app_match = re.match(r'^(?:open|launch|start|run)\s+([a-zA-Z0-9\s_-]+)$', goal_lower)
        if app_match:
            app_name = app_match.group(1).strip()
            # Alias resolution
            if app_name in ("google chrome", "chrome browser"):
                app_name = "chrome"
            elif app_name in ("command prompt", "cmd prompt"):
                app_name = "cmd"
            elif app_name in ("ms edge", "microsoft edge"):
                app_name = "edge"
                
            return [SubTask(
                description=f"Open {app_name}",
                task_id=1,
                tool_name="open_application",
                args={"app_name": app_name},
                verify_condition_type="process_running",
                verify_target=app_name
            )]
            
        return None

    @llm.function_tool(description="Create a step-by-step plan for a goal. For common commands (e.g. open chrome, open notepad, set volume to X, increase volume, decrease volume, set brightness to X, open youtube, etc.), you can omit subtasks_json and pass only the goal.")
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
                    return "Error: subtasks_json is required for custom goals that do not match a static template."
                tasks_list = json.loads(subtasks_json)
                if not isinstance(tasks_list, list):
                    return "Error: subtasks_json must be a JSON array."
                    
                for i, item in enumerate(tasks_list):
                    if isinstance(item, str):
                        subtasks.append(SubTask(description=item, task_id=i+1))
                    elif isinstance(item, dict):
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
                    else:
                        return "Error: Invalid format in subtasks_json."
                
                # Compile dependencies dynamically using DAGCompiler
                from modules.planning.dag_compiler import DAGCompiler
                subtasks = DAGCompiler.compile_dependencies(subtasks)

                # Evaluate plan via coordinator
                eval_warning = "Plan accepted."
                if self.coordinator:
                    eval_warning = self.coordinator.evaluate_plan(goal, [t.description for t in subtasks])
                    
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
