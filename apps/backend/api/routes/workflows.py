from fastapi import APIRouter, Depends, HTTPException, Body
from api.middleware.auth import get_current_user
import os
import json
import logging
from modules.skills.markdown_loader import parse_markdown, validate_workflow, parse_workflow_steps

router = APIRouter(prefix="/api/workflows", tags=["Workflows"])
logger = logging.getLogger("JARVIS.API.Workflows")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOWS_FILE = os.path.join(BACKEND_DIR, "database", "workflows.json")
CUSTOM_WORKFLOWS_DIR = os.path.join(BACKEND_DIR, "database", "custom_workflows")

def migrate_legacy_workflows():
    if os.path.exists(WORKFLOWS_FILE):
        try:
            with open(WORKFLOWS_FILE, "r", encoding="utf-8") as f:
                legacy_workflows = json.load(f)
            if isinstance(legacy_workflows, dict) and legacy_workflows:
                os.makedirs(CUSTOM_WORKFLOWS_DIR, exist_ok=True)
                for w_id, w_data in legacy_workflows.items():
                    w_file = os.path.join(CUSTOM_WORKFLOWS_DIR, f"{w_id}.json")
                    with open(w_file, "w", encoding="utf-8") as wf:
                        json.dump(w_data, wf, indent=4)
                logger.info(f"Successfully migrated {len(legacy_workflows)} workflows from workflows.json to custom_workflows/ directory.")
            # Rename or delete legacy file
            try:
                os.remove(WORKFLOWS_FILE)
            except Exception as e:
                logger.warning(f"Failed to remove legacy workflows.json file: {e}")
        except Exception as e:
            logger.exception(f"Failed to migrate legacy workflows: {e}")

