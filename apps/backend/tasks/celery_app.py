import os
from celery import Celery

REDIS_URL = os.environ.get("JARVIS_REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "jarvis",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.worker_tasks"]
)

# Optional configurations
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600, # 1 hour max limit
)

if __name__ == "__main__":
    celery_app.start()
