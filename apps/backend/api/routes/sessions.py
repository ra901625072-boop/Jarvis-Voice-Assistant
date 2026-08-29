from fastapi import APIRouter, Depends, HTTPException
import asyncio
import logging
from api.middleware.auth import get_current_user
from api.dependencies import get_memory

router = APIRouter(prefix="/api/sessions", tags=["Sessions"])
logger = logging.getLogger("JARVIS.API.Sessions")

@router.get("")
async def list_sessions(
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
    memory = Depends(get_memory)
):
    try:
        sessions = await asyncio.to_thread(memory.get_recent_sessions, limit)
        return {"sessions": sessions}
    except Exception as e:
        logger.exception("Failed to list sessions")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{session_id}/transcript")
async def get_session_transcript(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    memory = Depends(get_memory)
):
    try:
        transcript = await asyncio.to_thread(memory.get_session_transcript, session_id)
        return {"session_id": session_id, "transcript": transcript}
    except Exception as e:
        logger.exception(f"Failed to get session transcript for {session_id}")
        raise HTTPException(status_code=500, detail=str(e))
