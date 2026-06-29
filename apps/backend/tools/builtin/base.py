"""
toolsets/base.py — Base toolset class and TTL cache utility.

JarvisToolset is the common base class for all JARVIS LLM toolsets.
It provides:
  - safe_execute()       : runs a callable with optional security confirmation,
                           timing, WorldState updates, and tool-memory recording.
  - async_ttl_cache()   : a cachetools-backed TTL cache decorator for async
                           methods (fixes the args[1:] key-building bug in the
                           old hand-rolled version).
"""
import asyncio
import inspect
import logging
import os
import time
import threading
from functools import wraps

from livekit.agents import llm
from cachetools import TTLCache

_logger = logging.getLogger("JARVIS.Toolset")


# ── TTL cache ─────────────────────────────────────────────────────────────────

def async_ttl_cache(ttl: int = 300):
    """
    Async-safe TTL cache decorator backed by cachetools.TTLCache.

    Key is built from the function name + positional args (excluding self) +
    sorted keyword args.  This fixes the old args[1:] bug where methods with
    no additional args produced identical keys for different instances.
    """
    _cache: TTLCache = TTLCache(maxsize=256, ttl=ttl)
    _lock = threading.Lock()

    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Build a hashable cache key from func name + call arguments
            key = (func.__name__, args, tuple(sorted(kwargs.items())))
            with _lock:
                if key in _cache:
                    return _cache[key]
            result = await func(self, *args, **kwargs)
            with _lock:
                _cache[key] = result
            return result

        return wrapper

    return decorator


# ── JarvisToolset base ────────────────────────────────────────────────────────

class JarvisToolset(llm.Toolset):
    """
    Base class for all JARVIS LLM toolsets.

    Subclasses receive:
      self.security  — SecurityManager (optional)
      self.room      — LiveKit room (optional, injected per-session)
    """

    def __init__(self, security=None, room=None):
        super().__init__(id=self.__class__.__name__.lower())
        self.security = security
        self.room = room

    async def safe_execute(
        self,
        func,
        *args,
        confirmation_category: str = None,
        confirmation_action: str = None,
        confirmed: bool = False,
        success_msg: str = None,
        error_msg: str = None,
    ):
        """
        Execute a callable safely, with:
          1. Optional security confirmation gate (TIER_CONFIRM).
          2. Async vs. sync dispatch.
          3. WorldState update on success.
          4. Tool-memory recording.
          5. processing_start WebRTC event.
        """
        tool_name = getattr(func, "__name__", str(func))
        t0 = time.monotonic()
        try:
            if self.room:
                try:
                    msg = '{"type": "processing_start"}'
                    await self.room.local_participant.publish_data(msg.encode("utf-8"))
                except Exception:
                    pass

            # Security gate
            if confirmation_category and confirmation_action and self.security:
                if (
                    self.security.requires_confirmation(
                        confirmation_category, confirmation_action
                    )
                    and not confirmed
                ):
                    return (
                        f"SECURITY WARNING: This action requires user confirmation. "
                        f"Please ask the user to confirm they want to {confirmation_action}. "
                        f"Once they agree, call this tool again with confirmed=True."
                    )

            # Dispatch
            if inspect.iscoroutinefunction(func):
                result = await func(*args)
            else:
                result = await asyncio.to_thread(func, *args)

            exec_ms = int((time.monotonic() - t0) * 1000)
            logging.getLogger("JARVIS.Tool").info(
                f"Tool execution [{tool_name}]: {exec_ms / 1000.0:.3f}s"
            )

            is_error = result is False or (
                isinstance(result, str) and result.startswith("Error:")
            )

            # Record tool outcome in tool_memory (Phase 5 cognitive layer)
            try:
                if hasattr(self, "memory") and hasattr(self.memory, "lifecycle"):
                    self.memory.lifecycle.tool_memory.record(
                        tool_name,
                        not is_error,
                        exec_ms,
                        error=str(result)[:200] if is_error else None,
                    )
            except Exception:
                pass

            # Update WorldState on success
            if not is_error:
                try:
                    from modules.execution.world_state import WorldStateManager

                    ws = WorldStateManager()
                    if tool_name == "open_application" and args:
                        app_name = args[0] if args else ""
                        if app_name:
                            ws.update_shared_state(app_name, "open")
                    elif tool_name == "close_application" and args:
                        app_name = args[0] if args else ""
                        if app_name:
                            ws.update_shared_state(app_name, "closed")
                    elif tool_name == "open_url":
                        ws.update_shared_state("browser", "open")
                except Exception:
                    pass

            if is_error:
                return error_msg or result or "Failed to execute tool."
            if result is True and success_msg:
                return success_msg
            if success_msg:
                return success_msg
            return result

        except Exception as e:
            exec_ms = int((time.monotonic() - t0) * 1000)
            try:
                if hasattr(self, "memory") and hasattr(self.memory, "lifecycle"):
                    self.memory.lifecycle.tool_memory.record(
                        tool_name, False, exec_ms, error=str(e)[:200]
                    )
            except Exception:
                pass
            return f"Error: {e}"
