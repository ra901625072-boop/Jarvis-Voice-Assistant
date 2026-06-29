"""toolsets/app_tools.py — AppTools toolset."""
from livekit.agents import llm
from toolsets.base import JarvisToolset
from modules.controls.app_controller import AppController
from modules.core.security_manager import SecurityManager


class AppTools(JarvisToolset):
    """
    AppTools manages open and close actions for local desktop applications.

    SYSTEM PROMPT:
    Use AppTools to manage application lifecycles. Ensure fuzzy matching /
    alias lookup is utilized to match process names accurately.

    SHORT DESCRIPTION:
    Exposes functions to launch and terminate local host OS applications by
    name or path.

    PROCESS:
    1. Lazily instantiates AppController.
    2. Calls open_app() or close_app() with target query string.

    FLOW:
    Agent -> Tool call -> AppController -> subprocess / psutil -> Agent
    """

    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self._app_ctrl = AppController()

    @property
    def app_ctrl(self) -> AppController:
        return self._app_ctrl

    @llm.function_tool(
        description="Open an application by its name (e.g., notepad, calculator, chrome)"
    )
    async def open_application(self, app_name: str) -> str:
        return await self.safe_execute(
            self.app_ctrl.open_app,
            app_name,
            success_msg=f"Successfully opened {app_name}.",
            error_msg=f"Failed to open {app_name}.",
        )

    @llm.function_tool(
        description="Close a running application by its name. Requires user confirmation."
    )
    async def close_application(self, app_name: str, confirmed: bool = False) -> str:
        return await self.safe_execute(
            self.app_ctrl.close_app,
            app_name,
            confirmation_category="close_app",
            confirmation_action=f"close application '{app_name}'",
            confirmed=confirmed,
            success_msg=f"Attempted to close {app_name}.",
        )
