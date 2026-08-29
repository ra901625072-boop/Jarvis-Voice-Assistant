from container import ServiceContainer

def get_task_manager():
    container = ServiceContainer.instance()
    if container:
        # Check if Celery is enabled, or get BackgroundTaskManager
        # For compatibility with Phase 2 we will wire Celery as well.
        return container.get_or_none("task_manager")
    
    # Fallback to importing and returning
    from modules.planning.task_manager import BackgroundTaskManager
    return BackgroundTaskManager()

def get_security_manager():
    container = ServiceContainer.instance()
    if container:
        return container.get("security")
    from modules.security.manager import SecurityManager
    return SecurityManager()

def get_memory():
    container = ServiceContainer.instance()
    if container:
        return container.get_or_none("memory")
    from modules.memory.manager import MemoryManager
    return MemoryManager()
