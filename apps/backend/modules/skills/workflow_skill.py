import json
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class WorkflowSkill(BaseSkill):
    """
    Skill for saving and replaying named multi-step user workflows.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Save a multi-step workflow for future use")
    async def save_workflow(self, name: str, steps: str) -> str:
        """Save a new workflow."""
        async def _do_save():
            if not self.memory:
                return "Error: MemoryManager not available."
                
            try:
                # Steps might be a JSON string or plain text
                parsed_steps = []
                try:
                    parsed_steps = json.loads(steps)
                except Exception:
                    # If not JSON, try to split by newline or just save as a single string step
                    parsed_steps = [s.strip() for s in steps.split('\n') if s.strip()]
                    if not parsed_steps:
                        parsed_steps = [steps]

                # MemoryManager has save_workflow(goal, subtasks)
                self.memory.save_workflow(name, parsed_steps)
                return f"Successfully saved workflow: '{name}'"
            except Exception as e:
                return f"Failed to save workflow: {e}"

        return await self.safe_execute(
            _do_save,
            confirmation_category="read",
            confirmation_action=f"save workflow {name}",
            confirmed=True,
            success_msg="Saved workflow successfully",
            error_msg="Failed to save workflow"
        )

    @llm.function_tool(description="List available saved workflows")
    async def list_workflows(self) -> str:
        """List all saved workflows."""
        async def _do_list():
            if not self.memory:
                return "Error: MemoryManager not available."
                
            try:
                # Search workflows with an empty query or catch-all to list them
                workflows = self.memory.search_workflows("", limit=20)
                if not workflows:
                    return "No saved workflows found."
                    
                report = "Saved workflows:\n"
                for wf in workflows:
                    report += f"- {wf.get('goal', 'Unnamed')}\n"
                return report
            except Exception as e:
                return f"Failed to list workflows: {e}"

        return await self.safe_execute(
            _do_list,
            confirmation_category="read",
            confirmation_action="list workflows",
            confirmed=True,
            success_msg="Listed workflows successfully",
            error_msg="Failed to list workflows"
        )

    @llm.function_tool(description="Run a saved workflow by its name")
    async def run_workflow(self, name: str) -> str:
        """Execute a saved workflow."""
        async def _do_run():
            if not self.memory:
                return "Error: MemoryManager not available."
                
            try:
                workflows = self.memory.search_workflows(name, limit=1)
                if not workflows:
                    return f"Workflow '{name}' not found."
                    
                wf = workflows[0]
                subtasks = wf.get("subtasks", [])
                
                # To actually run it, we need to dispatch to the AgentBus or ExecutionEngine.
                # Since skills shouldn't duplicate ExecutionAgent bus logic unless necessary,
                # we'll return the steps to the voice LLM to execute, OR we can use ServiceContainer
                # to get the agent_bus and dispatch it. For now, returning the steps to the LLM
                # to guide the conversation is the most voice-native way.
                
                report = f"Loaded workflow '{wf.get('goal')}'. Steps to execute:\n"
                if isinstance(subtasks, list):
                    for i, step in enumerate(subtasks, 1):
                        report += f"{i}. {step}\n"
                else:
                    report += str(subtasks)
                    
                report += "\n(Please execute these steps sequentially)"
                return report
                
            except Exception as e:
                return f"Failed to run workflow: {e}"

        return await self.safe_execute(
            _do_run,
            confirmation_category="read",
            confirmation_action=f"run workflow {name}",
            confirmed=True,
            success_msg="Loaded workflow successfully",
            error_msg="Failed to load workflow"
        )
