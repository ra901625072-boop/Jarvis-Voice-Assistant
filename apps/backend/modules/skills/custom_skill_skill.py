from livekit.agents import llm
from modules.skills.base_skill import BaseSkill
import os
import json
import logging
from ai.agents.types import AgentTask
import uuid
from container import ServiceContainer

logger = logging.getLogger("JARVIS.Skills.CustomSkill")

class CustomSkillSkill(BaseSkill):
    """
    Skill for running custom instruction-based markdown skills.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Execute a custom instructional markdown skill by name when triggered by user")
    async def run_custom_skill(self, name: str, user_request: str = "", confirmed: bool = False) -> str:
        """
        Run a custom markdown skill by name, optionally passing additional details of the user's request.
        """
        async def _do_execute():
            bus = self._get_agent_bus()
            if not bus:
                return "Error: AgentBus not found in ServiceContainer."
                
            # Find backend directory dynamically
            curr_dir = os.path.abspath(os.path.dirname(__file__))
            while curr_dir and os.path.basename(curr_dir) != "backend":
                parent = os.path.dirname(curr_dir)
                if parent == curr_dir:
                    break
                curr_dir = parent
                
            skills_file = os.path.join(curr_dir, "database", "skills.json")
            if not os.path.exists(skills_file):
                return f"Error: Skills database not found. Custom skill '{name}' does not exist."
                
            try:
                with open(skills_file, "r", encoding="utf-8") as f:
                    skills = json.load(f)
            except Exception as e:
                return f"Error: Failed to load skills database: {e}"
                
            # Find skill by name (case-insensitive)
            target_skill = None
            for s_id, s_data in skills.items():
                if s_data.get("name", "").strip().lower() == name.strip().lower():
                    target_skill = s_data
                    break
                    
            if not target_skill:
                return f"Error: Custom skill '{name}' not found."
                
            if not target_skill.get("enabled", True):
                return f"Error: Custom skill '{name}' is currently disabled."
                
            # Load custom skill markdown file
            md_file = target_skill.get("file")
            if not md_file or not os.path.exists(md_file):
                # Try relative path check
                db_dir = os.path.dirname(skills_file)
                base_name = os.path.basename(md_file) if md_file else f"{target_skill.get('id')}.md"
                md_file = os.path.join(db_dir, "custom_skills", base_name)
                if not os.path.exists(md_file):
                    return f"Error: Custom skill instruction file not found for '{name}'."
                
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    md_content = f.read()
            except Exception as e:
                return f"Error: Failed to read custom skill instruction file: {e}"
                
            # Remove frontmatter for LLM to focus on instructions
            from modules.skills.markdown_loader import parse_markdown
            parsed = parse_markdown(md_content)
            instructions = parsed.get("body", "")
            
            # Combine instruction with user request
            goal_desc = f"Execute Custom Skill: {name}\n\nINSTRUCTIONS:\n{instructions}\n\nUSER REQUEST / INPUT DETAILS:\n{user_request or 'Perform this skill based on instructions.'}"
            
            task_id = str(uuid.uuid4())
            task = AgentTask(
                task_id=task_id,
                task_type="execute_goal",
                payload={"goal": goal_desc},
                origin_agent="voice_skill",
                target_agent="coordinator_agent"
            )
            
            try:
                result = await bus.dispatch(task, timeout=120.0)
            except Exception as e:
                logger.warning(f"Custom skill execution error or timeout: {e}")
                result = None
                
            if result:
                status = "Success" if result.success else "Failed"
                res_text = result.result or result.error or "No result returned."
                return f"Custom skill '{name}' execution completed with status '{status}':\n{res_text}"
            else:
                if self.memory:
                    try:
                        from modules.task.state_manager import AgentStateManager
                        state_mgr = AgentStateManager()
                        state_mgr.persist_state(self.memory)
                        logger.info("CustomSkillSkill: Persisted state on execution timeout.")
                    except Exception as save_err:
                        logger.warning(f"Failed to auto-save state on timeout: {save_err}")
                return f"Custom skill '{name}' execution timed out or returned no response. Current state has been auto-saved."

        return await self.safe_execute(
            _do_execute,
            confirmation_category="shell",
            confirmation_action=f"run custom skill: {name}",
            confirmed=confirmed,
            success_msg=f"Dispatched custom skill '{name}' successfully",
            error_msg=f"Failed to dispatch custom skill '{name}'"
        )
