import os
import logging
import asyncio
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.controls.system_controller import SystemController
from modules.security.manager import SecurityManager

logger = logging.getLogger("JARVIS.SystemTools")


class SystemTools(JarvisToolset):
    """
    SystemTools handles general computer operations such as power controls,
    clipboard access, settings, and screenshots.

    SYSTEM PROMPT:
    Use SystemTools to control system-level resources. Ensure user confirmation
    is obtained before executing power actions (shutdown, restart, logout).
    If standard file search or filesystem tools fail, use run_terminal_command 
    to execute OS commands like `dir /s /b *filename*` (Windows cmd) or 
    PowerShell commands to find files or gather system information.
    
    SHORT DESCRIPTION:
    Provides system-level control capabilities including power actions, clipboard
    access, screenshots, terminal command execution, and system configuration launchers.

    PROCESS:
    1. Delegates power actions, settings launchers, clipboard controls, and
       screenshots to SystemController.
    2. Provides a fallback terminal command execution capability for advanced queries.

    FLOW:
    Agent -> Tool call -> SystemController / subprocess -> OS Kernel / GUI utilities -> Agent
    """

    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self._system_ctrl = SystemController()

    @property
    def system_ctrl(self) -> SystemController:
        return self._system_ctrl

    @llm.function_tool(description="Shutdown the computer system. Requires user confirmation.")
    async def shutdown_system(self, confirmed: bool = False) -> str:
        return await self.safe_execute(
            self.system_ctrl.shutdown,
            confirmation_category="power",
            confirmation_action="shutdown",
            confirmed=confirmed,
            success_msg="Shutting down the system...",
        )

    @llm.function_tool(description="Restart the computer system. Requires user confirmation.")
    async def restart_system(self, confirmed: bool = False) -> str:
        return await self.safe_execute(
            self.system_ctrl.restart,
            confirmation_category="power",
            confirmation_action="restart",
            confirmed=confirmed,
            success_msg="Restarting the system...",
        )

    @llm.function_tool(description="Put the computer to sleep.")
    async def sleep_system(self) -> str:
        return await self.safe_execute(
            self.system_ctrl.sleep, success_msg="System entering sleep mode."
        )

    @llm.function_tool(description="Lock the computer workstation.")
    async def lock_pc(self) -> str:
        return await self.safe_execute(
            self.system_ctrl.lock_pc, success_msg="Workstation locked."
        )

    @llm.function_tool(description="Log out the current user.")
    async def logout_user(self, confirmed: bool = False) -> str:
        return await self.safe_execute(
            self.system_ctrl.logout,
            confirmation_category="power",
            confirmation_action="logout",
            confirmed=confirmed,
            success_msg="Logging out...",
        )

    @llm.function_tool(description="Copy text to the system clipboard.")
    async def copy_to_clipboard(self, text: str) -> str:
        return await self.safe_execute(
            self.system_ctrl.copy_text, text, success_msg="Text copied to clipboard."
        )

    @llm.function_tool(description="Get the current text from the system clipboard.")
    async def get_from_clipboard(self) -> str:
        content = await self.safe_execute(self.system_ctrl.get_clipboard)
        return (
            f"Clipboard content: {content}"
            if not str(content).startswith("Error:") and content
            else "Clipboard is empty."
        )

    @llm.function_tool(description="Clear the system clipboard.")
    async def clear_clipboard(self) -> str:
        return await self.safe_execute(
            self.system_ctrl.clear_clipboard, success_msg="Clipboard cleared."
        )

    ALLOWED_COMMANDS = frozenset({
        "dir", "echo", "hostname", "whoami", "ver", "systeminfo",
        "tasklist", "python", "pytest", "git", "type", "where"
    })

    @llm.function_tool(description="Execute a safe, allowlisted terminal command. Requires explicit user confirmation.")
    async def run_terminal_command(self, command: str = "", confirmed: bool = False) -> str:
        if not command or not command.strip():
            return "Error: No command provided to run_terminal_command."

        enabled = os.environ.get("JARVIS_ENABLE_TERMINAL", "false").lower() in ("true", "1", "yes")
        if not enabled:
            return "Error: Terminal command execution is disabled by security policy. Set JARVIS_ENABLE_TERMINAL=true to enable."

        import shlex
        try:
            tokens = shlex.split(command, posix=False)
        except Exception:
            tokens = command.strip().split()

        if not tokens:
            return "Error: Empty command."

        base_cmd = tokens[0].lower().rstrip(".exe")
        dangerous_patterns = [";", "&&", "||", "|", "`", "$", "\n", "\r", ">", "<"]
        if any(pat in command for pat in dangerous_patterns):
            return "Error: Command chaining, redirection, and shell substitutions are not permitted."

        if base_cmd not in self.ALLOWED_COMMANDS:
            return f"Error: Command '{base_cmd}' is not in the approved command allowlist ({', '.join(sorted(self.ALLOWED_COMMANDS))})."

        confirm_warning = await self.safe_execute(
            asyncio.sleep, 0,
            confirmation_category="shell",
            confirmation_action=f"execute terminal command '{command}'",
            confirmed=confirmed,
        )
        if isinstance(confirm_warning, str) and "SECURITY WARNING" in confirm_warning:
            return confirm_warning

        cwd = os.environ.get("JARVIS_WORKSPACE_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

        proc = None
        try:
            logger.info(f"AUDIT: Executing allowlisted terminal command: {command} (cwd={cwd})")
            proc = await asyncio.create_subprocess_exec(
                *tokens,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                try:
                    proc.terminate()
                    await proc.wait()
                except Exception:
                    pass
                logger.warning(f"AUDIT: Command timed out: {command}")
                return "Error: Command timed out after 30 seconds."
            
            output = (stdout.decode("utf-8", errors="replace") + "\n" + stderr.decode("utf-8", errors="replace")).strip()
            if len(output) > 2000:
                output = output[:1000] + "\n...[TRUNCATED]...\n" + output[-1000:]
                
            logger.info(f"AUDIT: Command completed with exit code {proc.returncode}: {command}")
            if proc.returncode != 0:
                return f"Command finished with non-zero exit code {proc.returncode}. Output:\n{output}"
                
            if not output:
                return f"Command executed successfully with no output. Exit code: {proc.returncode}"
            return output
            
        except asyncio.CancelledError:
            logger.info("run_terminal_command task cancelled. Terminating subprocess...")
            if proc:
                try:
                    proc.terminate()
                    await proc.wait()
                except Exception:
                    pass
            raise
        except Exception as e:
            logger.error(f"AUDIT: Error executing command '{command}': {e}")
            return f"Error executing command: {e}"

    @llm.function_tool(description="Take a screenshot of the computer screen.")
    async def take_screenshot(self) -> str:
        result = await self.safe_execute(self.system_ctrl.take_screenshot)
        if result is True or (isinstance(result, str) and not result.startswith("Error:")):
            path = os.path.abspath("screenshot.jpg")
            return f"Screenshot saved at {path}"
        return str(result)

    @llm.function_tool(description="Open the Windows system settings app.")
    async def open_settings(self) -> str:
        return await self.safe_execute(
            self.system_ctrl.open_settings, success_msg="Settings opened."
        )
