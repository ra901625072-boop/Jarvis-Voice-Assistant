from modules.planning.task_graph import TaskGraph, TaskNode, TaskStatus
from modules.planning.risk_gate import RiskGate, PlanningBudget
from modules.planning.replanner import Replanner, ReplanStrategy

logger = logging.getLogger("JARVIS.DAGScheduler")

class DAGScheduler:
    """
    DAGScheduler executes a compiled dependency graph of SubTasks concurrently and reactively.
    Utilizes event-driven asyncio.Event completion signaling, resource semaphores,
    cancellation token tracking, programmatic verification engines, RiskGate policies, and Replanner.
    """
    def __init__(self, execution_engine: ExecutionEngine, memory_manager = None, risk_gate: Optional[RiskGate] = None, replanner: Optional[Replanner] = None):
        self.engine = execution_engine
        self.state_manager = AgentStateManager()
        self.memory_manager = memory_manager
        self.risk_gate = risk_gate or RiskGate()
        self.replanner = replanner or Replanner(memory_manager=memory_manager)
        self._running_tasks: List[asyncio.Task] = []
        
        # Concurrency & Resource Control Semaphores
        self.browser_semaphore = asyncio.Semaphore(1)      # Max 1 concurrent browser CDP session
        self.heavy_task_semaphore = asyncio.Semaphore(2)   # Max 2 concurrent heavy OS/File actions

        # Tool locks for dangerous parallel actions (mouse, keyboard, window)
        self.tool_locks = {
            "mouse": asyncio.Lock(),
            "keyboard": asyncio.Lock(),
            "window": asyncio.Lock()
        }

    def _get_required_locks(self, tool_name: Optional[str]) -> List[asyncio.Lock]:
        """Maps tools to required exclusive locks (dangerous parallel tools)."""
        if not tool_name:
            return []
        name_lower = tool_name.lower()
        locks = []
        if any(keyword in name_lower for keyword in ["mouse", "click", "scroll"]):
            locks.append(self.tool_locks["mouse"])
        if any(keyword in name_lower for keyword in ["keyboard", "type", "press_key", "hold_key", "release_key"]):
            locks.append(self.tool_locks["keyboard"])
        if any(keyword in name_lower for keyword in ["window", "desktop", "focus", "show_desktop"]):
            locks.append(self.tool_locks["window"])
        return locks

    def _get_resource_semaphore(self, tool_name: Optional[str]) -> Optional[asyncio.Semaphore]:
        """Maps specific tool calls to concurrency resource semaphores."""
        if not tool_name:
            return None
        name_lower = tool_name.lower()
        if any(keyword in name_lower for keyword in ["browser", "url", "google", "youtube", "playwright", "click_dom", "fill_form"]):
            return self.browser_semaphore
        if any(keyword in name_lower for keyword in ["application", "command", "copy", "move", "rename"]):
            return self.heavy_task_semaphore
        return None

    async def execute_plan(self) -> bool:
        """
        Executes the current active plan topologically and concurrently in an event-driven flow.
        """
        plan = self.state_manager.active_plan
        if not plan or plan.status != "active":
            logger.warning("No active plan to execute.")
            return False

        self.state_manager.set_agent_state(AgentState.EXECUTING)
        subtasks = plan.subtasks

        try:
            # Validate plan layout and check for circular dependencies
            DAGCompiler.validate_and_sort(subtasks)
        except ValueError as e:
            logger.error(f"Dependency validation failed: {e}")
            self.state_manager.set_agent_state(AgentState.FAILED)
            return False

        logger.info(f"Starting event-driven execution of plan: '{plan.goal}' with {len(subtasks)} subtasks.")
        
        # Create completion events for each node
        node_events: Dict[int, asyncio.Event] = {task.id: asyncio.Event() for task in subtasks}
        
        # Build tasks list to run concurrently
        self._running_tasks = []
        for task in subtasks:
            coro = self._execute_task_node(task, node_events)
            self._running_tasks.append(asyncio.create_task(coro))

        # Wait for all task wrappers to complete
        await asyncio.gather(*self._running_tasks, return_exceptions=True)
        self._running_tasks.clear()

        # Check if the execution succeeded or was cancelled/failed
        plan_failed = False
        with self.state_manager._state_lock:
            if self.state_manager.cancel_token.is_cancelled:
                plan.status = "failed"
                plan_failed = True
                logger.warning("DAG Execution was cancelled by User.")
            else:
                failed_any = any(t.status in ("failed", "blocked") for t in subtasks)
                if failed_any:
                    plan.status = "failed"
                    plan_failed = True
                else:
                    plan.status = "completed"

        # Final state transition and Memory logging
        if self.memory_manager:
            try:
                goal = plan.goal or "unknown"
                success = not plan_failed
                
                # Record to SQLite stats
                if hasattr(self.memory_manager, 'update_workflow_stats'):
                    self.memory_manager.update_workflow_stats(goal, success=success, exec_time_ms=0)
                
                # Store episodic memory
                outcome_str = "completed successfully" if success else ("cancelled" if self.state_manager.cancel_token.is_cancelled else "failed")
                project_name = "general"
                if hasattr(self.memory_manager, '_scorer') and hasattr(self.memory_manager._scorer, 'detect_project'):
                    project_name = self.memory_manager._scorer.detect_project(goal)
                self.memory_manager.store_episodic(
                    f"Autonomous DAG plan execution {outcome_str} for goal: '{goal}'",
                    project=project_name,
                    importance=6 if success else 5
                )
            except Exception as mex:
                logger.error(f"Failed to record execution stats to memory: {mex}")

        if plan_failed:
            self.state_manager.set_agent_state(AgentState.FAILED)
            return False
        else:
            self.state_manager.set_agent_state(AgentState.COMPLETED)
            return True

    async def _execute_task_node(self, task: SubTask, node_events: Dict[int, asyncio.Event]):
        """
        Executes a single node reactively, waiting on parent dependency events.
        """

        # 1. Wait for all parent tasks to complete
        for dep_id in task.dependencies:
            if dep_id in node_events:
                await node_events[dep_id].wait()

        # 2. Check if cancellation requested
        if self.state_manager.cancel_token.is_cancelled:
            task.status = "failed"
            task.error = "Cancelled"
            node_events[task.id].set()
            return

        # 3. Check if any parent failed. If so, mark this node as blocked and exit
        plan = self.state_manager.active_plan
        task_status_map = {t.id: t.status for t in plan.subtasks} if plan else {}
        
        has_blocked_parents = any(task_status_map.get(dep_id) in ("failed", "blocked") for dep_id in task.dependencies)
        if has_blocked_parents:
            logger.warning(f"Blocking subtask '{task.description}' due to parent task failures.")
            task.status = "blocked"
            task.error = "Blocked by dependency failure"
            node_events[task.id].set()
            return

        # 4. Ready to run - set in_progress
        logger.info(f"Subtask '{task.description}' dependencies satisfied. Queueing execution.")
        task.status = "in_progress"
        self.state_manager.persist_state(self.memory_manager)

        # 4b. Pre-flight Risk & Budget Authorization
        if self.risk_gate:
            task_node = TaskNode.from_legacy_subtask(task)
            authorized, auth_err = await self.risk_gate.check_and_authorize(task_node)
            if not authorized:
                logger.error(f"Subtask '{task.description}' blocked by RiskGate: {auth_err}")
                self.state_manager.update_task_status(task, "failed", error=auth_err)
                node_events[task.id].set()
                return

        # 5. Acquire resource limits
        sem = self._get_resource_semaphore(task.tool_name)
        locks = self._get_required_locks(task.tool_name)
        error_msg = None
        result = None

        async def run_with_locks(lock_list, idx=0):
            if idx >= len(lock_list):
                return await self._run_tool_with_recovery(task)
            async with lock_list[idx]:
                return await run_with_locks(lock_list, idx + 1)

        try:
            if sem:
                async with sem:
                    result = await run_with_locks(locks)
            else:
                result = await run_with_locks(locks)
            
            # 6. Deep Verification Check
            if task.verify_condition_type and task.verify_target:
                self.state_manager.set_agent_state(AgentState.VERIFYING)
                verified = await self._verify_task_outcome(task.verify_condition_type, task.verify_target)
                self.state_manager.set_agent_state(AgentState.EXECUTING)
                
                if not verified:
                    raise RuntimeError(f"Verification FAILED: condition {task.verify_condition_type} -> '{task.verify_target}' returned FALSE.")
                logger.info(f"Verification SUCCESS: condition {task.verify_condition_type} -> '{task.verify_target}' is TRUE.")

            # Mark task completed
            self.state_manager.update_task_status(task, "completed", result=str(result))

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error executing subtask '{task.description}': {e}")
            self.state_manager.update_task_status(task, "failed", error=error_msg)

        # 6. Unblock dependents and notify Waiters:
        if self.memory_manager:
            self.state_manager.persist_state(self.memory_manager)
        # Wake up downstream nodes
        node_events[task.id].set()

    async def _run_tool_with_recovery(self, task: SubTask) -> Any:
        """Helper to run tool, and execute self-healing retries if it fails."""
        if self.state_manager.cancel_token.is_cancelled:
            raise asyncio.CancelledError("Task cancelled.")
            
        try:
            if not task.tool_name:
                return "Success (No tool specified)"
            
            # --- Fallback argument extraction if args are missing/empty ---
            if task.args is None:
                task.args = {}
            
            if task.tool_name == "open_url" and "url" not in task.args:
                import re
                match = re.search(r'https?://[^\s]+', task.description)
                if match:
                    task.args["url"] = match.group(0)
                else:
                    match = re.search(r'[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?', task.description)
                    if match:
                        task.args["url"] = "https://" + match.group(0)
            
            elif task.tool_name == "automate_desktop_flow" and "goal" not in task.args:
                task.args["goal"] = task.description
                
            elif task.tool_name in ("search_google", "search_google_live", "google_search", "duckduckgo_search", "web_search", "research_topic") and "query" not in task.args:
                task.args["query"] = task.description
                
            elif task.tool_name in ("open_application", "close_application") and "app_name" not in task.args:
                task.args["app_name"] = task.description
                
            # --- Resolve placeholders from dependency results ---
            plan = self.state_manager.active_plan
            if plan and task.args:
                import re
                
                def replace_placeholder(match):
                    step_type = match.group(1)
                    step_id = int(match.group(2))
                    for pt in plan.subtasks:
                        if pt.id == step_id:
                            if pt.status == "completed" and pt.result is not None:
                                return pt.result
                            return f"[Step {step_id} is {pt.status}]"
                    return match.group(0)
                
                pattern = re.compile(r'\b([A-Za-z_]+)_(?:FROM|OF)_STEP_(\d+)\b', re.IGNORECASE)
                
                def resolve_val(val):
                    if isinstance(val, str):
                        return pattern.sub(replace_placeholder, val)
                    elif isinstance(val, dict):
                        return {k: resolve_val(v) for k, v in val.items()}
                    elif isinstance(val, list):
                        return [resolve_val(item) for item in val]
                    return val
                
                task.args = resolve_val(task.args)

            result = await self.engine.dispatch(task.tool_name, task.args)
            if self.risk_gate:
                self.risk_gate.budget.record_tool_call()
            logger.debug("TASK SCHEDULER DEBUG - Result: %r Type: %s Starts with: %s", result, type(result), result.startswith("Verification FAILED:") if isinstance(result, str) else False)
            if isinstance(result, str) and (result.startswith("Error:") or result.startswith("SECURITY WARNING:") or result.startswith("Verification FAILED:")):
                raise RuntimeError(result)
            return result
        except Exception as e:
            error_msg = str(e)
            
            # Trigger self-healing recovery checks
            try:
                from modules.execution.recovery_engine import RecoveryEngine
                from modules.execution.world_state import WorldStateManager
                
                ws = WorldStateManager()
                recovery = RecoveryEngine(ws)
                directive = recovery.attempt_recovery(task.description or "", error_msg)
                
                if directive:
                    logger.info(f"Self-Healing: Triggered recovery: '{directive}'")
                    recovery_success = False
                    
                    if "scroll" in directive.lower():
                        logger.info("Executing recovery action: mouse scroll down.")
                        await self.engine.dispatch("scroll_mouse", {"amount": -3})
                        await asyncio.sleep(1.0)
                        recovery_success = True
                    elif "keyboard" in directive.lower() or "shortcut" in directive.lower() or "enter" in directive.lower():
                        logger.info("Executing recovery action: keyboard enter.")
                        await self.engine.dispatch("press_key", {"keys": "enter"})
                        await asyncio.sleep(1.0)
                        recovery_success = True
                        
                    if recovery_success:
                        # Check cancellation again
                        if self.state_manager.cancel_token.is_cancelled:
                            raise asyncio.CancelledError("Task cancelled.")
                        logger.info(f"Retrying subtask after recovery: '{task.description}'")
                        result = await self.engine.dispatch(task.tool_name, task.args)
                        if isinstance(result, str) and (result.startswith("Error:") or result.startswith("SECURITY WARNING:")):
                            raise RuntimeError(result)
                        return result
            except Exception as rex:
                logger.error(f"Self-healing retry failed: {rex}")
                error_msg = f"{error_msg} (Recovery failed: {rex})"
                
            raise RuntimeError(error_msg)

    async def _verify_task_outcome(self, condition_type: str, target: str) -> bool:
        """Queries the VerificationEngine to verify task outcome."""
        try:
            from modules.execution.verification_engine import VerificationEngine
            from modules.execution.world_state import WorldStateManager
            
            ws = WorldStateManager()
            ve = VerificationEngine(ws)
            # Run blocking check in thread pool
            result = await asyncio.to_thread(ve.verify, condition_type, target)
            return result
        except Exception as e:
            logger.error(f"Verification exception: {e}")
            return False

    def cancel_execution(self):
        """Cancels the active plan cancellation token and aborts running asyncio Tasks."""
        logger.warning("Cancelling active plan execution loop...")
        self.state_manager.cancel_active_execution()
        for t in self._running_tasks:
            if not t.done():
                t.cancel()
        self._running_tasks.clear()
        self.state_manager.set_agent_state(AgentState.IDLE)
