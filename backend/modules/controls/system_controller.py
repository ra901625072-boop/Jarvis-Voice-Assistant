import os
import pyperclip
import pyautogui
import logging
import platform
import tempfile

logger = logging.getLogger("JARVIS.System")

class SystemController:
    def __init__(self):
        logger.info("SystemController initialized.")

    # Power Controls
    def shutdown(self):
        try:
            logger.info("Initiating system shutdown.")
            if platform.system() == "Windows":
                os.system("shutdown /s /t 1")
            else:
                os.system("shutdown -h now")
            return True
        except Exception as e:
            logger.error(f"Failed to shutdown: {e}")
            return False

    def restart(self):
        try:
            logger.info("Initiating system restart.")
            if platform.system() == "Windows":
                os.system("shutdown /r /t 1")
            else:
                os.system("shutdown -r now")
            return True
        except Exception as e:
            logger.error(f"Failed to restart: {e}")
            return False

    def sleep(self):
        try:
            logger.info("Initiating system sleep.")
            if platform.system() == "Windows":
                os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
            else:
                os.system("systemctl suspend")
            return True
        except Exception as e:
            logger.error(f"Failed to sleep: {e}")
            return False

    def lock_pc(self):
        try:
            logger.info("Locking PC.")
            if platform.system() == "Windows":
                os.system("rundll32.exe user32.dll,LockWorkStation")
            return True
        except Exception as e:
            logger.error(f"Failed to lock PC: {e}")
            return False

    def logout(self):
        try:
            logger.info("Logging out.")
            if platform.system() == "Windows":
                os.system("shutdown /l")
            return True
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

    # Screenshots
    def take_screenshot(self, save_path="screenshot.jpg"):
        try:
            image = pyautogui.screenshot()
            image = image.convert("RGB")
            image.thumbnail((1600, 900))
            image.save(save_path, "JPEG", quality=75, optimize=True)
            logger.info(f"Screenshot saved to {save_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return False

    # Settings Pages (Windows specific)
    def open_settings(self):
        try:
            if platform.system() == "Windows":
                os.system("start ms-settings:")
            return True
        except Exception as e:
            logger.error("Failed to open settings.")
            return False

    def open_wifi_settings(self):
        try:
            if platform.system() == "Windows":
                os.system("start ms-settings:network-wifi")
            return True
        except Exception as e:
            logger.error("Failed to open wifi settings.")
            return False

    def open_bluetooth_settings(self):
        try:
            if platform.system() == "Windows":
                os.system("start ms-settings:bluetooth")
            return True
        except Exception as e:
            logger.error("Failed to open bluetooth settings.")
            return False

    def open_display_settings(self):
        try:
            if platform.system() == "Windows":
                os.system("start ms-settings:display")
            return True
        except Exception as e:
            return False

def capture_screen():
    temp_file = tempfile.NamedTemporaryFile(
        suffix=".jpg",
        delete=False
    )
    screenshot = pyautogui.screenshot()
    screenshot = screenshot.convert("RGB")
    screenshot.thumbnail((1600, 900))
    screenshot.save(temp_file.name, "JPEG", quality=75, optimize=True)
    return temp_file.name

def capture_screen_to_path(target_path):
    screenshot = pyautogui.screenshot()
    screenshot = screenshot.convert("RGB")
    screenshot.thumbnail((1600, 900))
    screenshot.save(target_path, "JPEG", quality=75, optimize=True)
    logger.info(f"Screenshot saved to {target_path}")
