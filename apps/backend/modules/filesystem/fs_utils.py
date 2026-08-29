import os
import platform
import string
import logging

logger = logging.getLogger("JARVIS.FSUtils")

def get_drives() -> list:
    """Returns a list of all available drive letters on Windows."""
    from modules.security.manager import SecurityManager
    return SecurityManager._get_drives()

def is_safe_path(path: str) -> bool:
    """
    .. deprecated::
        Use ``SecurityManager.is_safe_path()`` instead.

    This shim exists only for backward compatibility.  All new code should
    route path-safety checks through SecurityManager to avoid duplicate
    blocklist definitions.
    """
    import warnings
    warnings.warn(
        "fs_utils.is_safe_path() is deprecated. Use SecurityManager.is_safe_path() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from modules.security.manager import SecurityManager
    return SecurityManager().is_safe_path(path)

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
