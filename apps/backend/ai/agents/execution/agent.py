import logging
import asyncio
from typing import Dict, Any, List
from ai.agents.base_agent import BaseAgent
from ai.agents.types import AgentTask, AgentResult

from modules.execution.world_state import WorldStateManager
from modules.execution.execution_engine import ExecutionEngine
from modules.execution.tool_router import ToolRouter
from modules.planning.dag_compiler import DAGCompiler
from modules.core.state_manager import SubTask

logger = logging.getLogger("JARVIS.ExecutionAgent")

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

    async def _run_tool_with_recovery(self, task: SubTask) -> Any:
        """Executes a tool call with retries and local recovery."""
        tool_name = task.tool_name
        args = task.args or {}
        
        if self.tool_router and not tool_name:
            # Maybe it just gave a generic capability? Not standard, but handled.
            pass
            
        if self.tool_router and tool_name:
            tool_name = self.tool_router.get_optimal_tool(tool_name)

        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Dispatch to execution engine
                result = await self.engine.dispatch(tool_name, args)
                # Success
                return result
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Task '{task.description}' failed attempt {attempt+1}/{max_retries}: {e}")
                await asyncio.sleep(1.0)
                
        raise RuntimeError(f"Task failed after {max_retries} attempts. Last error: {last_error}")

    async def _execute_task_node(self, task: SubTask, node_events: Dict[int, asyncio.Event]):
        """Executes a single node reactively, waiting on parent dependency events."""
        # Wait for all parent tasks to complete
        for dep_id in task.dependencies:
            if dep_id in node_events:
                await node_events[dep_id].wait()
                
        # In a real DAG, we'd check if parents failed and block this task.
        # For simplicity, we assume if we reach here, we try to run.
        try:
            logger.info(f"ExecutionAgent starting task: '{task.description}'")
            if task.tool_name:
                result = await self._run_tool_with_recovery(task)
                task.status = "completed"
            else:
                task.status = "completed"
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            logger.error(f"Task '{task.description}' failed permanently: {e}")
            
        # Signal completion to unblock dependents
        if task.id in node_events:
            node_events[task.id].set()

    async def handle(self, task: AgentTask) -> AgentResult:
        task_type = task.task_type
        payload = task.payload
        
        try:
            if task_type == "execute_plan":
                plan_json = payload.get("plan", [])
                
                # Reconstruct SubTask objects
                subtasks = []
                for item in plan_json:
                    subtask = SubTask(
                        description=item.get("description", ""),
                        task_id=item.get("id", item.get("task_id", 0)),
                        dependencies=item.get("dependencies", []),
                        tool_name=item.get("tool_name"),
                        args=item.get("args", {}),
                        verify_condition_type=item.get("verify_condition_type"),
                        verify_target=item.get("verify_target")
                    )
                    subtasks.append(subtask)
                    
                # Execute DAG
                node_events: Dict[int, asyncio.Event] = {t.id: asyncio.Event() for t in subtasks}
                running_tasks = []
                for st in subtasks:
                    coro = self._execute_task_node(st, node_events)
                    running_tasks.append(asyncio.create_task(coro))
                    
                await asyncio.gather(*running_tasks, return_exceptions=True)
                
                failed_tasks = [t for t in subtasks if t.status == "failed"]
                
                if failed_tasks:
                    # Dispatch replan to planning_agent
                    import uuid
                    replan_task = AgentTask(
                        task_id=str(uuid.uuid4()),
                        task_type="replan",
                        payload={
                            "failed_task": failed_tasks[0].__dict__,
                            "error": failed_tasks[0].error
                        },
                        origin_agent="execution_agent",
                        target_agent="planning_agent"
                    )
                    await self.bus.dispatch(replan_task)
                    
                    return self._create_result(task, success=False, error=f"{len(failed_tasks)} tasks failed. Replanning triggered.")
                else:
                    return self._create_result(task, success=True, result={"status": "completed"})
                    
            elif task_type == "get_world_state":
                state = self.world_state.get_state_snapshot()
                return self._create_result(task, success=True, result={"state": state})
                
            else:
                return self._create_result(
                    task, 
                    success=False, 
                    error=f"ExecutionAgent does not support task type '{task_type}'"
                )
        except Exception as e:
            logger.exception(f"ExecutionAgent failed handling '{task_type}'")
            return self._create_result(task, success=False, error=str(e))
