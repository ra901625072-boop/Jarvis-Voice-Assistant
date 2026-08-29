import os
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class RefactoringSkill(BaseSkill):
    """
    Skill for refactoring existing code toward a stated goal.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Refactor an existing file to meet a specific goal")
    async def refactor_file(self, file_path: str = None, path: str = None, goal: str = None) -> str:
        """Refactor a file based on the goal."""
        act_file_path = file_path or path
        if not act_file_path:
            return "Error: Missing file_path or path parameter."
        if not goal:
            return "Error: Missing goal parameter."
        file_path = act_file_path
        norm_path = os.path.normpath(os.path.abspath(file_path))
        await self.cancel_active_task(norm_path)
        self.register_active_task(norm_path)
        try:
            async def _do_refactor():
                code = self.file_mgr.read_file(file_path)
                if "Error" in code:
                    return code

                prompt = (
                    f"You are an expert developer. Refactor the following code to achieve this goal: {goal}\n\n"
                    f"Return ONLY the refactored code without markdown wrappers or explanations.\n\n"
                    f"Code:\n{code}"
                )
                refactored_code = await self.generate_response(prompt=prompt)
                if refactored_code.startswith("```"):
                    first_nl = refactored_code.find("\n")
                    if first_nl != -1:
                        refactored_code = refactored_code[first_nl:].strip()
                    if refactored_code.endswith("```"):
                        refactored_code = refactored_code[:-3].strip()

                self.file_mgr.write_file(file_path, refactored_code)
                return f"Successfully refactored {file_path} to achieve: {goal}"

            return await self.safe_execute(
                _do_refactor,
                confirmation_category="open", # Since it reads/edits a single file, open/read is safe.
                confirmation_action=f"refactor {file_path}",
                confirmed=True,
                success_msg="Refactored file successfully",
                error_msg="Failed to refactor file"
            )
        finally:
            self.unregister_active_task(norm_path)
