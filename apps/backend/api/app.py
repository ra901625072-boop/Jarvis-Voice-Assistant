from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
import os
import psutil
import logging

from api.middleware.auth import get_current_user
from api.dependencies import get_security_manager
from modules.core.hardware_stats import get_cpu_temperature

# Configure logger
logger = logging.getLogger("JARVIS.API.App")

def create_fastapi_app() -> FastAPI:
    # Initialize SQLAlchemy database tables
    try:
        from domain.repositories.database import engine, Base
        import domain.entities.models # Register models
        Base.metadata.create_all(bind=engine)
        logger.info("SQLAlchemy database tables initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database tables: {e}")

    app = FastAPI(
        title="JARVIS API",
        description="REST & WebSocket API for JARVIS Multi-Agent System",
        version="2.0"
    )
    
    # Enable CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Authentication / JWT generation
    @app.post("/api/auth/token")
    async def login(body: dict, security_mgr = Depends(get_security_manager)):
        key = body.get("api_key")
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
        return {"token": token}

    # Hardware stats
    @app.get("/api/stats")
    async def stats_handler(current_user: dict = Depends(get_current_user)):
        cpu_percent = psutil.cpu_percent(interval=0)
        temp = get_cpu_temperature()
        source = "hardware" if temp is not None else "unavailable"
        return {"cpu": cpu_percent, "temp": temp, "temp_source": source}

    # Include routers
    from api.routes.tasks import router as tasks_router
    from api.routes.agents import router as agents_router
    from api.routes.workflows import router as workflows_router
    from api.routes.schedules import router as schedules_router
    from api.routes.websocket import router as ws_router
    from api.routes.notifications import router as notifications_router

    app.include_router(tasks_router)
    app.include_router(agents_router)
    app.include_router(workflows_router)
    app.include_router(schedules_router)
    app.include_router(ws_router)
    app.include_router(notifications_router)
    
    return app

app = create_fastapi_app()
