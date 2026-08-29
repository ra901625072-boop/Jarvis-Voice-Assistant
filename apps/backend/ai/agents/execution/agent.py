import logging
import asyncio
from typing import Dict, Any, List, Optional
from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

from modules.execution.world_state import WorldStateManager
from modules.execution.execution_engine import ExecutionEngine
from modules.execution.tool_router import ToolRouter
from modules.task.state_manager import SubTask

logger = logging.getLogger("JARVIS.ExecutionAgent")


class ExecutionPolicy:
    """
    Centralized execution policy defining retry budgets, timeouts,
    and recovery settings for the ExecutionAgent.
    """
    def __init__(
        self,
        max_tool_retries: int = 2,
        max_plan_retries: int = 2,
        max_plan_replans: int = 2,
        dependency_wait_timeout: float = 600.0
    ):
        self.max_tool_retries = max_tool_retries
        self.max_plan_retries = max_plan_retries
        self.max_plan_replans = max_plan_replans
        self.dependency_wait_timeout = dependency_wait_timeout


# Process-wide semaphore ensuring serial execution across FOREGROUND visual tasks
_global_foreground_semaphore = asyncio.Semaphore(1)


class ExecutionAgent(BaseAgent):
    """
    Safely dispatches tool calls and verifies task success.
    Migrates WorldStateManager, ExecutionEngine, and ToolRouter.
    """
    def __init__(self, tools_list, memory_agent, bus, security=None):
        super().__init__(agent_id="execution_agent")
        self.memory_agent = memory_agent
        self.bus = bus
        self.security = security
        
        # Instantiate execution components
        self.world_state = WorldStateManager()
        self.engine = ExecutionEngine(tools_list=tools_list, security=security)
        
        # Memory wrapper for ToolRouter
        memory_mgr = memory_agent.memory if hasattr(memory_agent, "memory") else None
        tool_memory = memory_mgr.lifecycle.tool_memory if memory_mgr and hasattr(memory_mgr, 'lifecycle') else None
        self.tool_router = ToolRouter(tool_memory) if tool_memory else None

        self.bus.register(self.agent_id, self.handle)

    async def _run_tool_with_recovery(
        self,
        task: SubTask,
        semaphores: Dict[str, asyncio.Semaphore] = None,
        policy: ExecutionPolicy = None,
        context_tag: str = "general"
    ) -> Any:
        """Executes a tool call with retries and local recovery."""
        tool_name = task.tool_name
        args = task.args or {}
        
        if self.tool_router and not tool_name:
            # Maybe it just gave a generic capability? Not standard, but handled.
            pass
            
        if self.tool_router and tool_name:
            tool_name = self.tool_router.get_optimal_tool(tool_name, context_tag)

        if not tool_name:
            task.failure_category = "validation_error"
            raise ValueError(f"No executable tool name resolved for task '{task.description}'")

        import random
        from modules.learning import failure_patterns
        
        effective_policy = policy or ExecutionPolicy()
        max_retries = effective_policy.max_tool_retries
        last_error = None
        
        # Ensure we have a semaphore for the tool to serialise access to the same tool
        actual_semaphores = semaphores if semaphores is not None else {}
        if tool_name not in actual_semaphores:
            actual_semaphores[tool_name] = asyncio.Semaphore(1)
            
        # Check execution context visibility
        is_foreground = str(getattr(task, "execution_context", "background")).lower() == "foreground"

        async with actual_semaphores[tool_name]:
            # Acquire foreground semaphore if this task is foreground
            fg_lock = _global_foreground_semaphore if is_foreground else asyncio.Semaphore(999)
            async with fg_lock:
                while task.attempt_count < max_retries:
                    task.attempt_count += 1
                    logger.info(
                        f"ExecutionAgent running tool '{tool_name}' on task {task.id} (attempt {task.attempt_count}/{max_retries}, context={task.execution_context}). "
                        f"parent_ids={task.dependencies}"
                    )
                    try:
                        # Dispatch to execution engine
                        result = await self.engine.dispatch(tool_name, args)
                        
                        # Automatic window focus for FOREGROUND tasks
                        if is_foreground:
                            try:
                                from modules.controls.window_controller import WindowController
                                wc = WindowController()
                                wc.focus_window()
                            except Exception as focus_err:
                                logger.debug(f"Auto window focus attempt note: {focus_err}")
                                
                        # Success
                        return result
                    except PermissionError as e:
                        task.failure_category = "permission_denied"
                        logger.error(
                            f"Permission denied executing tool '{tool_name}' on task {task.id}: {e}. "
                            f"parent_ids={task.dependencies}"
                        )
                        raise
                    except Exception as e:
                        last_error = str(e)
                        logger.warning(
                            f"Task '{task.description}' (task_id={task.id}, tool={tool_name}) failed attempt {task.attempt_count}/{max_retries}: {e}"
                        )
                        
                        # Check for transient patterns to raise max_retries
                        pattern_key = failure_patterns.extract_pattern(last_error)
                        if pattern_key in ("rate_limited", "request_timeout", "connection_error"):
                            task.failure_category = pattern_key
                            if max_retries == effective_policy.max_tool_retries:
                                max_retries = effective_policy.max_tool_retries + 1
                                logger.info(f"Transient error '{pattern_key}' detected. Extending max_retries to {max_retries}.")
                        else:
                            task.failure_category = "runtime_error"
                        
                        if task.attempt_count < max_retries:
                            # Exponential backoff + jitter
                            sleep_time = 0.5 * (2 ** (task.attempt_count - 1)) + random.uniform(0, 0.3)
                            logger.info(f"Sleeping for {sleep_time:.2f}s before retry...")
                            await asyncio.sleep(sleep_time)
                    
            raise RuntimeError(f"Task failed after {max_retries} attempts. Last error: {last_error}")

    async def _execute_task_node(
        self,
        task: SubTask,
        node_events: Dict[int, asyncio.Event],
        all_tasks: Dict[int, SubTask],
        semaphores: Dict[str, asyncio.Semaphore] = None,
        policy: ExecutionPolicy = None,
        context_tag: str = "general",
        parent_task: AgentTask = None
    ):
        """Executes a single node reactively, waiting on parent dependency events."""
        from modules.execution.execution_engine import current_task_type
        current_task_type.set(context_tag)
        
        effective_policy = policy or ExecutionPolicy()
        
        # Wait for all parent tasks to complete
        for dep_id in task.dependencies:
            if dep_id in node_events:
                try:
                    await asyncio.wait_for(node_events[dep_id].wait(), timeout=effective_policy.dependency_wait_timeout)
                except asyncio.TimeoutError:
                    task.status = "failed"
                    task.failure_category = "timeout"
                    task.error = f"Timeout waiting for dependency {dep_id}"
                    logger.error(
                        f"Timeout waiting for dependency {dep_id} for task {task.id}. "
                        f"parent_ids={task.dependencies}"
                    )
                    if task.id in node_events:
                        node_events[task.id].set()
                    return
                    
                parent_task_node = all_tasks.get(dep_id)
                if parent_task_node and parent_task_node.status in ("failed", "skipped", "blocked"):
                    logger.info(
                        f"ExecutionAgent skipping task '{task.description}' (task_id={task.id}) due to failed dependency {dep_id}. "
                        f"parent_ids={task.dependencies}"
                    )
                    task.status = "skipped"
                    task.failure_category = "dependency_failed"
                    if task.id in node_events:
                        node_events[task.id].set()
                    return
            else:
                # Validation should have caught this, but fail-safe
                task.status = "failed"
                task.failure_category = "validation_error"
                task.error = f"Dependency ID {dep_id} does not exist in the plan."
                logger.error(
                    f"Dependency ID {dep_id} not found in node events for task {task.id}. "
                    f"parent_ids={task.dependencies}"
                )
                if task.id in node_events:
                    node_events[task.id].set()
                return
                
        try:
            logger.info(
                f"ExecutionAgent starting task: '{task.description}' (task_id={task.id}). "
                f"parent_ids={task.dependencies}"
            )

            # Substitute parent output placeholders if dependencies exist
            if task.args and isinstance(task.args, dict) and task.dependencies:
                resolved_args = {}
                for k, v in task.args.items():
                    if isinstance(v, str):
                        for dep_id in task.dependencies:
                            parent_node = all_tasks.get(dep_id)
                            if parent_node and parent_node.result is not None:
                                res_str = str(parent_node.result)
                                v = v.replace(f"<output_of_task_{dep_id}>", res_str)
                                v = v.replace(f"{{output_of_task_{dep_id}}}", res_str)
                                v = v.replace(f"$output_of_task_{dep_id}", res_str)
                                v = v.replace("$LAST_TOOL_OUTPUT", res_str)
                        resolved_args[k] = v
                    else:
                        resolved_args[k] = v
                task.args = resolved_args

            if getattr(task, "execution_mode", "deterministic") == "grounded":
                import uuid
                route_task = AgentTask(
                    task_id=str(uuid.uuid4()),
                    task_type="route_subtask",
                    payload={
                        "description": task.description,
                        "args": task.args,
                        "tool_name": task.tool_name
                    },
                    origin_agent=self.agent_id,
                    target_agent="coordinator_agent",
                    dispatch_chain=getattr(parent_task, "dispatch_chain", []) + [self.agent_id]
                )
                route_res = await self.bus.dispatch(route_task)
                if route_res.success:
                    task.status = "completed"
                    task.result = str(route_res.result)
                else:
                    task.failure_category = "runtime_error"
                    raise RuntimeError(route_res.error or "Failed to execute grounded task via routing.")
            elif task.tool_name:
                result = await self._run_tool_with_recovery(task, semaphores, effective_policy, context_tag)
                task.status = "completed"
                task.result = str(result) if result is not None else None
            else:
                optimal_tool = self.tool_router.get_optimal_tool(task.description) if self.tool_router else None
                if optimal_tool and optimal_tool in self.engine.tools:
                    task.tool_name = optimal_tool
                    result = await self._run_tool_with_recovery(task, semaphores, effective_policy, context_tag)
                    task.status = "completed"
                    task.result = str(result) if result is not None else None
                else:
                    import uuid
                    route_task = AgentTask(
                        task_id=str(uuid.uuid4()),
                        task_type="route_subtask",
                        payload={
                            "description": task.description,
                            "args": task.args,
                            "tool_name": task.tool_name
                        },
                        origin_agent=self.agent_id,
                        target_agent="coordinator_agent",
                        dispatch_chain=getattr(parent_task, "dispatch_chain", []) + [self.agent_id]
                    )
                    route_res = await self.bus.dispatch(route_task)
                    if route_res.success:
                        task.status = "completed"
                        task.result = str(route_res.result)
                    else:
                        task.failure_category = "validation_error"
                        raise RuntimeError(f"No executable tool or route found for subtask '{task.description}'")
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            if not task.failure_category:
                task.failure_category = "runtime_error"
            logger.error(
                f"Task '{task.description}' (task_id={task.id}, tool={task.tool_name}) failed permanently: {e}. "
                f"failure_category={task.failure_category}"
            )
            
        # Update StateManager and persist checkpoint to SQLite DB
        try:
            from modules.task.state_manager import AgentStateManager
            from container import ServiceContainer
            state_mgr = AgentStateManager()
            target_subtask = None
            if state_mgr.active_plan:
                for t in state_mgr.active_plan.subtasks:
                    if t.id == task.id:
                        target_subtask = t
                        break
            if target_subtask:
                target_subtask.attempt_count = task.attempt_count
                target_subtask.failure_category = task.failure_category
                state_mgr.update_task_status(target_subtask, task.status, task.result, task.error)
                memory = ServiceContainer.instance().get_or_none("memory")
                if memory:
                    state_mgr.persist_state(memory)
                    logger.debug(f"ExecutionAgent: Checkpointed task {task.id} progress to DB.")
        except Exception as checkpoint_err:
            logger.warning(f"ExecutionAgent: Checkpoint failed for task '{task.description}': {checkpoint_err}")
            
        # Signal completion to unblock dependents
        if task.id in node_events:
            node_events[task.id].set()

    def _validate_plan(self, subtasks: List[SubTask]):
        """
        Validates the DAG:
        1. Confirms every dependency exists in the plan.
        2. Confirms there are no cycles.
        Raises ValueError if validation fails.
        """
        task_ids = {t.id for t in subtasks}
        for task in subtasks:
            for dep_id in task.dependencies:
                if dep_id not in task_ids:
                    logger.error(f"Plan validation failed: Task {task.id} depends on non-existent task {dep_id}")
                    raise ValueError(f"Plan validation failed: Task {task.id} depends on non-existent task {dep_id}")

        visited = {}  # id -> state: 0 = unvisited, 1 = visiting, 2 = visited
        task_map = {t.id: t for t in subtasks}

        def has_cycle(task_id: int) -> bool:
            visited[task_id] = 1
            task = task_map[task_id]
            for dep_id in task.dependencies:
                state = visited.get(dep_id, 0)
                if state == 1:
                    return True
                elif state == 0:
                    if has_cycle(dep_id):
                        return True
            visited[task_id] = 2
            return False

        for task in subtasks:
            if visited.get(task.id, 0) == 0:
                if has_cycle(task.id):
                    logger.error("Plan validation failed: Cyclic dependency detected.")
                    raise ValueError("Plan validation failed: Cyclic dependency detected in plan.")

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "execute_plan":
                plan_json = payload.get("plan", [])
                original_goal = payload.get("goal")
                
                policy = ExecutionPolicy()
                max_retries = policy.max_plan_retries
                max_replans = policy.max_plan_replans
                retry_attempt = 0
                replan_attempt = 0
                
                while True:
                    # Reconstruct SubTask objects
                    subtasks = []
                    from modules.execution.task_visibility_engine import TaskVisibilityEngine
                    for item in plan_json:
                        raw_ctx = item.get("execution_context")
                        if not raw_ctx or str(raw_ctx).lower() == "auto":
                            raw_ctx = TaskVisibilityEngine.classify(
                                item.get("description", ""),
                                item.get("tool_name", ""),
                                item.get("args", {})
                            ).value

                        subtask = SubTask(
                            description=item.get("description", ""),
                            task_id=item.get("id", item.get("task_id", 0)),
                            dependencies=item.get("dependencies", []),
                            tool_name=item.get("tool_name"),
                            args=item.get("args", {}),
                            verify_condition_type=item.get("verify_condition_type"),
                            verify_target=item.get("verify_target"),
                            execution_mode=item.get("execution_mode", "deterministic"),
                            grounding_hint=item.get("grounding_hint"),
                            critical=item.get("critical", True),
                            attempt_count=item.get("attempt_count", 0),
                            failure_category=item.get("failure_category"),
                            execution_context=str(raw_ctx).lower()
                        )
                        subtasks.append(subtask)

                    # Validate plan before execution (DAG check)
                    try:
                        self._validate_plan(subtasks)
                    except ValueError as val_err:
                        logger.error(f"Plan validation failed: {val_err}")
                        return self._create_result(task, success=False, error=str(val_err))
                        
                    # Execute DAG concurrently
                    node_events: Dict[int, asyncio.Event] = {t.id: asyncio.Event() for t in subtasks}
                    all_tasks_dict = {t.id: t for t in subtasks}
                    semaphores: Dict[str, asyncio.Semaphore] = {}
                    
                    execution_tasks = [
                        asyncio.create_task(
                            self._execute_task_node(st, node_events, all_tasks_dict, semaphores, policy, context_tag=st.tool_name or task_type, parent_task=task)
                        )
                        for st in subtasks
                    ]
                    
                    # Wait for all concurrent tasks to finish
                    await asyncio.gather(*execution_tasks)
                    
                    failed_tasks = [t for t in subtasks if t.status == "failed" and getattr(t, "critical", True)]
                    
                    if failed_tasks:
                        import uuid
                        
                        failed_goal_hint = ", ".join([f"{t.tool_name or t.description}" for t in failed_tasks])
                        
                        ctx_task = AgentTask(
                            task_id=str(uuid.uuid4()),
                            task_type="generate_context",
                            payload={"goal": failed_goal_hint},
                            origin_agent="execution_agent",
                            target_agent="coordinator_agent"
                        )
                        ctx_result = await self.bus.dispatch(ctx_task)
                        dynamic_context = ctx_result.result.get("context", "") if (ctx_result and ctx_result.success) else ""
                            
                        recovery_task = AgentTask(
                            task_id=str(uuid.uuid4()),
                            task_type="recover_failure",
                            payload={
                                "failed_task_description": failed_goal_hint,
                                "error_context": "; ".join([t.error for t in failed_tasks if t.error]) + f"\nDynamic context: {dynamic_context}",
                                "goal": original_goal
                            },
                            origin_agent="execution_agent",
                            target_agent="recovery_agent"
                        )
                        recovery_result = await self.bus.dispatch(recovery_task)
                        
                        if recovery_result.success:
                            action = recovery_result.result.get("action")
                            if action == "retry":
                                if retry_attempt < max_retries:
                                    retry_attempt += 1
                                    logger.info(f"ExecutionAgent: choosing retry, attempt {retry_attempt}/{max_retries}")
                                    continue
                                else:
                                    logger.warning("ExecutionAgent: Max execution retries exceeded.")
                            elif action == "replan":
                                if replan_attempt < max_replans:
                                    new_plan = recovery_result.result.get("new_plan")
                                    if new_plan:
                                        plan_json = new_plan
                                        replan_attempt += 1
                                        retry_attempt = 0  # Reset retry budget for new plan
                                        logger.info(f"ExecutionAgent: choosing replan, attempt {replan_attempt}/{max_replans}")
                                        continue
                                else:
                                    logger.warning("ExecutionAgent: Max replans exceeded.")
                        
                        # Escalate or unrecoverable
                        error_msg = f"{len(failed_tasks)} critical tasks failed. Replanning/Recovery failed or exhausted."
                        if retry_attempt >= max_retries:
                            error_msg = "Max execution retries exceeded."
                        elif replan_attempt >= max_replans:
                            error_msg = "Max replanning budget exceeded."

                        report_task = AgentTask(
                            task_id=str(uuid.uuid4()),
                            task_type="record_execution_report",
                            payload={"success": False, "plan_json": plan_json, "failed_tasks": [t.__dict__ for t in failed_tasks], "goal": original_goal},
                            origin_agent="execution_agent",
                            target_agent="memory_agent"
                        )
                        await self.bus.dispatch(report_task)
                        return self._create_result(task, success=False, error=error_msg)
                    else:
                        import uuid
                        report_task = AgentTask(
                            task_id=str(uuid.uuid4()),
                            task_type="record_execution_report",
                            payload={"success": True, "plan_json": plan_json, "goal": original_goal},
                            origin_agent="execution_agent",
                            target_agent="memory_agent"
                        )
                        await self.bus.dispatch(report_task)
                        executed_plan = [
                            {
                                "id": t.id,
                                "description": t.description,
                                "tool_name": t.tool_name,
                                "args": t.args,
                                "status": t.status,
                                "result": t.result,
                                "error": t.error
                            }
                            for t in subtasks
                        ]
                        single_res = subtasks[0].result if len(subtasks) == 1 else None
                        return self._create_result(task, success=True, result={"status": "completed", "plan": executed_plan, "result": single_res})
                    
            elif task_type == "get_world_state":
                state = self.world_state.get_state_snapshot()
                return self._create_result(task, success=True, result={"state": state})
                
            elif task_type in self.engine.tools:
                # Dispatch tool directly (e.g. execute_command, run_script, etc.)
                result = await self.engine.dispatch(task_type, payload)
                res_dict = result if isinstance(result, dict) else {"result": result}
                return self._create_result(task, success=True, result=res_dict)
                
            else:
                return self._create_result(
                    task, 
                    success=False, 
                    error=f"ExecutionAgent does not support task type '{task_type}'"
                )
        except Exception as e:
            logger.exception(f"ExecutionAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))
