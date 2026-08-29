import asyncio
from typing import List
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class ParallelExecutionSkill(BaseSkill):
    """
    Skill for running multiple independent shell commands or tasks concurrently.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Run multiple shell commands in parallel and aggregate their results")
    async def run_parallel_commands(self, commands: List[str], confirmed: bool = False) -> str:
        """Run N independent shell commands concurrently."""
        async def _do_parallel():
            # Create a task for each command
            tasks = [self.run_shell_command(cmd) for cmd in commands]
            
            # Run them all concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            report = f"Executed {len(commands)} commands in parallel:\n\n"
            for i, (cmd, result) in enumerate(zip(commands, results)):
                report += f"--- Command {i+1}: {cmd} ---\n"
                if isinstance(result, Exception):
                    report += f"Exception: {str(result)}\n"
                else:
                    report += f"Exit Code: {result.get('returncode')}\n"
                    if result.get('stdout'):
                        report += f"Stdout:\n{result.get('stdout')}\n"
                    if result.get('stderr'):
                        report += f"Stderr:\n{result.get('stderr')}\n"
                report += "\n"
                
            return report

        return await self.safe_execute(
            _do_parallel,
            confirmation_category="shell",
            confirmation_action=f"run {len(commands)} parallel commands",
            confirmed=confirmed,
            success_msg="Executed parallel commands successfully",
            error_msg="Failed to execute parallel commands"
        )
