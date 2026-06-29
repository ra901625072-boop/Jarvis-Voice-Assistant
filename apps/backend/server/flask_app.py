"""
Flask web server for JARVIS — all HTTP routes extracted from main.py.

Routes:
  GET /token   — Issue a LiveKit room token + dispatch agent (rate-limited + auth-gated)
  GET /stats   — Return CPU usage + temperature (auth-gated)
  GET /        — Serve frontend index.html

Security:
  - API key must be sent via 'Authorization' header only (no query params).
  - Rate limiter uses TTLCache for O(1) bounded memory.
"""
import os
import uuid
import asyncio
import functools
import logging
import threading

from flask import Flask, jsonify, request, send_from_directory
from cachetools import TTLCache
from livekit import api

from modules.core.hardware_stats import get_cpu_temperature

logger = logging.getLogger("JARVIS.WebServer")

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(frontend_path: str) -> Flask:
    app = Flask(__name__, static_folder=frontend_path, static_url_path="")

    # ── Rate limiter: max 5 requests / IP / 60 s — bounded memory ──────────
    # TTLCache entries auto-expire after `ttl` seconds, so inactive IPs are
    # evicted automatically without a background sweep thread.
    _rate_cache_lock = threading.Lock()
    _token_rate: TTLCache = TTLCache(maxsize=10_000, ttl=60)

    def _check_rate_limit(ip: str) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        with _rate_cache_lock:
            count = _token_rate.get(ip, 0)
            if count >= 5:
                return False
            _token_rate[ip] = count + 1
            return True

    # ── Auth decorator ───────────────────────────────────────────────────────
    def require_api_key(f):
        """Decorator: reject requests whose Authorization header doesn't match JARVIS_API_KEY."""
        import hmac

        @functools.wraps(f)
        def _inner(*args, **kwargs):
            req_key = request.headers.get("Authorization", "")
            expected = os.environ.get("JARVIS_API_KEY", "")
            if not expected or not req_key:
                return jsonify({"error": "Unauthorized"}), 401
            try:
                if not hmac.compare_digest(
                    req_key.encode("utf-8"), expected.encode("utf-8")
                ):
                    return jsonify({"error": "Unauthorized"}), 401
            except Exception:
                return jsonify({"error": "Unauthorized"}), 401
            return f(*args, **kwargs)

        return _inner

    # ── Dedicated background event loop for async LiveKit dispatch ───────────
    _dispatch_loop = asyncio.new_event_loop()

    def _start_loop():
        asyncio.set_event_loop(_dispatch_loop)
        _dispatch_loop.run_forever()

    threading.Thread(target=_start_loop, daemon=True, name="JarvisDispatchLoop").start()

    _livekit_api_ref = {"api": None}

    # ── Routes ───────────────────────────────────────────────────────────────

    @app.route("/token", methods=["GET"])
    @require_api_key
    def token_handler():
        ip = request.remote_addr
        if not _check_rate_limit(ip):
            return (
                jsonify({"error": "Rate limit exceeded. Maximum 5 token requests per minute."}),
                429,
            )

        try:
            room_name = f"jarvis-room-{uuid.uuid4().hex[:8]}"

            grant = api.VideoGrants(room_join=True, room=room_name)
            token = (
                api.AccessToken(
                    os.environ.get("LIVEKIT_API_KEY"),
                    os.environ.get("LIVEKIT_API_SECRET"),
                )
                .with_identity("User_Frontend")
                .with_name("Web User")
                .with_grants(grant)
            )

            async def _dispatch():
                if _livekit_api_ref["api"] is None:
                    _livekit_api_ref["api"] = api.LiveKitAPI(
                        os.environ.get("LIVEKIT_URL"),
                        os.environ.get("LIVEKIT_API_KEY"),
                        os.environ.get("LIVEKIT_API_SECRET"),
                    )
                try:
                    await _livekit_api_ref["api"].agent_dispatch.create_dispatch(
                        api.CreateAgentDispatchRequest(
                            agent_name=os.environ.get("AGENT_NAME", "jarvis"),
                            room=room_name,
                        )
                    )
                except Exception as e:
                    logger.error(f"Error dispatching agent: {e}")

            asyncio.run_coroutine_threadsafe(_dispatch(), _dispatch_loop)

            return jsonify(
                {
                    "token": token.to_jwt(),
                    "url": os.environ.get("LIVEKIT_URL", "ws://localhost:7880"),
                }
            )
        except Exception as e:
            logger.exception(f"Failed to generate session token: {e}")
            return jsonify({"error": "Failed to generate session token."}), 500

    @app.route("/stats", methods=["GET"])
    @require_api_key
    def stats_handler():
        import psutil

        cpu_percent = psutil.cpu_percent(interval=0)
        temp = get_cpu_temperature()
        source = "hardware" if temp is not None else "unavailable"
        return jsonify({"cpu": cpu_percent, "temp": temp, "temp_source": source})

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    return app
