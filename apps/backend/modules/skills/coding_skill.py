import os
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class CodingSkill(BaseSkill):
    """
    Skill for writing and explaining single files via LLM-generated code.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Write or modify code in a single file based on instructions")
    async def write_code(self, file_path: str = None, path: str = None, instruction: str = None, instructions: str = None, code: str = None, code_content: str = None, content: str = None) -> str:
        """Write or modify code in a single file."""
        act_file_path = file_path or path
        if not act_file_path:
            return "Error: Missing file_path or path parameter."
        file_path = act_file_path
        
        provided_code = code or code_content or content
        norm_path = os.path.normpath(os.path.abspath(file_path))
        await self.cancel_active_task(norm_path)
        self.register_active_task(norm_path)
        try:
            if provided_code is not None:
                async def _do_write_provided_code():
                    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
                    self.file_mgr.write_file(file_path, provided_code)
                    return f"Successfully wrote code to {file_path}"
                return await self.safe_execute(
                    _do_write_provided_code,
                    confirmation_category="open",
                    confirmation_action=f"write code to {file_path}",
                    confirmed=True,
                    success_msg="Wrote code successfully",
                    error_msg="Failed to write code"
                )
                
            act_instruction = instruction or instructions
            if not act_instruction:
                return "Error: Missing instruction parameter."
                
            async def _do_write_code():
                existing_code = ""
                if os.path.exists(file_path):
                    existing_code = self.file_mgr.read_file(file_path)

                prompt = (
                    f"You are an expert developer. Implement the following instruction for the file {file_path}.\n"
                    f"Instruction: {act_instruction}\n\n"
                )
                if existing_code and "Error" not in existing_code:
                    prompt += f"Existing Code:\n{existing_code}\n\n"
                
                prompt += "Return ONLY the full code for the file without markdown wrappers or explanations."
                
                new_code = await self.generate_response(prompt=prompt)
                if new_code.startswith("```"):
                    first_nl = new_code.find("\n")
                    if first_nl != -1:
                        new_code = new_code[first_nl:].strip()
                    if new_code.endswith("```"):
                        new_code = new_code[:-3].strip()

                # Ensure directory exists
                os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
                self.file_mgr.write_file(file_path, new_code)
                return f"Successfully wrote code to {file_path}"

            return await self.safe_execute(
                _do_write_code,
                confirmation_category="open",
                confirmation_action=f"write code to {file_path}",
                confirmed=True,
                success_msg="Wrote code successfully",
                error_msg="Failed to write code"
            )
        finally:
            self.unregister_active_task(norm_path)

    @llm.function_tool(description="Explain the code in a specific file")
    async def explain_code(self, file_path: str = None, path: str = None) -> str:
        """Explain the code in a single file."""
        act_file_path = file_path or path
        if not act_file_path:
            return "Error: Missing file_path or path parameter."
        file_path = act_file_path
        async def _do_explain():
            code = self.file_mgr.read_file(file_path)
            if "Error" in code:
                return code

            prompt = (
                f"You are an expert developer. Explain the functionality of the following code in a clear and concise manner.\n\n"
                f"Code from {file_path}:\n{code}"
            )
            explanation = await self.generate_response(prompt=prompt)
            return explanation

        return await self.safe_execute(
            _do_explain,
            confirmation_category="read",
            confirmation_action=f"explain code in {file_path}",
            confirmed=True,
            success_msg="Explained code successfully",
            error_msg="Failed to explain code"
        )
