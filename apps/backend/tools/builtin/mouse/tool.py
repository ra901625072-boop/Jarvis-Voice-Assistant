"""toolsets/mouse_tools.py — MouseTools toolset."""
from livekit.agents import llm
from toolsets.base import JarvisToolset
from modules.controls.mouse_controller import MouseController
from modules.core.security_manager import SecurityManager


class MouseTools(JarvisToolset):
    """
    MouseTools allows programmatic mouse movement, scroll, clicks, and state
    management.

    SYSTEM PROMPT:
    Use MouseTools to coordinate clicks, scrolling actions, and drags. Ensure
    coordinate boundary verification passes.

    SHORT DESCRIPTION:
    Enables simulated mouse operations including moves, clicks, scrolling, drags,
    and screen position queries.

    PROCESS:
    1. Invokes MouseController methods to set or query coordinates, issue mouse
       button clicks, double clicks, right clicks, drags, or scroll amounts.

    FLOW:
    Agent -> Tool call -> MouseController -> OS GUI Subsystem -> Agent
    """

    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self._mouse_ctrl = MouseController()

    @property
    def mouse_ctrl(self) -> MouseController:
        return self._mouse_ctrl

    @llm.function_tool(
        description="Left click the mouse at its current location, or optionally at specified x,y coordinates"
    )
    async def click_mouse(self, x: int = None, y: int = None) -> str:
        return await self.safe_execute(
            self.mouse_ctrl.click, x, y, success_msg="Mouse left-clicked."
        )

    @llm.function_tool(
        description="Double left click the mouse at its current location, or optionally at specified x,y coordinates"
    )
    async def double_click_mouse(self, x: int = None, y: int = None) -> str:
        return await self.safe_execute(
            self.mouse_ctrl.double_click, x, y, success_msg="Mouse double-clicked."
        )

    @llm.function_tool(
        description="Right click the mouse at its current location, or optionally at specified x,y coordinates"
    )
    async def right_click_mouse(self, x: int = None, y: int = None) -> str:
        return await self.safe_execute(
            self.mouse_ctrl.right_click, x, y, success_msg="Mouse right-clicked."
        )

    @llm.function_tool(
        description="Move the mouse cursor to the specified absolute x,y coordinates on the screen"
    )
    async def move_mouse(self, x: int, y: int) -> str:
        return await self.safe_execute(
            self.mouse_ctrl.move, x, y, success_msg=f"Mouse moved to {x},{y}."
        )

    @llm.function_tool(
        description="Scroll the mouse wheel. Positive amount scrolls up, negative amount scrolls down"
    )
    async def scroll_mouse(self, amount: int) -> str:
        return await self.safe_execute(
            self.mouse_ctrl.scroll, amount, success_msg=f"Mouse scrolled by {amount}."
        )

    @llm.function_tool(description="Get the current x,y coordinates of the mouse cursor")
    async def get_mouse_position(self) -> str:
        res = await self.safe_execute(self.mouse_ctrl.get_position)
        if isinstance(res, tuple):
            x, y = res
            return f"Mouse is currently at {x},{y}."
        return str(res)
