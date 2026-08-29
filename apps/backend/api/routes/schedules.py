from fastapi import APIRouter, Depends, HTTPException
from api.middleware.auth import get_current_user
import os
import json
import logging
import threading

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


# ── Background Cron Scheduler ──────────────────────────────────────────────────

def match_cron_field(field: str, value: int) -> bool:
    if field == '*':
        return True
    for part in field.split(','):
        if '/' in part:
            val_range, step = part.split('/')
            step = int(step)
            if val_range == '*':
                if value % step == 0:
                    return True
            elif '-' in val_range:
                start, end = map(int, val_range.split('-'))
                if start <= value <= end and (value - start) % step == 0:
                    return True
            else:
                start = int(val_range)
                if value >= start and (value - start) % step == 0:
                    return True
        elif '-' in part:
            start, end = map(int, part.split('-'))
            if start <= value <= end:
                return True
        else:
            if part.isdigit() and int(part) == value:
                return True
    return False

def cron_matches(cron_expr: str, dt) -> bool:
    fields = cron_expr.split()
    if len(fields) != 5:
        return False
    min_match = match_cron_field(fields[0], dt.minute)
    hour_match = match_cron_field(fields[1], dt.hour)
    day_match = match_cron_field(fields[2], dt.day)
    month_match = match_cron_field(fields[3], dt.month)
    python_weekday = dt.isoweekday()  # 1 (Mon) - 7 (Sun)
    day_of_week_match = match_cron_field(fields[4], python_weekday) or (python_weekday == 7 and match_cron_field(fields[4], 0))
    return min_match and hour_match and day_match and month_match and day_of_week_match

def trigger_workflow_execution(workflow_id: str):
    try:
        from api.routes.workflows import load_workflows
        from api.dependencies import get_task_manager
        
        workflows = load_workflows()
        if workflow_id not in workflows:
            logger.error(f"Scheduled workflow {workflow_id} not found.")
            return
            
        wf = workflows[workflow_id]
        steps = wf.get("steps", [])
        
        async def execute_steps(context):
            context.update_progress(0)
            total = len(steps)
            for idx, step in enumerate(steps):
                import asyncio
                await asyncio.sleep(1.0)
                context.update_progress(int(((idx + 1) / total) * 100))
        from api.helpers import run_coroutine_sync

        def sync_wrapper(context, *args, **kwargs):
            return run_coroutine_sync(execute_steps, context)

        tm = get_task_manager()
        task_id = tm.add_task(
            task_type="workflow_execution",
            func=sync_wrapper,
            kwargs={"workflow_id": workflow_id},
            label=f"Workflow Execution (Scheduled): {wf.get('name', workflow_id)}",
            announce=True,
            priority="normal"
        )
        logger.info(f"Triggered scheduled workflow task {task_id} for workflow {workflow_id}")
    except Exception as e:
        logger.error(f"Failed to trigger scheduled workflow {workflow_id}: {e}", exc_info=True)

def run_schedules_loop():
    import time
    from datetime import datetime
    logger.info("Background Cron Scheduler loop started.")
    while True:
        try:
            now_sec = time.time()
            sleep_time = 60.0 - (now_sec % 60.0)
            time.sleep(sleep_time)
            
            dt = datetime.now()
            schedules = load_schedules()
            for sch in schedules.values():
                cron_expr = sch.get("cron")
                wf_id = sch.get("workflow_id")
                if cron_expr and wf_id:
                    if cron_matches(cron_expr, dt):
                        logger.info(f"Cron match found: Schedule '{sch.get('name')}' ({cron_expr}) matches current time {dt}. Triggering workflow {wf_id}")
                        threading.Thread(target=trigger_workflow_execution, args=(wf_id,), daemon=True).start()
        except Exception as e:
            logger.error(f"Error in background cron scheduler loop: {e}", exc_info=True)
            time.sleep(10)

import sys
if "pytest" not in sys.modules and "PYTEST_CURRENT_TEST" not in os.environ:
    threading.Thread(target=run_schedules_loop, daemon=True, name="JarvisSchedulesLoop").start()

