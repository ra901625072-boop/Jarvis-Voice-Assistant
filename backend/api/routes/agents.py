from fastapi import APIRouter, Depends, HTTPException
from api.middleware.auth import get_current_user
from container import ServiceContainer

import logging

router = APIRouter(prefix="/api/agents", tags=["Agents"])
logger = logging.getLogger("JARVIS.API.Agents")

@router.get("")
async def list_agents(current_user: dict = Depends(get_current_user)):
    try:
        container = ServiceContainer.instance()
        tools = container.get("tools") if container else []
        

        agents_list = []
        for tool in tools:
            # Determine name and type
            tool_name = tool.__class__.__name__
            tool_desc = getattr(tool, "__doc__", "") or "No description available"
            # Cleanup docstring whitespace
            tool_desc = " ".join(tool_desc.split())
            agents_list.append({
                "name": tool_name,
                "description": tool_desc,
                "status": "idle",
                "capabilities": [getattr(f, "_wrapped", f).__name__ for f in getattr(tool, "_actions", {}).values()] if hasattr(tool, "_actions") else []
            })
            
        return {"agents": agents_list}
    except Exception as e:
        logger.exception("Failed to list agents")
        raise HTTPException(status_code=500, detail=str(e))
