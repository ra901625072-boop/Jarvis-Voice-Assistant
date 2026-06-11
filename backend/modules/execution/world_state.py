import logging
import psutil
import pyperclip
from typing import Dict, List, Any
try:
    import pygetwindow as gw
except ImportError:
    gw = None

logger = logging.getLogger("JARVIS.WorldState")

class WorldStateManager:
    """
    Maintains a deterministic snapshot of the OS environment.
    """
    def __init__(self):
        self._last_snapshot = {}

    def get_running_processes(self) -> List[str]:
        """Returns a list of key running process names (deduplicated)."""
        processes = set()
        for proc in psutil.process_iter(['name']):
            try:
                name = proc.info['name']
                if name:
                    processes.add(name.lower())
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return list(processes)

    def get_open_windows(self) -> List[Dict[str, Any]]:
        """Returns active window titles and states."""
        if not gw:
            return []
        windows = []
        for win in gw.getAllWindows():
            if win.title and win.visible and win.width > 0 and win.height > 0:
                windows.append({
                    "title": win.title,
                    "is_active": win.isActive,
                    "is_maximized": win.isMaximized,
                    "is_minimized": win.isMinimized
                })
        return windows

    def get_clipboard_content(self) -> str:
        """Retrieves the current clipboard text."""
        try:
            content = pyperclip.paste()
            return content[:500] + ("..." if len(content) > 500 else "")
        except Exception as e:
            logger.debug(f"Failed to read clipboard: {e}")
            return ""

    def get_state_snapshot(self) -> Dict[str, Any]:
        """Captures and returns the current world state."""
        self._last_snapshot = {
            "windows": self.get_open_windows(),
            "processes": self.get_running_processes(),
            "clipboard": self.get_clipboard_content()
        }
        return self._last_snapshot

    def format_state_for_planner(self) -> str:
        """Formats the state snapshot into a concise string for LLM injection."""
        state = self.get_state_snapshot()
        
        # Format processes (only common targets to avoid noise)
        common_procs = {"chrome.exe", "msedge.exe", "code.exe", "explorer.exe", "notepad.exe", "cmd.exe", "powershell.exe", "spotify.exe", "discord.exe"}
        active_procs = [p for p in state["processes"] if p in common_procs]
        
        # Format windows
        windows_str = ""
        for w in state["windows"]:
            active_marker = "*" if w["is_active"] else " "
            state_marker = "[MIN]" if w["is_minimized"] else ""
            windows_str += f"  {active_marker} {state_marker} {w['title']}\n"
            
        clipboard_str = state["clipboard"].replace('\n', ' ')
        if len(clipboard_str) > 100:
            clipboard_str = clipboard_str[:97] + "..."
            
        return (
            "--- CURRENT WORLD STATE ---\n"
            f"Active Key Processes: {', '.join(active_procs) if active_procs else 'None'}\n"
            f"Open Windows (* = active):\n{windows_str if windows_str else '  None'}\n"
            f"Clipboard Content: {clipboard_str if clipboard_str else '<empty>'}\n"
        )
