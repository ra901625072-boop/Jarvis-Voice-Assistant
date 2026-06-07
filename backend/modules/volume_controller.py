from pycaw.pycaw import AudioUtilities
import logging
import pythoncom

logger = logging.getLogger("JARVIS.Volume")

class VolumeController:
    def __init__(self):
        logger.info("VolumeController initialized.")

    def _get_volume(self):
        try:
            # Need to initialize COM on whatever thread this is called from
            pythoncom.CoInitialize()
            devices = AudioUtilities.GetSpeakers()
            return devices.EndpointVolume
        except Exception as e:
            logger.error(f"Failed to get Volume endpoint: {e}")
            return None

    def set_volume(self, level: int):
        """Sets volume to a specific percentage (0-100)."""
        vol = self._get_volume()
        if vol is None:
            return
            
        try:
            level = max(0, min(100, level)) # Clamp 0-100
            
            # Pycaw works in decibels, but we can set scalar directly
            vol.SetMasterVolumeLevelScalar(level / 100.0, None)
            logger.info(f"Set volume to {level}%")
        except Exception as e:
            logger.error(f"Error setting volume: {e}")

    def mute(self):
        vol = self._get_volume()
        if vol:
            vol.SetMute(1, None)

    def unmute(self):
        vol = self._get_volume()
        if vol:
            vol.SetMute(0, None)
