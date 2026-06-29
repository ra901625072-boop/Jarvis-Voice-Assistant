from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from api.dependencies import get_task_manager
from modules.planning.task_manager import BackgroundTaskManager
import asyncio
import logging

router = APIRouter(prefix="/api/ws", tags=["WebSockets"])
logger = logging.getLogger("JARVIS.API.WebSockets")

# Global active websocket connections
active_connections: list[WebSocket] = []

@router.websocket("/tasks")
async def global_tasks_websocket(websocket: WebSocket, tm: BackgroundTaskManager = Depends(get_task_manager)):
    await websocket.accept()
    active_connections.append(websocket)
    logger.info("New global tasks WebSocket client connected")
    
    # Send current tasks list immediately
    try:
        tasks = tm.get_all_tasks(limit=30)
        await websocket.send_json({"type": "init", "tasks": tasks})
    except Exception as e:
        logger.error(f"Failed to send initial tasks list: {e}")
        
    try:
        last_tasks_state = {}
        while True:
            # Poll for updates and push if something changed
            tasks = tm.get_all_tasks(limit=30)
            changed = False
            for t in tasks:
                t_id = t["task_id"]
                t_state = (t["status"], t["progress"], t["error"], t["result"])
                if last_tasks_state.get(t_id) != t_state:
                    changed = True
                    last_tasks_state[t_id] = t_state
            
            if changed:
                await websocket.send_json({"type": "update", "tasks": tasks})
                
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        logger.info("Global tasks WebSocket client disconnected")
    except Exception as e:
        logger.error(f"Error in global tasks WebSocket: {e}")
        if websocket in active_connections:
            active_connections.remove(websocket)

@router.websocket("/tasks/{task_id}")
async def single_task_websocket(websocket: WebSocket, task_id: str, tm: BackgroundTaskManager = Depends(get_task_manager)):
    await websocket.accept()
    logger.info(f"WebSocket monitoring task {task_id} connected")
    
    try:
        last_state = None
        while True:
            task = tm.get_task(task_id)
            if not task:
                # Check DB directly
                all_tasks = tm.get_all_tasks(limit=100)
                db_task = None
                for t in all_tasks:
                    if t["task_id"] == task_id:
                        db_task = t
                        break
                if db_task:
                    state = (db_task["status"], db_task["progress"])
                    if state != last_state:
                        await websocket.send_json(db_task)
                        last_state = state
                    if db_task["status"] in ("completed", "failed", "cancelled"):
                        break
                else:
                    await websocket.send_json({"error": f"Task {task_id} not found"})
                    break
            else:
                task_dict = task.to_dict()
                state = (task_dict["status"], task_dict["progress"])
                if state != last_state:
                    await websocket.send_json(task_dict)
                    last_state = state
                if task_dict["status"] in ("completed", "failed", "cancelled"):
                    break
                    
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        logger.info(f"WebSocket monitoring task {task_id} disconnected")
    except Exception as e:
        logger.error(f"Error in task WebSocket for {task_id}: {e}")
