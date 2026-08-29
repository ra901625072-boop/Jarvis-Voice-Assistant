import os
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class SelfHealingSkill(BaseSkill):
    """
    Skill for suggesting and optionally applying recovery actions for failed local tasks.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Suggest a recovery action for a failed local task")
    async def suggest_recovery(self, failed_task: str, error_message: str) -> str:
        """Suggest recovery actions based on a failure."""
        async def _do_suggest():
            prompt = (
                f"You are an expert self-healing agent. The following task failed:\n"
                f"Task: {failed_task}\n"
                f"Error Message: {error_message}\n\n"
                f"Suggest a concrete, actionable recovery step. If the fix requires a shell command, "
                f"provide the exact shell command to run. Otherwise, explain what needs to be changed."
            )
            suggestion = await self.generate_response(prompt=prompt)
            return suggestion

        return await self.safe_execute(
            _do_suggest,
            confirmation_category="read",
            confirmation_action=f"suggest recovery for {failed_task}",
            confirmed=True,
            success_msg="Generated recovery suggestion",
            error_msg="Failed to generate recovery suggestion"
        )

    def _is_command_safe(self, command: str) -> tuple[bool, str]:
        """
        Verify that a command is safe to run by checking against allow-lists and deny-lists.
        """
        import re
        import os
        
        # Split command by common operators to inspect individual commands
        subcommands = re.split(r'(&&|\|\||;|\||\n)', command)
        
        allowed_base = {"git", "pip", "npm", "pytest", "python", "poetry", "cargo", "go", "echo", "make", "task", "docker", "docker-compose"}
        denied_base = {"rm", "del", "rd", "rmdir", "format", "mkfs", "dd", "shutdown", "reboot", "kill", "curl", "wget", "powershell", "cmd", "bash", "sh"}
        
        for sub in subcommands:
            sub = sub.strip()
            if not sub or sub in {"&&", "||", ";", "|", "\n"}:
                continue
            
            # Tokenize and extract the executable
            tokens = [t.strip('"\'') for t in sub.split()]
            if not tokens:
                continue
                
            exe_path = tokens[0]
            exe_name = os.path.basename(exe_path).lower()
            exe_name_no_ext, _ = os.path.splitext(exe_name)
            
            # Check deny-list
            if exe_name_no_ext in denied_base or exe_name in denied_base:
                return False, f"Command executable '{exe_name}' is in the deny-list."
                
            # Check allow-list
            if exe_name_no_ext not in allowed_base and exe_name not in allowed_base:
                return False, f"Command executable '{exe_name}' is not in the allow-list."
                
            # Check for dangerous arguments/patterns
            sub_lower = sub.lower()
            if "rm -rf" in sub_lower or "rd /s" in sub_lower or "rmdir /s" in sub_lower or "del /s" in sub_lower:
                return False, "Command contains dangerous deletion flags (e.g. -rf, /s)."
                
        return True, ""

    @llm.function_tool(description="Apply a recovery action (e.g., run a shell command)")
    async def apply_recovery(self, action: str, confirm_command: str = "") -> str:
        """Apply a recovery action after validation."""
        # Perform command safety check first
        is_safe, warning = self._is_command_safe(action)
        
        # Dry-run / confirmation mode
        if confirm_command != action:
            safety_status = "✅ PASS (Allowed Command)" if is_safe else f"❌ BLOCKED ({warning})"
            preview_card = (
                f"--- RECOVERY COMMAND DRY-RUN PREVIEW ---\n"
                f"Proposed Command: {action}\n"
                f"Safety Status:    {safety_status}\n\n"
                f"To run this recovery command, please call apply_recovery again passing the exact command as the confirmation argument:\n"
                f"apply_recovery(action=\"{action}\", confirm_command=\"{action}\")"
            )
            return preview_card
            
        if not is_safe:
            return f"Error: Command execution blocked by safety policy. Reason: {warning}"

        async def _do_apply():
            result = await self.run_shell_command(action)
            
            # Log action to episodic memory
            if self.memory and hasattr(self.memory, "store_memory"):
                try:
                    from modules.task.state_manager import AgentStateManager
                    state_mgr = AgentStateManager()
                    current_goal = state_mgr.current_goal or "general"
                    project = "general"
                    if hasattr(self.memory, "_scorer") and hasattr(self.memory._scorer, "detect_project"):
                        project = self.memory._scorer.detect_project(current_goal)
                    
                    self.memory.store_memory(
                        content=f"Executed self-healing recovery command: {action}",
                        memory_type="episodic",
                        project=project,
                        importance=8
                    )
                except Exception as mem_err:
                    self.logger.warning(f"Failed to record recovery to memory: {mem_err}")

            if result.get("returncode") == 0:
                return f"Recovery action applied successfully. Output:\n{result.get('stdout')}"
            else:
                return f"Recovery action failed. Error:\n{result.get('stderr')}"

        return await self.safe_execute(
            _do_apply,
            confirmation_category="shell",
            confirmation_action=f"run recovery command: {action}",
            confirmed=True,
            success_msg="Applied recovery action",
            error_msg="Failed to apply recovery action"
        )
