from pycaw.pycaw import AudioUtilities
import logging
import pythoncom

logger = logging.getLogger("JARVIS.Volume")

class VolumeController:
    def __init__(self):
        logger.info("VolumeController initialized.")

    def set_volume(self, level: int):
        """Sets volume to a specific percentage (0-100)."""
        try:
            pythoncom.CoInitialize()
            devices = AudioUtilities.GetSpeakers()
            vol = devices.EndpointVolume
            if vol:
                level = max(0, min(100, level))  # Clamp 0-100
                vol.SetMasterVolumeLevelScalar(level / 100.0, None)
                logger.info(f"Set volume to {level}%")
            return True
        except Exception as e:
            logger.error(f"Error setting volume: {e}")
            return False
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def mute(self):
        try:
            pythoncom.CoInitialize()
            devices = AudioUtilities.GetSpeakers()
            vol = devices.EndpointVolume
            if vol:
                vol.SetMute(1, None)
                logger.info("System audio muted.")
            return True
        except Exception as e:
            logger.error(f"Error muting volume: {e}")
            return False
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def unmute(self):
        try:
            pythoncom.CoInitialize()
            devices = AudioUtilities.GetSpeakers()
            vol = devices.EndpointVolume
            if vol:
                vol.SetMute(0, None)
                logger.info("System audio unmuted.")
            return True
        except Exception as e:
            logger.error(f"Error unmuting volume: {e}")
            return False
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
