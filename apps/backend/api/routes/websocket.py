from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from api.dependencies import get_task_manager
from modules.planning.task_manager import BackgroundTaskManager
from core.scheduler import PriorityTaskScheduler
from events.event_bus import EventBus
import asyncio
import logging

router = APIRouter(prefix="/api/ws", tags=["WebSockets"])
logger = logging.getLogger("JARVIS.API.WebSockets")

from api.helpers import map_os_task_to_frontend

# Global active websocket connections
active_connections: list[WebSocket] = []

async def notify_approval_pending(approval_id: str, action: str):
    """Push an approval request notification to all connected frontend clients."""
    message = {
        "type": "APPROVAL_REQUIRED",
        "approval_id": approval_id,
        "action": action,
        "message": f"Action '{action}' requires your approval."
    }
    for connection in list(active_connections):
        try:
            await connection.send_json(message)
        except Exception:
            pass

@router.websocket("/tasks")
async def global_tasks_websocket(websocket: WebSocket, tm: BackgroundTaskManager = Depends(get_task_manager)):
    await websocket.accept()
    active_connections.append(websocket)
    logger.info("New global tasks WebSocket client connected")
    
    event_queue = asyncio.Queue()
    
    async def on_task_event(event):
        await event_queue.put(event)
        
    EventBus.get_instance().subscribe("task_events", on_task_event)
    
    def get_unified_tasks():
        try:
            scheduler = PriorityTaskScheduler.get_instance()
            os_tasks = [map_os_task_to_frontend(t) for t in scheduler.list_tasks(limit=30)]
        except Exception as e:
            logger.error(f"Failed to fetch OS tasks: {e}")
            os_tasks = []
        try:
            bg_tasks = tm.get_all_tasks(limit=30)
        except Exception as e:
            logger.error(f"Failed to fetch legacy tasks: {e}")
            bg_tasks = []
        return os_tasks + bg_tasks

    # Send current tasks list immediately
    try:
        await websocket.send_json({"type": "init", "tasks": get_unified_tasks()})
    except Exception as e:
        logger.error(f"Failed to send initial tasks list: {e}")
        
    try:
        while True:
            try:
                await asyncio.wait_for(event_queue.get(), timeout=1.0)
                event_queue.task_done()
            except asyncio.TimeoutError:
                pass
                
            await websocket.send_json({"type": "update", "tasks": get_unified_tasks()})
    except WebSocketDisconnect:
        logger.info("Global tasks WebSocket client disconnected")
    except Exception as e:
        logger.error(f"Error in global tasks WebSocket: {e}")
    finally:
        if websocket in active_connections:
            active_connections.remove(websocket)
        EventBus.get_instance().unsubscribe("task_events", on_task_event)

@router.websocket("/tasks/{task_id}")
async def single_task_websocket(websocket: WebSocket, task_id: str, tm: BackgroundTaskManager = Depends(get_task_manager)):
    await websocket.accept()
    logger.info(f"WebSocket monitoring task {task_id} connected")
    
    event_queue = asyncio.Queue()
    
    async def on_task_event(event):
        if getattr(event, "task_id", None) == task_id:
            await event_queue.put(event)
            
    EventBus.get_instance().subscribe("task_events", on_task_event)
    
    def get_task_data():
        scheduler = PriorityTaskScheduler.get_instance()
        os_task = scheduler.get_task(task_id)
        if os_task:
            return map_os_task_to_frontend(os_task.to_dict())
            
        task = tm.get_task(task_id)
        if task:
            return task.to_dict()
            
        all_tasks = tm.get_all_tasks(limit=100)
        for t in all_tasks:
            if t["task_id"] == task_id:
                return t
        return None

    try:
        last_state = None
        task_data = get_task_data()
        if task_data:
            await websocket.send_json(task_data)
            last_state = (task_data["status"], task_data["progress"])
        else:
            await websocket.send_json({"error": f"Task {task_id} not found"})
            return

        while True:
            try:
                await asyncio.wait_for(event_queue.get(), timeout=0.5)
                event_queue.task_done()
            except asyncio.TimeoutError:
                pass
                
            task_data = get_task_data()
            if not task_data:
                await websocket.send_json({"error": f"Task {task_id} not found"})
                break
                
            state = (task_data["status"], task_data["progress"])
            if state != last_state:
                await websocket.send_json(task_data)
                last_state = state
                
            if task_data["status"] in ("completed", "failed", "cancelled", "done", "error"):
                break
    except WebSocketDisconnect:
        logger.info(f"WebSocket monitoring task {task_id} disconnected")
    except Exception as e:
        logger.error(f"Error in task WebSocket for {task_id}: {e}")
    finally:
        EventBus.get_instance().unsubscribe("task_events", on_task_event)
