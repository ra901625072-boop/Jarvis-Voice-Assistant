"""
api/helpers.py — Shared helper utilities for FastAPI routes and WebSocket handlers.
"""
import asyncio
from typing import Any, Dict, Callable, Coroutine


def map_os_task_to_frontend(t: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize OS-level task dictionaries into standard frontend response objects."""
    status_raw = t.get("status", "pending")
    status_lower = status_raw.lower() if isinstance(status_raw, str) else str(status_raw).lower()

    if status_lower == "pending":
        status_lower = "queued"
    elif status_lower == "cancelled":
        status_lower = "failed"

    priority_val = t.get("priority", 60)
    if not isinstance(priority_val, (int, float)):
        priority_val = 60

    if priority_val >= 95:
        priority_str = "high"
    elif priority_val >= 50:
        priority_str = "normal"
    else:
        priority_str = "low"

    return {
        "task_id": t.get("id") or t.get("task_id", ""),
        "task_type": t.get("agent") or t.get("task_type", ""),
        "label": t.get("name") or t.get("label", ""),
        "status": status_lower,
        "progress": t.get("progress", 0),
        "created_at": t.get("created_at"),
        "started_at": t.get("started_at"),
        "finished_at": t.get("completed_at") or t.get("finished_at"),
        "error": t.get("error"),
        "result": str(t["result"]) if t.get("result") is not None else None,
        "priority": priority_str,
        "logs": t.get("logs", []),
        "is_os_task": True,
    }


def run_coroutine_sync(async_fn, *args, **kwargs):
    """Safely execute an async coroutine inside a fresh event loop for sync worker callbacks."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(async_fn(*args, **kwargs))
    finally:
        loop.close()
