"""
base_adapter.py — Abstract Base Class for Social Media Platform Adapters.

Provides common rate limiting, health checks, approval preview extraction,
and standardized execution signatures across all social platforms.
"""
from abc import ABC, abstractmethod
import time
import logging
import asyncio
from collections import deque
from typing import Any, Dict, Optional, Tuple, List

logger = logging.getLogger("JARVIS.PlatformAdapter")


class PlatformAdapter(ABC):
    """
    Abstract Base Class for platform adapters (Gmail, WhatsApp, LinkedIn, Instagram).
    """

    def __init__(self, platform_name: str, max_requests_per_hour: int = 30):
        self.platform_name = platform_name.lower().strip()
        self.max_requests_per_hour = max_requests_per_hour
        self._action_timestamps: deque = deque()
        self._killswitch = False

    def set_killswitch(self, active: bool) -> None:
        """Enable or disable platform killswitch locally."""
        self._killswitch = active

    def is_killswitch_active(self) -> bool:
        return self._killswitch

    async def check_rate_limit(self) -> Tuple[bool, str]:
        """
        Sliding-window rate limiter checking actions in the last 3600 seconds.
        Tries to use Redis and falls back to in-memory deque.
        Returns (is_allowed, error_reason).
        """
        now = time.time()
        window_start = now - 3600.0

        from container import ServiceContainer
        container = ServiceContainer.instance()
        bus = container.get_or_none("agent_bus") if container else None

        if bus and hasattr(bus, "_connected") and bus._connected and bus._redis:
            try:
                redis_client = bus._redis
                key = f"jarvis:rate_limit:{self.platform_name}"
                # Remove timestamps older than window_start
                await redis_client.zremrangebyscore(key, "-inf", window_start)
                # Count current timestamps in the window
                count = await redis_client.zcard(key)
                if count >= self.max_requests_per_hour:
                    oldest_elements = await redis_client.zrange(key, 0, 0, withscores=True)
                    if oldest_elements:
                        item = oldest_elements[0]
                        if isinstance(item, tuple):
                            oldest_ts = float(item[1])
                        else:
                            oldest_ts = await redis_client.zscore(key, item)
                            if oldest_ts is None:
                                oldest_ts = float(item)
                        remaining = int(3600 - (now - oldest_ts))
                    else:
                        remaining = 3600
                    return (
                        False,
                        f"Rate limit reached for {self.platform_name} ({self.max_requests_per_hour}/hr). "
                        f"Reset in {remaining} seconds."
                    )
                return True, ""
            except Exception as e:
                logger.warning(f"Redis rate limiting failed: {e}. Falling back to in-memory.")

        # Fallback: In-memory sliding window
        while self._action_timestamps and self._action_timestamps[0] < window_start:
            self._action_timestamps.popleft()

        if len(self._action_timestamps) >= self.max_requests_per_hour:
            remaining = int(3600 - (now - self._action_timestamps[0]))
            return (
                False,
                f"Rate limit reached for {self.platform_name} ({self.max_requests_per_hour}/hr). "
                f"Reset in {remaining} seconds."
            )

        return True, ""

    def record_action(self) -> None:
        """Record an action timestamp into the sliding window (persistent via Redis if active)."""
        now = time.time()
        self._action_timestamps.append(now)

        from container import ServiceContainer
        container = ServiceContainer.instance()
        bus = container.get_or_none("agent_bus") if container else None

        if bus and hasattr(bus, "_connected") and bus._connected and bus._redis:
            async def _bg_record():
                try:
                    redis_client = bus._redis
                    key = f"jarvis:rate_limit:{self.platform_name}"
                    await redis_client.zadd(key, {str(now): now})
                    await redis_client.zremrangebyscore(key, "-inf", now - 3600.0)
                except Exception as e:
                    logger.warning(f"Failed to record action to Redis background: {e}")

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_bg_record())
            except RuntimeError:
                pass

    async def get_rate_limit_status(self) -> Dict[str, Any]:
        """Returns rate limit headroom and capacity, querying Redis if available."""
        now = time.time()
        window_start = now - 3600.0

        from container import ServiceContainer
        container = ServiceContainer.instance()
        bus = container.get_or_none("agent_bus") if container else None

        if bus and hasattr(bus, "_connected") and bus._connected and bus._redis:
            try:
                redis_client = bus._redis
                key = f"jarvis:rate_limit:{self.platform_name}"
                await redis_client.zremrangebyscore(key, "-inf", window_start)
                active_count = await redis_client.zcard(key)
                return {
                    "platform": self.platform_name,
                    "max_per_hour": self.max_requests_per_hour,
                    "used_last_hour": active_count,
                    "remaining": max(0, self.max_requests_per_hour - active_count),
                }
            except Exception as e:
                logger.warning(f"Failed to query rate limit status from Redis: {e}")

        # Fallback to in-memory
        active_count = sum(1 for t in self._action_timestamps if t >= window_start)
        return {
            "platform": self.platform_name,
            "max_per_hour": self.max_requests_per_hour,
            "used_last_hour": active_count,
            "remaining": max(0, self.max_requests_per_hour - active_count),
        }

    @abstractmethod
    async def connect(self, **kwargs) -> bool:
        """Initialize or authenticate the platform session/client."""
        pass

    @abstractmethod
    async def disconnect(self) -> bool:
        """Tear down or log out from the platform."""
        pass

    @abstractmethod
    async def health(self) -> Dict[str, Any]:
        """Return connectivity and authentication health status."""
        pass

    @abstractmethod
    async def execute(self, task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the requested task on the platform.
        Returns a dict containing at minimum {'success': bool, ...}.
        """
        pass

    def get_approval_preview(self, task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract a user-facing preview of an outbound action for the approval card.
        """
        recipient = payload.get("to") or payload.get("recipient") or payload.get("username") or payload.get("id") or payload.get("target_id") or "Unknown"
        subject = payload.get("subject", "")
        body = payload.get("body") or payload.get("text") or payload.get("caption") or ""
        if task_type in ("follow_user", "follow"):
            body = f"Follow user @{recipient}"
        elif task_type in ("unfollow_user", "unfollow"):
            body = f"Unfollow user @{recipient}"
        elif task_type in ("reply_message",):
            body = f"Reply on WhatsApp to {recipient}: {body}"
        elif task_type in ("forward_message",):
            body = f"Forward message to {recipient}"
        elif task_type in ("clear_chat", "delete_chat"):
            body = f"Clear chat with {recipient}"
        elif task_type in ("pin_chat", "pin"):
            body = f"Pin chat with {recipient}"
        elif task_type in ("archive_chat", "archive"):
            body = f"Archive chat with {recipient}"
        elif task_type in ("mute_chat", "mute"):
            body = f"Mute notifications for {recipient}"
        elif task_type in ("reply_email", "reply"):
            body = f"Reply to {recipient}: {body}"
        elif task_type in ("forward_email", "forward"):
            body = f"Forward email to {recipient}: {body}"
        elif task_type in ("trash_email", "delete_email"):
            body = f"Move email ({recipient}) to Trash"
        elif task_type in ("send_draft",):
            body = f"Send Draft ID: {payload.get('draft_id') or recipient}"
        media = payload.get("media_path") or payload.get("attachment")
        
        preview_text = body[:200] + ("..." if len(body) > 200 else "")
        return {
            "platform": self.platform_name,
            "action": task_type,
            "recipient": recipient,
            "subject": subject,
            "preview": preview_text,
            "media": media,
        }
