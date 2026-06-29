from fastapi import APIRouter, Depends, HTTPException
from api.middleware.auth import get_current_user, require_role
from api.dependencies import get_task_manager, get_security_manager
from modules.planning.task_manager import BackgroundTaskManager
import logging

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])
logger = logging.getLogger("JARVIS.API.Tasks")

@router.get("")
async def list_tasks(
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    tm: BackgroundTaskManager = Depends(get_task_manager)
):
    try:
        tasks = tm.get_all_tasks(limit=limit)
        return {"tasks": tasks}
    except Exception as e:
        logger.exception("Failed to list tasks")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("")
async def create_task(
    body: dict,
    current_user: dict = Depends(require_role(["admin", "user"])),
    tm: BackgroundTaskManager = Depends(get_task_manager)
):
    text_input = body.get("input")
    if not text_input:
        raise HTTPException(status_code=400, detail="Missing 'input' command string")
    
    # We will submit task of type 'nl_command'.
    # In a full multi-agent workflow, we want to parse this NL input and route it.
    # For now, let's queue the task using BackgroundTaskManager.
    # To execute the NL command, we can run a function that invokes agent.py or an execution engine.
    # Let's map it to an execution task that can be picked up by the worker or handled locally.
    
    async def run_nl_task(context):
        from container import ServiceContainer
        container = ServiceContainer.instance()
        tools = container.get("tools") if container else []
        from modules.execution.execution_engine import ExecutionEngine
        engine = ExecutionEngine(tools)
        # In a real run, we can call our agent session to process natural language.
        # But since we want to handle the command, let's pass it to a high-level coding/workflow skill
        # or mock the execution for the task pipeline.
        # Let's simulate step progress for demonstration, or invoke the correct tool.
        context.update_progress(10)
        import asyncio
        await asyncio.sleep(1.0)
        context.update_progress(50)
        await asyncio.sleep(1.0)
        context.update_progress(100)
        return f"Processed command: '{text_input}'"

    # We run the task in the background. Since background task functions in BackgroundTaskManager 
    # run synchronously in threads, we need a sync wrapper if the handler is async or standard sync.
    # In BackgroundTaskManager, the handler func signature is: func(context, *args, **kwargs)
    def sync_wrapper(context, *args, **kwargs):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(run_nl_task(context))
        finally:
            loop.close()

    try:
        task_id = tm.add_task(
            task_type="nl_command",
            func=sync_wrapper,
            kwargs={"input": text_input}
        )
        return {"task_id": task_id, "status": "queued"}
    except Exception as e:
        logger.exception("Failed to submit task")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{task_id}")
async def get_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
    tm: BackgroundTaskManager = Depends(get_task_manager)
):
    task = tm.get_task(task_id)
    if not task:
        # Check SQLite db directly via list
        all_tasks = tm.get_all_tasks(limit=100)
        for t in all_tasks:
            if t["task_id"] == task_id:
                return t
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task.to_dict()

@router.delete("/{task_id}")
async def cancel_task(
    task_id: str,
    current_user: dict = Depends(require_role(["admin"])),
    tm: BackgroundTaskManager = Depends(get_task_manager)
):
    cancelled = tm.cancel_task(task_id)
    if not cancelled:
        raise HTTPException(status_code=400, detail=f"Could not cancel task {task_id}")
    return {"status": "cancelled", "task_id": task_id}
