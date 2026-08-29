"""toolsets/window_tools.py — WindowTools toolset."""
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.controls.window_controller import WindowController
from modules.security.manager import SecurityManager


class WindowTools(JarvisToolset):
    """
    WindowTools provides actions to control window states (minimize, maximize,
    focus, close, restore) on the desktop.

    SYSTEM PROMPT:
    Use WindowTools to manage active desktop layout. Validate target window title
    keywords first. Ask for confirmation before closing active windows.

    SHORT DESCRIPTION:
    Provides control options for desktop app windows (minimize, maximize, restore,
    close, activate) and OS display layout triggers.

    PROCESS:
    1. Lazily instantiates WindowController.
    2. Delegates minimizing, maximizing, restoring, closing, and activating windows.
    3. Triggers desktop view or active window switching.

    FLOW:
    Agent -> Tool call -> WindowController -> pygetwindow / pyautogui
          -> OS Window Manager -> Agent
    """

    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self._window_ctrl = WindowController()

    @property
    def window_ctrl(self) -> WindowController:
        return self._window_ctrl

    @llm.function_tool(
        description="Minimize a window by its title keyword, or the active window if none provided."
    )
    async def minimize_window(self, title_keyword: str = None) -> str:
        return await self.safe_execute(
            self.window_ctrl.minimize_window,
            title_keyword,
            success_msg="Window minimized.",
            error_msg="Failed to find or minimize window.",
        )

    @llm.function_tool(
        description="Maximize a window by its title keyword, or the active window if none provided."
    )
    async def maximize_window(self, title_keyword: str = None) -> str:
        return await self.safe_execute(
            self.window_ctrl.maximize_window,
            title_keyword,
            success_msg="Window maximized.",
            error_msg="Failed to find or maximize window.",
        )

    @llm.function_tool(
        description="Restore a window to its normal size by its title keyword, or the active window if none provided."
    )
    async def restore_window(self, title_keyword: str = None) -> str:
        return await self.safe_execute(
            self.window_ctrl.restore_window,
            title_keyword,
            success_msg="Window restored.",
            error_msg="Failed to find or restore window.",
        )

    @llm.function_tool(
        description="Close a window by its title keyword, or the active window if none provided."
    )
    async def close_window(self, title_keyword: str = None) -> str:
        return await self.safe_execute(
            self.window_ctrl.close_window,
            title_keyword,
            success_msg="Window closed.",
            error_msg="Failed to find or close window.",
        )

    @llm.function_tool(
        description="Bring a window to the foreground and focus it by its title keyword."
    )
    async def focus_window(self, title_keyword: str = None) -> str:
        return await self.safe_execute(
            self.window_ctrl.focus_window,
            title_keyword,
            success_msg="Window focused.",
            error_msg="Failed to find or focus window.",
        )

    @llm.function_tool(description="Switch to the next window (simulates Alt+Tab).")
    async def switch_window(self) -> str:
        return await self.safe_execute(
            self.window_ctrl.switch_window, success_msg="Switched window."
        )

    @llm.function_tool(description="Show the desktop (minimizes all windows).")
    async def show_desktop(self) -> str:
        return await self.safe_execute(
            self.window_ctrl.show_desktop, success_msg="Showing desktop."
        )
