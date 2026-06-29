import screen_brightness_control as sbc
import logging

logger = logging.getLogger("JARVIS.Brightness")

class BrightnessController:
    """
    BrightnessController controls the computer monitor brightness.

    SYSTEM PROMPT:
    Use BrightnessController to adjust the system display brightness. Always stay within the 0 to 100 percentage range.

    SHORT DESCRIPTION:
    Manages the display brightness of local connected monitors.

    PROCESS:
    1. Validates the target level to ensure it is within [0, 100].
    2. Attempts adjustment using screen_brightness_control library.
    3. If screen_brightness_control fails, falls back to WMI (Windows Management Instrumentation) using wmi module to set the brightness on compatible monitors.

    FLOW:
    Caller -> set_brightness() -> screen_brightness_control / _set_brightness_wmi() -> Caller
    """
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
            import wmi
            wmi_obj = wmi.WMI(namespace='wmi')
            methods = wmi_obj.WmiMonitorBrightnessMethods()
            for method in methods:
                # 1 is the timeout, level is the brightness
                method.WmiSetBrightness(1, level)
            logger.info(f"Set brightness to {level}% via WMI.")
        except Exception as e:
            logger.error(f"WMI brightness control also failed: {e}")
