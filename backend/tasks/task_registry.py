from tasks.worker_tasks import execute_skill_task

class CeleryTaskRegistry:
    """
    Registry mapping system skill execution calls to celery worker tasks.
    """
    @staticmethod
    def dispatch_to_celery(tool_name: str, action_name: str, args: dict):
        """Dispatch task to Celery queue and return Celery AsyncResult."""
        return execute_skill_task.delay(tool_name, action_name, args)