def load_workflows():
    # Run migration if needed
    migrate_legacy_workflows()
    
    if not os.path.exists(CUSTOM_WORKFLOWS_DIR):
        return {}
        
    workflows = {}
    try:
        for fname in os.listdir(CUSTOM_WORKFLOWS_DIR):
            if fname.startswith("wf_") and fname.endswith(".json"):
                fpath = os.path.join(CUSTOM_WORKFLOWS_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        w_data = json.load(f)
                        w_id = w_data.get("id") or fname[:-5]
                        workflows[w_id] = w_data
                except Exception as e:
                    logger.error(f"Failed to load workflow file {fname}: {e}")
    except Exception as e:
        logger.exception("Failed to scan custom_workflows directory")
    return workflows

def save_workflows(workflows):
    try:
        os.makedirs(CUSTOM_WORKFLOWS_DIR, exist_ok=True)
        # Identify current workflow files in directory to handle deletions
        existing_files = set()
        if os.path.exists(CUSTOM_WORKFLOWS_DIR):
            for fname in os.listdir(CUSTOM_WORKFLOWS_DIR):
                if fname.startswith("wf_") and fname.endswith(".json"):
                    existing_files.add(fname)
                    
        # Save all workflows in the passed dictionary
        for w_id, w_data in workflows.items():
            fname = f"{w_id}.json"
            fpath = os.path.join(CUSTOM_WORKFLOWS_DIR, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(w_data, f, indent=4)
            if fname in existing_files:
                existing_files.remove(fname)
                
        # Any file left in existing_files should be deleted (since it was removed from the workflows dictionary)
        for fname in existing_files:
            try:
                os.remove(os.path.join(CUSTOM_WORKFLOWS_DIR, fname))
            except Exception as e:
                logger.warning(f"Failed to delete removed workflow file {fname}: {e}")
                
        return True
    except Exception as e:
        logger.exception("Failed to save workflows")
        return False

@router.get("")
async def list_workflows(current_user: dict = Depends(get_current_user)):
    username = current_user.get("username") or current_user.get("sub")
    all_wfs = load_workflows()
    filtered_wfs = []
    for wf in all_wfs.values():
        if not wf.get("owner") or wf.get("owner") == username:
            filtered_wfs.append(wf)
    return {"workflows": filtered_wfs}

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
        
    body["owner"] = current_user.get("username") or current_user.get("sub")
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
    wf = workflows[workflow_id]
    username = current_user.get("username") or current_user.get("sub")
    if wf.get("owner") and wf.get("owner") != username:
        raise HTTPException(status_code=403, detail="You do not own this workflow")
    return wf

@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str, current_user: dict = Depends(get_current_user)):
    workflows = load_workflows()
    wf = workflows[workflow_id]
    if wf.get("owner") and wf.get("owner") != current_user.get("username"):
        raise HTTPException(status_code=403, detail="You do not own this workflow")
    del workflows[workflow_id]
    if save_workflows(workflows):
        # Clean up associated schedules
        try:
            from api.routes.schedules import load_schedules, save_schedules
            schedules = load_schedules()
            schedules_to_del = [sid for sid, s in schedules.items() if s.get("workflow_id") == workflow_id]
            if schedules_to_del:
                for sid in schedules_to_del:
                    del schedules[sid]
                save_schedules(schedules)
        except Exception as se:
            logger.error(f"Failed to clean up schedules for deleted workflow {workflow_id}: {se}")
            
        return {"status": "success", "message": f"Deleted workflow {workflow_id}"}
    raise HTTPException(status_code=500, detail="Failed to write workflow database")

@router.post("/{workflow_id}/run")
async def run_workflow(
    workflow_id: str,
    current_user: dict = Depends(get_current_user)
):
    workflows = load_workflows()
    wf = workflows[workflow_id]
    if wf.get("owner") and wf.get("owner") != current_user.get("username"):
        raise HTTPException(status_code=403, detail="You do not own this workflow")
    
    # In a full multi-agent setup, we execute the DAG of workflow steps
    # For now, let's submit a task to TaskManager to execute the workflow
    from api.dependencies import get_task_manager
    tm = get_task_manager()
    
    wf = workflows[workflow_id]
    steps = wf.get("steps", [])
    
    async def execute_steps(context):
        from container import ServiceContainer
        container = ServiceContainer.instance()
        if not container:
            raise RuntimeError("Service container not available")
            
        agent_bus = container.get("agent_bus")
        import uuid
        from ai.agents.types import AgentTask
        
        context.update_progress(0)
        total = len(steps)
        for idx, step in enumerate(steps):
            agent_name = step.get("agent", "execution_agent")
            target_agent = agent_name.lower().strip()
            # If the user specified e.g. "CodingAgent" or "coding", normalize to "coding_agent"
            if not target_agent.endswith("_agent"):
                target_agent = f"{target_agent}_agent"
                
            task_type = step.get("action", "execute_command")
            payload = step.get("payload", step.get("args", {}))
            
            step_task = AgentTask(
                task_id=str(uuid.uuid4()),
                task_type=task_type,
                payload=payload,
                origin_agent="workflow_api",
                target_agent=target_agent
            )
            res = await agent_bus.dispatch(step_task)
            if not res.success:
                raise RuntimeError(res.error or f"Workflow step {idx+1} ({step.get('name', task_type)}) failed.")
            context.update_progress(int(((idx + 1) / total) * 100))
        return f"Executed workflow {wf['name']} with {total} steps successfully."

    from api.helpers import run_coroutine_sync

    def sync_wrapper(context, *args, **kwargs):
        return run_coroutine_sync(execute_steps, context)

    task_id = tm.add_task(
        task_type="workflow_execution",
        func=sync_wrapper,
        kwargs={"workflow_id": workflow_id},
        label=f"Workflow Execution: {wf.get('name', workflow_id)}",
        announce=True,
        priority="normal"
    )
    return {"task_id": task_id, "status": "queued"}


@router.post("/validate-md")
async def validate_markdown_workflow(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    raw_markdown = body.get("raw_markdown", "")
    if not raw_markdown:
        raise HTTPException(status_code=400, detail="Missing 'raw_markdown'")
        
    parsed = parse_markdown(raw_markdown)
    ok, errors = validate_workflow(parsed)
    metadata = parsed.get("metadata", {})
    steps = []
    if ok:
        steps, step_errors = parse_workflow_steps(parsed.get("body", ""))
        
    return {
        "valid": ok,
        "errors": errors,
        "metadata": metadata,
        "steps": steps
    }


@router.post("/import-md")
async def import_markdown_workflow(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    raw_markdown = body.get("raw_markdown", "")
    if not raw_markdown:
        raise HTTPException(status_code=400, detail="Missing 'raw_markdown'")
        
    parsed = parse_markdown(raw_markdown)
    ok, errors = validate_workflow(parsed)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Validation failed: {', '.join(errors)}")
        
    metadata = parsed.get("metadata", {})
    name = metadata.get("name")
    description = metadata.get("description", "")
    schedule_cron = metadata.get("schedule")
    
    steps, step_errors = parse_workflow_steps(parsed.get("body", ""))
    if step_errors:
        raise HTTPException(status_code=400, detail=f"Failed to parse steps: {', '.join(step_errors)}")
        
    import uuid
    workflow_id = f"wf_{uuid.uuid4().hex[:8]}"
    
    workflow = {
        "id": workflow_id,
        "name": name,
        "description": description,
        "steps": steps,
        "source": "markdown",
        "raw_markdown": raw_markdown,
        "owner": current_user.get("username")
    }
    
    # Save workflow in workflows.json
    workflows = load_workflows()
    workflows[workflow_id] = workflow
    if not save_workflows(workflows):
        raise HTTPException(status_code=500, detail="Failed to write workflow database")
        
    # Auto-register schedule if provided in markdown metadata
    if schedule_cron:
        try:
            from api.routes.schedules import load_schedules, save_schedules
            schedules = load_schedules()
            
            sch_id = f"sch_{uuid.uuid4().hex[:8]}"
            schedules[sch_id] = {
                "id": sch_id,
                "name": f"Cron: {name}",
                "cron": schedule_cron,
                "workflow_id": workflow_id
            }
            save_schedules(schedules)
        except Exception as se:
            logger.error(f"Failed to auto-register schedule for workflow {workflow_id}: {se}")
            
    return {"status": "success", "workflow": workflow}
