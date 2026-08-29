import os
from typing import Dict, Any, Optional
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class DebuggingSkill(BaseSkill):
    """
    Skill for diagnosing errors from text and stack traces.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Diagnose an error or stack trace to find the root cause and suggest a fix")
    async def diagnose_error(self, error_context: str, component_name: str = "") -> str:
        """
        Diagnose an error from text/stack traces.
        """
        async def _do_diagnose():
            prompt = (
                f"You are an expert debugger. Diagnose the following error context "
                f"{'in component ' + component_name if component_name else ''} and provide "
                f"a concise root cause analysis and a suggested fix.\n\n"
                f"Error Context:\n{error_context}"
            )
            response = await self.generate_response(prompt=prompt)
            return response

        return await self.safe_execute(
            _do_diagnose,
            confirmation_category="read",
            confirmation_action=f"diagnose error in {component_name}" if component_name else "diagnose error",
            confirmed=True, # Read operations are safe, confirmed implicitly if not tier confirm
            success_msg="Diagnosed error successfully",
            error_msg="Failed to diagnose error"
        )
