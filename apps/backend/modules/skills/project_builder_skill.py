import os
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class ProjectBuilderSkill(BaseSkill):
    """
    Skill for scaffolding a new multi-file project.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Scaffold a new multi-file project based on a description")
    async def build_project(self, description: str, target_dir: str, confirmed: bool = False) -> str:
        """Scaffold a new project in the target directory."""
        norm_dir = os.path.normpath(os.path.abspath(target_dir))
        await self.cancel_active_task(norm_dir)
        self.register_active_task(norm_dir)
        try:
            async def _do_build():
                # Generate the structure and initialization commands
                prompt = (
                    f"You are an expert developer. I need to scaffold a new project in '{target_dir}'.\n"
                    f"Project Description: {description}\n\n"
                    f"Please provide:\n"
                    f"1. A JSON object mapping file paths (relative to the target directory) to their initial code content.\n"
                    f"2. A list of shell initialization commands to run in the target directory (e.g. npm init, git init). "
                    f"Return the response ONLY as a valid JSON object with keys 'files' and 'commands'.\n"
                    f"Example:\n"
                    f"{{\n"
                    f"  \"files\": {{\n"
                    f"    \"src/index.js\": \"console.log('hello');\",\n"
                    f"    \"README.md\": \"# Project\"\n"
                    f"  }},\n"
                    f"  \"commands\": [\n"
                    f"    \"npm init -y\"\n"
                    f"  ]\n"
                    f"}}"
                )
                
                response_text = await self.generate_response(prompt=prompt, response_mime_type="application/json")
                try:
                    project_data = self.clean_and_parse_json(response_text)
                except Exception as e:
                    return f"Error parsing project structure: {e}\nResponse was:\n{response_text}"

                files = project_data.get("files", {})
                commands = project_data.get("commands", [])

                # Create files
                os.makedirs(target_dir, exist_ok=True)
                for rel_path, content in files.items():
                    abs_path = os.path.normpath(os.path.join(target_dir, rel_path))
                    # Prevent path traversal
                    if not abs_path.startswith(os.path.abspath(target_dir)):
                        self.logger.warning(f"Skipping file path outside target dir: {rel_path}")
                        continue
                        
                    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                    self.file_mgr.write_file(abs_path, content)

                # Run commands
                command_outputs = []
                for cmd in commands:
                    result = await self.run_shell_command(cmd, cwd=target_dir)
                    command_outputs.append(
                        f"Command: {cmd}\nExit Code: {result.get('returncode')}\nOutput: {result.get('stdout')}\nError: {result.get('stderr')}"
                    )

                report = f"Successfully scaffolded project in {target_dir}.\nCreated {len(files)} files.\n"
                if command_outputs:
                    report += "Initialization commands executed:\n" + "\n---\n".join(command_outputs)
                    
                return report

            is_safe = self.security.is_safe_path(target_dir) if self.security else True
            auto_confirm_effective = confirmed or is_safe or (os.environ.get("JARVIS_AUTO_CONFIRM", "true").lower() in ("true", "1", "yes"))

            return await self.safe_execute(
                _do_build,
                confirmation_category="shell", # Project builder uses shell commands and writes multiple files
                confirmation_action=f"scaffold project in {target_dir}",
                confirmed=auto_confirm_effective,
                success_msg="Project scaffolded successfully",
                error_msg="Failed to scaffold project"
            )
        finally:
            self.unregister_active_task(norm_dir)
