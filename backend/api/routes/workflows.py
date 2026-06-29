from fastapi import APIRouter, Depends, HTTPException
from api.middleware.auth import get_current_user
import os
import json
import logging

router = APIRouter(prefix="/api/workflows", tags=["Workflows"])
logger = logging.getLogger("JARVIS.API.Workflows")

WORKFLOWS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "database", "workflows.json"
)

def load_workflows():
    if not os.path.exists(WORKFLOWS_FILE):
        return {}
    try:
        with open(WORKFLOWS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to load workflows")
        return {}

def save_workflows(workflows):
    try:
        os.makedirs(os.path.dirname(WORKFLOWS_FILE), exist_ok=True)
        with open(WORKFLOWS_FILE, "w", encoding="utf-8") as f:
            json.dump(workflows, f, indent=4)
        return True
    except Exception:
        logger.exception("Failed to save workflows")
        return False

@router.get("")
async def list_workflows(current_user: dict = Depends(get_current_user)):
    return {"workflows": list(load_workflows().values())}

@router.post("")
async def create_workflow(body: dict, current_user: dict = Depends(get_current_user)):
    w_id = body.get("id")
    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Missing 'name'")
    if not w_id:
        import uuid
        w_id = f"wf_{uuid.uuid4().hex[:8]}"
        body["id"] = w_id
        
    workflows = load_workflows()
    workflows[w_id] = body
    if save_workflows(workflows):
        return {"status": "success", "workflow": body}
    raise HTTPException(status_code=500, detail="Failed to write workflow database")

@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str, current_user: dict = Depends(get_current_user)):
    workflows = load_workflows()
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflows[workflow_id]

@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str, current_user: dict = Depends(get_current_user)):
    workflows = load_workflows()
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")
    del workflows[workflow_id]
    if save_workflows(workflows):
        return {"status": "success", "message": f"Deleted workflow {workflow_id}"}
    raise HTTPException(status_code=500, detail="Failed to write workflow database")

@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: str,
    current_user: dict = Depends(get_current_user)
):
    workflows = load_workflows()
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    # In a full multi-agent setup, we execute the DAG of workflow steps
    # For now, let's submit a task to TaskManager to execute the workflow
    from api.dependencies import get_task_manager
    tm = get_task_manager()
    
    wf = workflows[workflow_id]
    steps = wf.get("steps", [])
    
    async def execute_steps(context):
        context.update_progress(0)
        total = len(steps)
        for idx, step in enumerate(steps):
            # Run step
            # Log & simulate step execution
            import asyncio
            await asyncio.sleep(1.0)
            context.update_progress(int(((idx + 1) / total) * 100))
        return f"Executed workflow {wf['name']} with {total} steps successfully."

    def sync_wrapper(context, *args, **kwargs):
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(execute_steps(context))
        finally:
            loop.close()

    task_id = tm.add_task(
        task_type="workflow_execution",
        func=sync_wrapper,
        kwargs={"workflow_id": workflow_id}
    )
    return {"task_id": task_id, "status": "queued"}
