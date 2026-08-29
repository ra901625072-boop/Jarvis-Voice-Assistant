from livekit.agents import llm
from modules.skills.base_skill import BaseSkill
from container import ServiceContainer
from ai.agents.types import AgentTask
import uuid

class GoalExecutionSkill(BaseSkill):
    """
    Skill for dispatching a natural-language goal to the agent bus.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Execute a complex multi-step goal autonomously by dispatching it to the cognitive agent swarm (coordinator -> planning -> execution).")
    async def execute_goal(self, goal_description: str = "", goal: str = "", confirmed: bool = True) -> str:
        """Dispatch a goal to the agent bus."""
        actual_goal = goal_description or goal
        if not actual_goal:
            return "Error: goal_description or goal is empty."

        async def _do_execute():
            bus = self._get_agent_bus()
            if not bus:
                return "Error: AgentBus not found in ServiceContainer."
            
            task_id = str(uuid.uuid4())
            task = AgentTask(
                task_id=task_id,
                task_type="execute_goal",
                payload={"goal": actual_goal},
                origin_agent="voice_skill",
                target_agent="coordinator_agent"
            )
            
            try:
                result = await bus.dispatch(task, timeout=300.0)
            except Exception as e:
                self.logger.warning(f"Goal execution error or timeout: {e}")
                result = None
            
            if result:
                status = "Success" if result.success else "Failed"
                res_text = result.result or result.error or "No result returned."
                return f"Goal execution completed with status '{status}':\n{res_text}"
            else:
                # Dispatch timed out or returned no response — auto-save state
                if self.memory:
                    try:
                        from modules.task.state_manager import AgentStateManager
                        state_mgr = AgentStateManager()
                        state_mgr.persist_state(self.memory)
                        self.logger.info("GoalExecutionSkill: Persisted state on goal execution timeout.")
                    except Exception as save_err:
                        self.logger.warning(f"Failed to auto-save state on timeout: {save_err}")
                return "Goal execution timed out or returned no response. Current state has been auto-saved."

        return await self.safe_execute(
            _do_execute,
            confirmation_category="read",
            confirmation_action=f"execute complex goal: {actual_goal}",
            confirmed=True,
            success_msg="Dispatched goal successfully",
            error_msg="Failed to dispatch goal"
        )
