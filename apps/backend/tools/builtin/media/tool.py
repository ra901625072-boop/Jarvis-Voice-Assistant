"""toolsets/media_tools.py — MediaTools toolset."""
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.controls.volume_controller import VolumeController
from modules.controls.brightness_controller import BrightnessController
from modules.core.security_manager import SecurityManager


class MediaTools(JarvisToolset):
    """
    MediaTools provides options to set display and system audio configuration.

    SYSTEM PROMPT:
    Use MediaTools to alter sound levels (mute/unmute/set volume) and screen
    brightness values. Levels are bounded between 0 and 100 percent.

    SHORT DESCRIPTION:
    Manages system sound parameters and brightness controls.

    PROCESS:
    1. Directs brightness queries/updates to BrightnessController.
    2. Directs volume and mute controls to VolumeController.

    FLOW:
    Agent -> Tool call -> VolumeController / BrightnessController
          -> OS Audio/Video interface -> Agent
    """

    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self._volume_ctrl = VolumeController()
        self._brightness_ctrl = BrightnessController()

    @property
    def volume_ctrl(self) -> VolumeController:
        return self._volume_ctrl

    @property
    def brightness_ctrl(self) -> BrightnessController:
        return self._brightness_ctrl

    @llm.function_tool(description="Set the system volume to a specific percentage (0-100)")
    async def set_volume(self, level: int) -> str:
        return await self.safe_execute(
            self.volume_ctrl.set_volume, level, success_msg=f"Volume set to {level}%."
        )

    @llm.function_tool(description="Mute the system audio")
    async def mute_audio(self) -> str:
        return await self.safe_execute(self.volume_ctrl.mute, success_msg="Audio muted.")

    @llm.function_tool(description="Unmute the system audio")
    async def unmute_audio(self) -> str:
        return await self.safe_execute(self.volume_ctrl.unmute, success_msg="Audio unmuted.")

    @llm.function_tool(
        description="Set the system display brightness to a specific percentage (0-100)"
    )
    async def set_brightness(self, level: int) -> str:
        return await self.safe_execute(
            self.brightness_ctrl.set_brightness,
            level,
            success_msg=f"Brightness set to {level}%.",
        )
