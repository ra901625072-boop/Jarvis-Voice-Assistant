from tasks.celery_app import celery_app
import logging
import asyncio

logger = logging.getLogger("JARVIS.CeleryWorkers")

# Lazy container initialization for the worker process
_worker_container = None

def get_worker_container():
    global _worker_container
    if _worker_container is None:
        from container import build_container
        _worker_container = build_container()
        
        # Start startup inside an event loop
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_worker_container.startup())
        finally:
            loop.close()
    return _worker_container

@celery_app.task(bind=True)
def execute_skill_task(self, tool_name: str, action_name: str, args: dict):
    logger.info(f"Celery task received: execute {tool_name} -> {action_name} with args {args}")
    container = get_worker_container()
    tools = container.get("tools")
    
    # Find matching tool
    target_tool = None
    for t in tools:
        if t.__class__.__name__.lower() == tool_name.lower():
            target_tool = t
            break
            
    if not target_tool:
        raise ValueError(f"Tool {tool_name} not found in container tools")
        
    # Dispatch execution using ExecutionEngine
    from modules.execution.execution_engine import ExecutionEngine
    engine = ExecutionEngine(tools)
    
    # Run async function in a clean event loop
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(engine.dispatch(action_name, args))
        logger.info(f"Celery task execution success: result = {res}")
        return res
    except Exception as e:
        logger.error(f"Celery task execution failed: {e}")
        raise e
    finally:
        loop.close()
