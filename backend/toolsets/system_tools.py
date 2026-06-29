"""toolsets/system_tools.py — SystemTools toolset."""
import os
from livekit.agents import llm
from toolsets.base import JarvisToolset
from modules.controls.system_controller import SystemController
from modules.core.security_manager import SecurityManager


class SystemTools(JarvisToolset):
    """
    SystemTools handles general computer operations such as power controls,
    clipboard access, settings, and screenshots.

    SYSTEM PROMPT:
    Use SystemTools to control system-level resources. Ensure user confirmation
    is obtained before executing power actions (shutdown, restart, logout).

    SHORT DESCRIPTION:
    Provides system-level control capabilities including power actions, clipboard
    access, screenshots, and system configuration launchers.

    PROCESS:
    1. Delegates power actions, settings launchers, clipboard controls, and
       screenshots to SystemController.
    2. Validates user confirmation flag where necessary.

    FLOW:
    Agent -> Tool call -> SystemController -> OS Kernel / GUI utilities -> Agent
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
