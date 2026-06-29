"""toolsets/keyboard_tools.py — KeyboardTools toolset."""
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.controls.keyboard_controller import KeyboardController
from modules.core.security_manager import SecurityManager


class KeyboardTools(JarvisToolset):
    """
    KeyboardTools allows programmatic text entry and key events.

    SYSTEM PROMPT:
    Use KeyboardTools to enter text or send hotkeys. For texts exceeding 500
    characters, require confirmation parameter.

    SHORT DESCRIPTION:
    Enables simulated hardware keyboard actions including typing, holding,
    releasing, and combined shortcuts.

    PROCESS:
    1. Checks text length safety parameters.
    2. Invokes KeyboardController functions to send keystrokes.

    FLOW:
    Agent -> Tool call -> KeyboardController -> OS Input Subsystem -> Agent
    """

    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self._keyboard_ctrl = KeyboardController()

    @property
    def keyboard_ctrl(self) -> KeyboardController:
        return self._keyboard_ctrl

    @llm.function_tool(description="Type a given text string exactly using the keyboard")
    async def type_text(self, text: str, confirmed: bool = False) -> str:
        if len(text) > 500 and not confirmed:
            return (
                "SECURITY WARNING: The text is too long. Please ask the user to confirm "
                "they want to type this much text. Call again with confirmed=True."
            )
        return await self.safe_execute(
            self.keyboard_ctrl.type_text, text, success_msg="Typed the given text."
        )

    @llm.function_tool(
        description="Press a specific key or key combination string (e.g., 'enter', 'ctrl+c', 'win+d')"
    )
    async def press_key(self, keys: str) -> str:
        return await self.safe_execute(
            self.keyboard_ctrl.press_key, keys, success_msg=f"Pressed keys: {keys}."
        )

    @llm.function_tool(description="Hold down a specific key (e.g., 'shift', 'ctrl', 'a')")
    async def hold_key(self, key: str) -> str:
        return await self.safe_execute(
            self.keyboard_ctrl.hold_key, key, success_msg=f"Held down key: {key}."
        )

    @llm.function_tool(description="Release a specific key that was previously held down")
    async def release_key(self, key: str) -> str:
        return await self.safe_execute(
            self.keyboard_ctrl.release_key, key, success_msg=f"Released key: {key}."
        )
