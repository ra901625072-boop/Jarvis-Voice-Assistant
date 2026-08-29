from fastapi import APIRouter, Depends, HTTPException
from api.middleware.auth import get_current_user, require_role
from api.dependencies import get_task_manager
from modules.planning.task_manager import BackgroundTaskManager
from core.orchestrator import MasterOrchestrator
from core.scheduler import PriorityTaskScheduler
import logging
from api.helpers import map_os_task_to_frontend

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])
logger = logging.getLogger("JARVIS.API.Tasks")

@router.get("")
async def list_tasks(
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    tm: BackgroundTaskManager = Depends(get_task_manager)
):
    try:
        # Fetch from PriorityTaskScheduler (Multi-Agent OS tasks)
        scheduler = PriorityTaskScheduler.get_instance()
        os_tasks = [map_os_task_to_frontend(t) for t in scheduler.list_tasks(limit=limit)]
        
        # Also fetch legacy background tasks if any
        bg_tasks = tm.get_all_tasks(limit=limit)

        return {
            "tasks": os_tasks + bg_tasks,
            "legacy_tasks": bg_tasks
        }
    except Exception as e:
        logger.exception("Failed to list tasks")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
async def create_task(
    body: dict,
    current_user: dict = Depends(require_role(["admin", "user"]))
):
    text_input = body.get("input")
    if not text_input:
        raise HTTPException(status_code=400, detail="Missing 'input' command string")
    
    try:
        orchestrator = MasterOrchestrator.get_instance()
        created_records = await orchestrator.handle_user_intent(text_input, origin="api")
        
        return {
            "status": "queued",
            "count": len(created_records),
            "tasks": [map_os_task_to_frontend(r.to_dict()) for r in created_records]
        }
    except Exception as e:
        logger.exception("Failed to submit task to MasterOrchestrator")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{task_id}")
async def get_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    tm: BackgroundTaskManager = Depends(get_task_manager)
):
    scheduler = PriorityTaskScheduler.get_instance()
    task_record = scheduler.get_task(task_id)
    if task_record:
        return map_os_task_to_frontend(task_record.to_dict())

    # Fallback to legacy task manager
    legacy_task = tm.get_task(task_id)
    if legacy_task:
        return legacy_task.to_dict()

    raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

@router.post("/{task_id}/cancel")
@router.delete("/{task_id}")
async def cancel_task(
    task_id: str,
    current_user: dict = Depends(require_role(["admin", "user"])),
    tm: BackgroundTaskManager = Depends(get_task_manager)
):
    scheduler = PriorityTaskScheduler.get_instance()
    cancelled = await scheduler.cancel_task(task_id)
    
    if not cancelled:
        cancelled = tm.cancel_task(task_id)

    if not cancelled:
        raise HTTPException(status_code=400, detail=f"Could not cancel task {task_id}")
    return {"status": "cancelled", "task_id": task_id}

@router.post("/{task_id}/pause")
async def pause_task(
    task_id: str,
    current_user: dict = Depends(require_role(["admin", "user"]))
):
    scheduler = PriorityTaskScheduler.get_instance()
    paused = await scheduler.pause_task(task_id)
    if not paused:
        raise HTTPException(status_code=400, detail=f"Could not pause task {task_id}")
    return {"status": "paused", "task_id": task_id}

@router.post("/{task_id}/resume")
async def resume_task(
    task_id: str,
    current_user: dict = Depends(require_role(["admin", "user"]))
):
    scheduler = PriorityTaskScheduler.get_instance()
    resumed = await scheduler.resume_task(task_id)
    if not resumed:
        raise HTTPException(status_code=400, detail=f"Could not resume task {task_id}")
    return {"status": "resumed", "task_id": task_id}
