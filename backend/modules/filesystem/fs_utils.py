import os
import platform
import string
import logging

logger = logging.getLogger("JARVIS.FSUtils")

def get_drives() -> list:
    """Returns a list of all available drive letters on Windows."""
    drives = []
    if platform.system() == "Windows":
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                drives.append(drive)
    else:
        drives = ["/"]
    return drives

def is_safe_path(path: str) -> bool:
    """Blocks destructive modifications inside system root or windows directory."""
    try:
        path = os.path.normpath(os.path.abspath(path))
        path_lower = path.lower()
        
        system_drive = os.environ.get("SystemDrive", "C:") + "\\"
        system_drive_lower = system_drive.lower()
        
        unsafe_prefixes = [
            os.path.join(system_drive_lower, "windows"),
            os.path.join(system_drive_lower, "program files"),
            os.path.join(system_drive_lower, "program files (x86)"),
            os.path.join(system_drive_lower, "system volume information"),
            os.path.join(system_drive_lower, "$recycle.bin"),
            os.path.join(system_drive_lower, "recovery"),
            os.path.join(system_drive_lower, "boot")
        ]
        
        drive_roots = [d.lower() for d in get_drives()]
        if path_lower in drive_roots:
            return False
            
        for prefix in unsafe_prefixes:
            if path_lower.startswith(prefix):
                return False
                
        if path_lower == "c:\\" or path_lower == "c:":
            return False
            
        return True
    except Exception as e:
        logger.error(f"Error checking safety of path {path}: {e}")
        return False

def close_explorer_window(path: str) -> bool:
    """Closes File Explorer windows matching the folder path."""
    if platform.system() != "Windows":
        return False
        
    path = os.path.normpath(os.path.abspath(path))
    try:
        import win32com.client
        shell = win32com.client.Dispatch("Shell.Application")
        closed_explorer = False
        for window in shell.Windows():
            try:
                if window.Name in ["File Explorer", "Windows Explorer"]:
                    window_path = os.path.normpath(window.Document.Folder.Self.Path)
                    if window_path.lower() == path.lower():
                        window.Quit()
                        closed_explorer = True
            except Exception as e:
                logger.debug(f"Ignored error closing folder window: {e}")
        
        if closed_explorer:
            logger.info(f"Closed folder window for: {path}")
            return True
        else:
            logger.debug(f"Could not find an open Explorer window for: {path}")
            return False
    except ImportError:
        logger.debug("win32com not available.")
        return False
    except Exception as e:
        logger.error(f"Failed to close folder {path}: {e}")
        return False
