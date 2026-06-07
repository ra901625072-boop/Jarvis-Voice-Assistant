import screen_brightness_control as sbc
import logging
import wmi

logger = logging.getLogger("JARVIS.Brightness")

class BrightnessController:
    def __init__(self):
        logger.info("BrightnessController initialized.")

    def set_brightness(self, level: int):
        """Sets brightness to a specific percentage (0-100)."""
        try:
            level = max(0, min(100, level))
            sbc.set_brightness(level)
            logger.info(f"Set brightness to {level}% via sbc.")
        except Exception as e:
            logger.warning(f"sbc failed ({e}), trying WMI fallback...")
            self._set_brightness_wmi(level)

    def _set_brightness_wmi(self, level: int):
        try:
            wmi_obj = wmi.WMI(namespace='wmi')
            methods = wmi_obj.WmiMonitorBrightnessMethods()
            for method in methods:
                # 1 is the timeout, level is the brightness
                method.WmiSetBrightness(1, level)
            logger.info(f"Set brightness to {level}% via WMI.")
        except Exception as e:
            logger.error(f"WMI brightness control also failed: {e}")
