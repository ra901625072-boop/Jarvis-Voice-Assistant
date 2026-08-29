import os
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class DocumentationSkill(BaseSkill):
    """
    Skill for generating README, docstrings, and API documentation from code.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Generate a README.md file for the specified project directory")
    async def generate_readme(self, project_dir: str) -> str:
        """Generate a README.md for the project directory."""
        readme_path = os.path.join(project_dir, "README.md")
        norm_path = os.path.normpath(os.path.abspath(readme_path))
        await self.cancel_active_task(norm_path)
        self.register_active_task(norm_path)
        try:
            async def _do_generate_readme():
                # Gather files to understand project
                files_info = self.folder_mgr.list_directory(project_dir, recursive=True)
                if "Error" in files_info:
                    return files_info

                prompt = (
                    f"You are an expert technical writer. Generate a comprehensive README.md "
                    f"for the project located at {project_dir} based on the following file structure:\n\n"
                    f"{files_info}\n\n"
                    f"Provide only the markdown content for the README.md."
                )
                readme_content = await self.generate_response(prompt=prompt)
                
                self.file_mgr.write_file(readme_path, readme_content)
                return f"Successfully generated README.md at {readme_path}"

            return await self.safe_execute(
                _do_generate_readme,
                confirmation_category="read", # The category for the action, mostly reading project structure, but creates README.
                confirmation_action=f"generate README for {project_dir}",
                confirmed=True,
                success_msg="Generated README",
                error_msg="Failed to generate README"
            )
        finally:
            self.unregister_active_task(norm_path)

    @llm.function_tool(description="Generate and insert docstrings for a specified Python file")
    async def generate_docstrings(self, file_path: str = None, path: str = None) -> str:
        """Generate docstrings for the specified file."""
        act_file_path = file_path or path
        if not act_file_path:
            return "Error: Missing file_path or path parameter."
        file_path = act_file_path
        norm_path = os.path.normpath(os.path.abspath(file_path))
        await self.cancel_active_task(norm_path)
        self.register_active_task(norm_path)
        try:
            async def _do_generate_docstrings():
                code = self.file_mgr.read_file(file_path)
                if "Error" in code:
                    return code

                prompt = (
                    f"You are an expert Python developer. Add comprehensive docstrings (using Google style) "
                    f"to the following code. Return ONLY the modified code, no markdown wrappers, no explanations.\n\n"
                    f"Code:\n{code}"
                )
                documented_code = await self.generate_response(prompt=prompt)
                if documented_code.startswith("```"):
                    documented_code = documented_code.strip("`").replace("python\n", "", 1)
                    
                self.file_mgr.write_file(file_path, documented_code.strip())
                return f"Successfully generated docstrings for {file_path}"

            return await self.safe_execute(
                _do_generate_docstrings,
                confirmation_category="read",
                confirmation_action=f"generate docstrings for {file_path}",
                confirmed=True,
                success_msg="Generated docstrings",
                error_msg="Failed to generate docstrings"
            )
        finally:
            self.unregister_active_task(norm_path)
