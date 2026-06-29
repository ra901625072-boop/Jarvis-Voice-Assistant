from fastapi import APIRouter, Depends, HTTPException
from api.middleware.auth import get_current_user
import os
import json
import logging

router = APIRouter(prefix="/api/schedules", tags=["Schedules"])
logger = logging.getLogger("JARVIS.API.Schedules")

SCHEDULES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "database", "schedules.json"
)

def load_schedules():
    if not os.path.exists(SCHEDULES_FILE):
        return {}
    try:
        with open(SCHEDULES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to load schedules")
        return {}

def save_schedules(schedules):
    try:
        os.makedirs(os.path.dirname(SCHEDULES_FILE), exist_ok=True)
        with open(SCHEDULES_FILE, "w", encoding="utf-8") as f:
            json.dump(schedules, f, indent=4)
        return True
    except Exception:
        logger.exception("Failed to save schedules")
        return False

@router.get("")
async def list_schedules(current_user: dict = Depends(get_current_user)):
    return {"schedules": list(load_schedules().values())}

@router.post("")
async def create_schedule(body: dict, current_user: dict = Depends(get_current_user)):
    s_id = body.get("id")
    name = body.get("name")
    cron_expr = body.get("cron")
    workflow_id = body.get("workflow_id")
    
    if not name or not cron_expr or not workflow_id:
        raise HTTPException(status_code=400, detail="Missing required fields: name, cron, workflow_id")
        
    if not s_id:
        import uuid
        s_id = f"sch_{uuid.uuid4().hex[:8]}"
        body["id"] = s_id
        
    schedules = load_schedules()
    schedules[s_id] = body
    if save_schedules(schedules):
        return {"status": "success", "schedule": body}
    raise HTTPException(status_code=500, detail="Failed to write schedule database")

@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str, current_user: dict = Depends(get_current_user)):
    schedules = load_schedules()
    if schedule_id not in schedules:
        raise HTTPException(status_code=404, detail="Schedule not found")
    del schedules[schedule_id]
    if save_schedules(schedules):
        return {"status": "success", "message": f"Deleted schedule {schedule_id}"}
    raise HTTPException(status_code=500, detail="Failed to write schedule database")
