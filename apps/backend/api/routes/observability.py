from fastapi import APIRouter, Depends
from api.middleware.auth import get_current_user
from modules.observability.trace_store import TraceStore

router = APIRouter(prefix="/api/observability", tags=["Observability"])

def get_trace_store() -> TraceStore:
    from container import ServiceContainer
    container = ServiceContainer.instance()
    if container:
        try:
            return container.get("trace_store")
        except KeyError:
            pass
    return TraceStore()

@router.get("/metrics")
async def get_metrics(current_user=Depends(get_current_user), ts=Depends(get_trace_store)):
    return ts.get_metrics()

@router.get("/spans")
async def get_spans(limit: int = 100, current_user=Depends(get_current_user), ts=Depends(get_trace_store)):
    return {"spans": ts.get_recent(limit)}

@router.get("/agents")
async def agent_breakdown(current_user=Depends(get_current_user), ts=Depends(get_trace_store)):
    return {"agents": ts.get_agent_breakdown()}
