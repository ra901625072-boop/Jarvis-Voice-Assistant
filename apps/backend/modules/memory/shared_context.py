import asyncio
import logging
from typing import Any, Dict, Optional, List
from datetime import datetime

logger = logging.getLogger("JARVIS.SharedContext")

class SharedContextStore:
    """
    Thread-safe, async-accessible state storage for sharing project context,
    active goals, git status, search findings, and environment state across all agent workers.
    """
    _instance: Optional["SharedContextStore"] = None

    def __init__(self):
        self._data: Dict[str, Any] = {
            "active_project": None,
            "git_branch": "main",
            "current_errors": [],
            "last_commit": None,
            "active_tasks_count": 0,
            "research_notes": {},
            "user_preferences": {},
            "system_status": "ONLINE"
        }
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "SharedContextStore":
        if cls._instance is None:
            cls._instance = SharedContextStore()
        return cls._instance

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._global_lock:
            return self._data.get(key, default)

    async def set(self, key: str, value: Any) -> None:
        async with self._global_lock:
            self._data[key] = value
            logger.debug(f"SharedContext update: {key} = {value}")

    async def update_dict(self, key: str, updates: Dict[str, Any]) -> None:
        async with self._global_lock:
            if key not in self._data or not isinstance(self._data[key], dict):
                self._data[key] = {}
            self._data[key].update(updates)

    async def append_list(self, key: str, item: Any) -> None:
        async with self._global_lock:
            if key not in self._data or not isinstance(self._data[key], list):
                self._data[key] = []
            self._data[key].append(item)

    async def snapshot(self) -> Dict[str, Any]:
        async with self._global_lock:
            return dict(self._data)
