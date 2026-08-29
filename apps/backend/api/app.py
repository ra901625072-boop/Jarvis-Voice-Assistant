from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import os
import logging

from api.dependencies import get_security_manager
from api.middleware.auth import get_current_user

# Configure logger
logger = logging.getLogger("JARVIS.API.App")

# ── Rate limiter for /token ───────────────────────────────────────────────
from cachetools import TTLCache
import threading

token_rate_cache_lock = threading.Lock()
token_rate_cache = TTLCache(maxsize=10000, ttl=60)


def create_fastapi_app() -> FastAPI:
    cors_origins = [
        "http://localhost:8000",
        "http://localhost:8001",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8001",
        "http://127.0.0.1:5173",
    ]
    custom_origins = os.environ.get("JARVIS_CORS_ORIGINS")
    if custom_origins:
        cors_origins.extend([o.strip() for o in custom_origins.split(",")])
        
    # Dynamically resolve local network IP and add to CORS list
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            cors_origins.append(f"http://{local_ip}:8000")
            cors_origins.append(f"http://{local_ip}:8001")
            cors_origins.append(f"http://{local_ip}:5173")
    except Exception:
        pass

    # Initialize FastAPI application
    app = FastAPI(
        title="JARVIS API",
        description="REST & WebSocket API for JARVIS Multi-Agent System",
        version="2.0"
    )
    
    # Enable CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Disable caching for static frontend files to prevent stale scripts on page load
    from fastapi import Request
    @app.middleware("http")
    async def add_no_cache_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path.lower()
        if path.endswith((".js", ".css", ".html")) or not path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response
    
    def check_fastapi_rate_limit(request: Request):
        if os.environ.get("JARVIS_DISABLE_RATE_LIMIT") == "true":
            return
        ip = request.client.host if request.client else "127.0.0.1"
        with token_rate_cache_lock:
            count = token_rate_cache.get(ip, 0)
            if count >= 5:
                raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 5 token requests per minute.")
            token_rate_cache[ip] = count + 1

    from api.schemas import TokenRequest, TokenResponse, UploadRequest, UploadResponse

    # Authentication / JWT generation
    @app.post("/api/auth/token", response_model=TokenResponse)
    async def login(body: TokenRequest, request: Request, security_mgr = Depends(get_security_manager)):
        check_fastapi_rate_limit(request)
        key = body.api_key
        expected = os.environ.get("JARVIS_API_KEY", "")
        import hmac
        if not expected or not key:
            raise HTTPException(status_code=401, detail="Unauthorized: key missing")
        try:
            if not hmac.compare_digest(key.encode("utf-8"), expected.encode("utf-8")):
                raise HTTPException(status_code=401, detail="Unauthorized: invalid key")
        except Exception:
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        token = security_mgr.create_jwt(user_id="user_admin", role="admin")
        return {"token": token, "token_type": "bearer"}

    # Base64-based file upload endpoint
    @app.post("/api/upload", response_model=UploadResponse)
    async def upload_file(body: UploadRequest, current_user: dict = Depends(get_current_user)):
        filename = body.filename
        base64_data = body.content
        
        # Sanitize filename to prevent path traversal
        raw_name = os.path.basename(filename).strip()
        if not raw_name or raw_name in (".", "..") or "/" in raw_name or "\\" in raw_name:
            raise HTTPException(status_code=400, detail="Invalid filename")
            
        import base64
        import uuid
        import re
        
        # Strip unsafe characters
        safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', raw_name)
        file_id = f"{uuid.uuid4().hex[:12]}_{safe_name}"
        
        try:
            file_bytes = base64.b64decode(base64_data, validate=True)
            
            # Enforce 10MB upload limit
            max_size = 10 * 1024 * 1024
            if len(file_bytes) > max_size:
                raise HTTPException(status_code=413, detail=f"File exceeds maximum allowed size of 10MB ({len(file_bytes)} bytes)")
            
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            upload_dir = os.path.join(backend_dir, "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            
            file_path = os.path.join(upload_dir, file_id)
            with open(file_path, "wb") as f:
                f.write(file_bytes)
                
            rel_path = f"uploads/{file_id}"
            return {"status": "success", "filepath": rel_path, "file_id": file_id, "filename": safe_name}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to save uploaded file: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to process upload: {str(e)}")


    # Include routers
    from api.routes.auth import router as auth_router, ensure_admin_user
    from api.dependencies import get_memory
    try:
        ensure_admin_user(get_memory())
    except Exception as e:
        logger.error(f"Startup ensure_admin_user failed: {e}")

    from api.routes.tasks import router as tasks_router
    from api.routes.agents import router as agents_router
    from api.routes.workflows import router as workflows_router
    from api.routes.skills import router as skills_router
    from api.routes.schedules import router as schedules_router
    from api.routes.websocket import router as ws_router
    from api.routes.notifications import router as notifications_router
    from api.routes.observability import router as obs_router
    from api.routes.approvals import router as approvals_router
    from api.routes.sessions import router as sessions_router
    from api.routes.social_media import router as social_media_router
    from api.routes.webhooks import router as webhooks_router

    app.include_router(auth_router)
    app.include_router(tasks_router)
    app.include_router(agents_router)
    app.include_router(workflows_router)
    app.include_router(skills_router)
    app.include_router(schedules_router)
    app.include_router(ws_router)
    app.include_router(notifications_router)
    app.include_router(obs_router)
    app.include_router(approvals_router)
    app.include_router(sessions_router)
    app.include_router(social_media_router)
    app.include_router(webhooks_router)

    # ── Rate limiter for /token ───────────────────────────────────────────────
    def check_token_rate_limit(ip: str):
        with token_rate_cache_lock:
            count = token_rate_cache.get(ip, 0)
            if count >= 5:
                raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 5 token requests per minute.")
            token_rate_cache[ip] = count + 1

    # ── Helper auth for /token ───────────────────────────────────────────────
    async def get_token_username(request: Request, security_mgr = Depends(get_security_manager)) -> str:
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        expected = os.environ.get("JARVIS_API_KEY", "")
        import hmac
        # Check if raw API key matches using time-constant comparison
        if expected and auth_header:
            try:
                if hmac.compare_digest(auth_header.encode("utf-8"), expected.encode("utf-8")):
                    return "admin"
            except Exception:
                pass

        # Check if it is a valid JWT token
        token = auth_header
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        try:
            payload = security_mgr.verify_jwt(token)
            return payload.get("sub", "admin")
        except Exception:
            raise HTTPException(status_code=401, detail="Unauthorized")

    # ── LiveKit API client caching for token handler ─────────────────────────
    livekit_api_ref = {"api": None}

    def get_livekit_api():
        if livekit_api_ref["api"] is None:
            from livekit import api as lk_api
            livekit_api_ref["api"] = lk_api.LiveKitAPI(
                os.environ.get("LIVEKIT_URL"),
                os.environ.get("LIVEKIT_API_KEY"),
                os.environ.get("LIVEKIT_API_SECRET"),
            )
        return livekit_api_ref["api"]

    # ── /token route ──────────────────────────────────────────────────────────
    @app.get("/token")
    async def token_handler(request: Request, username: str = Depends(get_token_username)):
        import sys
        is_testing = os.environ.get("TESTING") == "true"
        
        if not is_testing:
            ip = request.client.host if request.client else "127.0.0.1"
            check_token_rate_limit(ip)

        try:
            from livekit import api as lk_api
            import uuid
            import asyncio
            
            room_name = f"jarvis-room-{uuid.uuid4().hex[:8]}"

            grant = lk_api.VideoGrants(room_join=True, room=room_name)
            token = (
                lk_api.AccessToken(
                    os.environ.get("LIVEKIT_API_KEY"),
                    os.environ.get("LIVEKIT_API_SECRET"),
                )
                .with_identity(username)
                .with_name(username)
                .with_grants(grant)
            )

            async def _dispatch():
                try:
                    lk_api_client = get_livekit_api()
                    await lk_api_client.agent_dispatch.create_dispatch(
                        lk_api.CreateAgentDispatchRequest(
                            agent_name=os.environ.get("AGENT_NAME", "jarvis"),
                            room=room_name,
                        )
                    )
                except Exception as e:
                    logger.error(f"Error dispatching agent: {e}")

            # Run dispatch asynchronously in the event loop
            asyncio.create_task(_dispatch())

            return {
                "token": token.to_jwt(),
                "url": os.environ.get("LIVEKIT_URL", "ws://localhost:7880"),
            }
        except Exception as e:
            logger.exception(f"Failed to generate session token: {e}")
            raise HTTPException(status_code=500, detail="Failed to generate session token.")

    # ── Serve static files / frontend ─────────────────────────────────────────
    from fastapi.staticfiles import StaticFiles
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frontend_path = os.path.abspath(os.path.join(os.path.dirname(backend_dir), "frontend"))
    
    # Mount the static files at root
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
    
    return app

app = create_fastapi_app()
