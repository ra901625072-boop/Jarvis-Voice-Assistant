import logging
import psutil
import pyperclip
import threading
import time
from typing import Dict, List, Any
try:
    import pygetwindow as gw
except ImportError:
    gw = None

logger = logging.getLogger("JARVIS.WorldState")

class WorldStateManager:
    """
    WorldStateManager captures system indicators including running processes, open windows, and clipboard contents.
    Converts to a thread-safe singleton managing shared state updates and short-lived snapshot cache.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(WorldStateManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._last_snapshot = {}
        self._last_snapshot_time = 0.0
        self._state_lock = threading.Lock()  # Instance lock (separate from class-level singleton _lock)
        self._shared_state = {}
        self._initialized = True
        logger.info("WorldStateManager singleton initialized.")

    def update_shared_state(self, key: str, value: Any):
        with self._state_lock:
            self._shared_state[key.lower()] = value
            logger.info(f"WorldState shared_state updated: {key} -> {value}")

    def get_shared_state(self, key: str, default: Any = None) -> Any:
        with self._state_lock:
            return self._shared_state.get(key.lower(), default)

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

    def get_state_snapshot(self, max_age: float = 0.5) -> Dict[str, Any]:
        """Captures and returns the current world state, using a short-lived cache."""
        # Fast path: return cached snapshot if still fresh
        with self._state_lock:
            now = time.time()
            if self._last_snapshot and (now - self._last_snapshot_time < max_age):
                return self._last_snapshot

        # Collect expensive I/O OUTSIDE the lock to avoid blocking other threads
        windows = self.get_open_windows()
        processes = self.get_running_processes()
        clipboard = self.get_clipboard_content()

        # Atomically update the cache
        with self._state_lock:
            now = time.time()
            # Double-check: another thread may have refreshed while we collected
            if self._last_snapshot and (now - self._last_snapshot_time < max_age):
                return self._last_snapshot
            self._last_snapshot = {
                "windows": windows,
                "processes": processes,
                "clipboard": clipboard
            }
            self._last_snapshot_time = now
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
