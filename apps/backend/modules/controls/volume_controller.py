from pycaw.pycaw import AudioUtilities
import logging
import pythoncom
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger("JARVIS.Volume")


@contextmanager
def _com_audio_endpoint():
    """Context manager: initializes COM, yields the volume endpoint, then uninitializes."""
    pythoncom.CoInitialize()
    try:
        devices = AudioUtilities.GetSpeakers()
        yield devices.EndpointVolume
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


class VolumeController:
    """
    VolumeController manages master audio settings on the system speaker endpoints using PyCaw.

    SYSTEM PROMPT:
    Use VolumeController to mute, unmute, or set the master system audio volume. Levels should be bounded between 0 and 100.

    SHORT DESCRIPTION:
    Manages master volume levels and mute states for system audio devices.

    PROCESS:
    1. Initializes Windows COM runtime via CoInitialize on target threads.
    2. Accesses system speakers endpoint interface via PyCaw utilities.
    3. Clamps percentage levels to [0, 100] and scales to float [0.0, 1.0].
    4. Sets MasterVolumeLevelScalar or SetMute state as requested.
    5. Cleanly releases COM references via context manager.

    FLOW:
    Caller -> set_volume()/mute()/unmute()/get_volume() -> _com_audio_endpoint() -> pycaw volume endpoints -> Caller
    """
    def __init__(self):
        logger.info("VolumeController initialized.")

    def get_volume(self) -> Optional[int]:
        """Returns the current master volume level as an integer (0-100), or None on error."""
        try:
            with _com_audio_endpoint() as vol:
                if vol:
                    scalar = vol.GetMasterVolumeLevelScalar()
                    level = round(scalar * 100)
                    logger.info(f"Current volume: {level}%")
                    return level
        except Exception as e:
            logger.error(f"Error getting volume: {e}")
        return None

    def set_volume(self, level: int) -> bool:
        """Sets volume to a specific percentage (0-100)."""
        try:
            with _com_audio_endpoint() as vol:
                if vol:
                    level = max(0, min(100, level))  # Clamp 0-100
                    vol.SetMasterVolumeLevelScalar(level / 100.0, None)
                    logger.info(f"Set volume to {level}%")
                    return True
        except Exception as e:
            logger.error(f"Error setting volume: {e}")
        return False

    def mute(self) -> bool:
        try:
            with _com_audio_endpoint() as vol:
                if vol:
                    vol.SetMute(1, None)
                    logger.info("System audio muted.")
                    return True
        except Exception as e:
            logger.error(f"Error muting volume: {e}")
        return False

    def unmute(self) -> bool:
        try:
            with _com_audio_endpoint() as vol:
                if vol:
                    vol.SetMute(0, None)
                    logger.info("System audio unmuted.")
                    return True
        except Exception as e:
            logger.error(f"Error unmuting volume: {e}")
        return False
