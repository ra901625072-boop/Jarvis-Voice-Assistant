"""
modules/skills/web_development_skill.py — Skill for autonomous full-stack web development.
"""
import os
import json
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill
from ai.agents.planning.web_pipeline import compile_web_development_pipeline, extract_project_metadata

class WebDevelopmentSkill(BaseSkill):
    """
    Skill for scaffolding and managing professional end-to-end web applications.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Scaffold a complete full-stack web application following the 15-stage pipeline")
    async def build_fullstack_app(self, project_name: str, description: str, tech_stack: str = "fastapi-react", target_dir: str = "") -> str:
        """Scaffold and build a complete full-stack web project."""
        if not target_dir:
            target_dir = f"d:/Jarvis/scratch/{project_name.lower().replace(' ', '_')}"
            
        async def _do_build():
            goal = f"create {project_name} website with {description} in {target_dir}"
            subtasks = compile_web_development_pipeline(goal)
            
            # Execute subtasks sequentially or via execution engine
            results = []
            for st in subtasks:
                if st.tool_name == "write_code":
                    file_p = st.args.get("file_path")
                    code_c = st.args.get("code")
                    if file_p and code_c:
                        os.makedirs(os.path.dirname(file_p), exist_ok=True)
                        self.file_mgr.write_file(file_p, code_c)
                        results.append(f"Created {file_p}")
                elif st.tool_name == "execute_command":
                    cmd = st.args.get("command")
                    if cmd:
                        res = await self.run_shell_command(cmd)
                        results.append(f"Command '{cmd}': exit code {res.get('returncode')}")
                        
            return f"Successfully generated {project_name} in {target_dir}.\nCompleted {len(results)} steps.\nFiles ready at: {target_dir}"

        return await self.safe_execute(
            _do_build,
            confirmation_category="shell",
            confirmation_action=f"build web project in {target_dir}",
            confirmed=True,
            success_msg="Web project built successfully",
            error_msg="Failed to build web project"
        )

    @llm.function_tool(description="Generate a Product Requirements Document (PRD) for a web project")
    async def generate_prd(self, project_name: str, description: str, target_dir: str = "") -> str:
        """Generate PRD for a website."""
        if not target_dir:
            target_dir = f"d:/Jarvis/scratch/{project_name.lower().replace(' ', '_')}"
        os.makedirs(f"{target_dir}/docs", exist_ok=True)
        prd_path = f"{target_dir}/docs/PRD.md"
        
        prompt = f"Generate a comprehensive PRD for project '{project_name}'. Description: {description}. Include Executive Summary, Target Personas, Core Features, API endpoints, Non-functional requirements."
        content = await self.generate_response(prompt=prompt)
        self.file_mgr.write_file(prd_path, content)
        return f"PRD successfully generated at {prd_path}"

    @llm.function_tool(description="Generate UI/UX Design System specifications and color tokens for a web project")
    async def generate_design_system(self, project_name: str, style: str = "modern clean", target_dir: str = "") -> str:
        """Generate Design System specification."""
        if not target_dir:
            target_dir = f"d:/Jarvis/scratch/{project_name.lower().replace(' ', '_')}"
        os.makedirs(f"{target_dir}/docs", exist_ok=True)
        ds_path = f"{target_dir}/docs/DESIGN_SYSTEM.md"
        
        prompt = f"Generate a UI/UX Design System for '{project_name}' in style '{style}'. Include WCAG 2.1 compliant color tokens, typography scale, component layouts, and states."
        content = await self.generate_response(prompt=prompt)
        self.file_mgr.write_file(ds_path, content)
        return f"Design System successfully generated at {ds_path}"

    @llm.function_tool(description="Audit and run tests on an existing web project")
    async def audit_web_project(self, target_dir: str) -> str:
        """Run health check and tests on a project."""
        test_file = f"{target_dir}/tests/test_api.py"
        if not os.path.exists(test_file):
            return f"No test suite found at {test_file}"
        res = await self.run_shell_command(f"python -m pytest {test_file}")
        return f"Test audit results for {target_dir}:\nReturn Code: {res.get('returncode')}\nOutput:\n{res.get('stdout')}"
