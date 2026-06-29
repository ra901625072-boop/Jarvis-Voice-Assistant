import os
import subprocess
import pyperclip
import pyautogui
import logging
import platform
import tempfile

logger = logging.getLogger("JARVIS.System")

class SystemController:
    """
    SystemController handles system shutdown, reboot, sleep, clipboard access, screenshots, and opening settings.

    SYSTEM PROMPT:
    Use SystemController to perform system operations (power state transitions, clipboard queries/edits, screenshots, settings apps). Always ask the user for confirmation prior to power operations (shutdown, restart, logout).

    SHORT DESCRIPTION:
    Manages host OS power functions, clipboard data, screen capture, and system configuration launchers.

    PROCESS:
    1. Executes shell commands or specialized DLL calls (e.g. rundll32.exe) to change power states (shutdown, restart, sleep, lock, logout).
    2. Interacts with the local keyboard/clipboard buffer via pyperclip.
    3. Triggers fullscreen capture via pyautogui and processes/saves as optimized JPEG files.
    4. Starts specific URI protocols (e.g., ms-settings:) to open Windows Settings pages.

    FLOW:
    Caller -> shutdown()/copy_text()/take_screenshot() -> subprocess / pyperclip / pyautogui / os.system() -> OS Kernel / GUI Subsystem -> Caller
    """
    def __init__(self):
        logger.info("SystemController initialized.")

    # Power Controls
    def shutdown(self):
        try:
            logger.info("Initiating system shutdown.")
            if platform.system() == "Windows":
                subprocess.run(["shutdown", "/s", "/t", "1"], check=True)
            else:
                subprocess.run(["shutdown", "-h", "now"], check=True)
            return True
        except Exception as e:
            logger.error(f"Failed to shutdown: {e}")
            return False

    def restart(self):
        try:
            logger.info("Initiating system restart.")
            if platform.system() == "Windows":
                subprocess.run(["shutdown", "/r", "/t", "1"], check=True)
            else:
                subprocess.run(["shutdown", "-r", "now"], check=True)
            return True
        except Exception as e:
            logger.error(f"Failed to restart: {e}")
            return False

    def sleep(self):
        try:
            logger.info("Initiating system sleep.")
            if platform.system() == "Windows":
                subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=True)
            else:
                subprocess.run(["systemctl", "suspend"], check=True)
            return True
        except Exception as e:
            logger.error(f"Failed to sleep: {e}")
            return False

    def lock_pc(self):
        try:
            logger.info("Locking PC.")
            if platform.system() == "Windows":
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=True)
                return True
            logger.warning("lock_pc is only supported on Windows.")
            return False
        except Exception as e:
            logger.error(f"Failed to lock PC: {e}")
            return False

    def logout(self):
        try:
            logger.info("Logging out.")
            if platform.system() == "Windows":
                subprocess.run(["shutdown", "/l"], check=True)
                return True
            logger.warning("logout is only supported on Windows.")
            return False
        except Exception as e:
            logger.error(f"Failed to logout: {e}")
            return False

    # Clipboard
    def copy_text(self, text):
        try:
            pyperclip.copy(text)
            logger.info("Copied text to clipboard.")
            return True
        except Exception as e:
            logger.error(f"Failed to copy to clipboard: {e}")
            return False

    def get_clipboard(self):
        try:
            return pyperclip.paste()
        except Exception as e:
            logger.error(f"Failed to get clipboard: {e}")
            return None

    def clear_clipboard(self):
        try:
            pyperclip.copy("")
            logger.info("Cleared clipboard.")
            return True
        except Exception as e:
            logger.error(f"Failed to clear clipboard: {e}")
            return False

    # Settings Pages (Windows specific)
    def _open_settings_page(self, uri: str, label: str = "settings") -> bool:
        """Internal helper to open a Windows Settings URI."""
        try:
            if platform.system() == "Windows":
                subprocess.run(["start", uri], shell=True, check=True)
            return True
        except Exception as e:
            logger.error(f"Failed to open {label}: {e}")
            return False

    def open_settings(self):
        return self._open_settings_page("ms-settings:", "settings")

    def open_wifi_settings(self):
        return self._open_settings_page("ms-settings:network-wifi", "wifi settings")

    def open_bluetooth_settings(self):
        return self._open_settings_page("ms-settings:bluetooth", "bluetooth settings")

    def open_display_settings(self):
        return self._open_settings_page("ms-settings:display", "display settings")

    # Screenshots
    def take_screenshot(self, save_path: str = None) -> bool:
        """Take a screenshot and save to the specified path (or a temp file)."""
        if save_path is None:
            save_path = os.path.join(tempfile.gettempdir(), "jarvis_screenshot.jpg")
        return _capture_screenshot(save_path)


def _capture_screenshot(target_path: str) -> bool:
    """Shared screenshot helper used by SystemController, capture_screen, and capture_screen_to_path."""
    try:
        image = pyautogui.screenshot()
        image = image.convert("RGB")
        image.thumbnail((1600, 900))
        image.save(target_path, "JPEG", quality=75, optimize=True)
        logger.info(f"Screenshot saved to {target_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to take screenshot: {e}")
        return False
