import uuid
import time
import logging
import threading
import queue
import sqlite3
import json
import os
from enum import Enum
from datetime import datetime

logger = logging.getLogger("JARVIS.TaskManager")

class TaskStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskContext:
    def __init__(self, task_manager, task_id):
        self.task_manager = task_manager
        self.task_id = task_id

    def update_progress(self, progress: int):
        self.task_manager.update_progress(self.task_id, progress)

    def is_cancelled(self) -> bool:
        task = self.task_manager.get_task(self.task_id)
        return task is not None and task.status == TaskStatus.CANCELLED

class BackgroundTask:
    def __init__(self, task_id: str, task_type: str, func, args=None, kwargs=None, max_retries: int = 0):
        self.task_id = task_id
        self.task_type = task_type
        self.func = func
        self.args = args or ()
        self.kwargs = kwargs or {}
        
        self.created_at = datetime.now()
        self.started_at = None
        self.finished_at = None
        
        self.status = TaskStatus.QUEUED
        self.progress = 0
        self.error = None
        self.result = None
        
        self.max_retries = max_retries
        self.retry_count = 0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "progress": self.progress,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
            "result": str(self.result) if self.result is not None else None,
            "retry_count": self.retry_count
        }

class BackgroundTaskManager:
    def __init__(self, db_path: str = None, num_workers: int = 2):
        self.tasks = {}
        self.queue = queue.Queue()
        self.lock = threading.Lock()
        self.handlers = {}
        self.workers = []
        self.running = False
        self.num_workers = num_workers
        
        if db_path is None:
            db_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "tasks.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id TEXT PRIMARY KEY,
                        task_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        progress INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        error TEXT,
                        result TEXT,
                        args TEXT,
                        kwargs TEXT,
                        max_retries INTEGER DEFAULT 0,
                        retry_count INTEGER DEFAULT 0
                    )
                """)
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to initialize tasks database: {e}")
            finally:
                conn.close()

    def _db_save_task(self, task: BackgroundTask):
        conn = sqlite3.connect(self.db_path)
        try:
            try:
                serialized_result = json.dumps(task.result)
            except TypeError:
                serialized_result = json.dumps(str(task.result))
                
            conn.execute("""
                INSERT OR REPLACE INTO tasks (
                    task_id, task_type, status, progress, created_at, started_at, finished_at, error, result, args, kwargs, max_retries, retry_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id,
                task.task_type,
                task.status.value,
                task.progress,
                task.created_at.isoformat() if task.created_at else None,
                task.started_at.isoformat() if task.started_at else None,
                task.finished_at.isoformat() if task.finished_at else None,
                task.error,
                serialized_result if task.result is not None else None,
                json.dumps(task.args),
                json.dumps(task.kwargs),
                task.max_retries,
                task.retry_count
            ))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to save task {task.task_id} to database: {e}")
        finally:
            conn.close()

    def _restore_pending_tasks(self):
        conn = sqlite3.connect(self.db_path)
        restored_count = 0
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE status IN ('queued', 'running')")
            rows = cursor.fetchall()
            
            cursor.execute("PRAGMA table_info(tasks)")
            columns = [col[1] for col in cursor.fetchall()]
            
            for row in rows:
                data = dict(zip(columns, row))
                task_id = data["task_id"]
                task_type = data["task_type"]
                
                func = self.handlers.get(task_type)
                if not func:
                    logger.warning(f"Unable to restore task {task_id}: no handler registered for type '{task_type}'")
                    continue
                    
                args = json.loads(data["args"])
                kwargs = json.loads(data["kwargs"])
                max_retries = data["max_retries"]
                retry_count = data["retry_count"]
                
                task = BackgroundTask(task_id, task_type, func, args, kwargs, max_retries)
                task.retry_count = retry_count
                task.created_at = datetime.fromisoformat(data["created_at"]) if data["created_at"] else datetime.now()
                
                task.status = TaskStatus.QUEUED
                task.progress = 0
                self._db_save_task(task)
                
                self.tasks[task_id] = task
                self.queue.put(task_id)
                restored_count += 1
                
        except Exception as e:
            logger.error(f"Failed to restore pending tasks from database: {e}")
        finally:
            conn.close()
            
        if restored_count > 0:
            logger.info(f"Restored {restored_count} pending/interrupted tasks from tasks.db")

    def register_handler(self, task_type: str, func):
        with self.lock:
            self.handlers[task_type] = func
            logger.info(f"Handler registered for task type: '{task_type}'")

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            
            for i in range(self.num_workers):
                t = threading.Thread(target=self._worker_loop, name=f"JarvisTaskWorker-{i}", daemon=True)
                self.workers.append(t)
                t.start()
                
            self._restore_pending_tasks()
        logger.info("BackgroundTaskManager services started.")

    def add_task(self, task_type: str, func=None, max_retries: int = 0, args=None, kwargs=None) -> str:
        if func:
            self.register_handler(task_type, func)
            
        with self.lock:
            handler = self.handlers.get(task_type)
            if not handler:
                raise ValueError(f"No handler registered for task type: '{task_type}'")
                
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            task = BackgroundTask(task_id, task_type, handler, args, kwargs, max_retries)
            
            self.tasks[task_id] = task
            self._db_save_task(task)
            
        self.queue.put(task_id)
        logger.info(f"Task {task_id} of type '{task_type}' added to queue.")
        return task_id

    def get_task(self, task_id: str) -> BackgroundTask:
        with self.lock:
            return self.tasks.get(task_id)

    def get_all_tasks(self, limit: int = 50) -> list:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            cursor.execute("PRAGMA table_info(tasks)")
            columns = [col[1] for col in cursor.fetchall()]
            tasks_list = []
            for row in rows:
                data = dict(zip(columns, row))
                tasks_list.append(data)
            return tasks_list
        except Exception as e:
            logger.error(f"Failed to query tasks from database: {e}")
            with self.lock:
                return [t.to_dict() for t in self.tasks.values()]
        finally:
            conn.close()

    def cancel_task(self, task_id: str) -> bool:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                return False
            task.status = TaskStatus.CANCELLED
            task.finished_at = datetime.now()
            self._db_save_task(task)
            logger.info(f"Task {task_id} has been marked CANCELLED.")
            return True

    def update_progress(self, task_id: str, progress: int):
        with self.lock:
            task = self.tasks.get(task_id)
            if task and task.status == TaskStatus.RUNNING:
                task.progress = min(max(progress, 0), 100)
                self._db_save_task(task)

    def shutdown(self):
        self.running = False
        for _ in self.workers:
            self.queue.put(None)
        for t in self.workers:
            t.join(timeout=1.0)
        logger.info("BackgroundTaskManager shut down.")

    def _worker_loop(self):
        while self.running:
            try:
                task_id = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue
                
            if task_id is None:
                break
                
            task = self.get_task(task_id)
            if not task:
                self.queue.task_done()
                continue
                
            with self.lock:
                if task.status == TaskStatus.CANCELLED:
                    self.queue.task_done()
                    continue
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.now()
                self._db_save_task(task)
                
            logger.info(f"Task {task_id} started running.")
            context = TaskContext(self, task_id)
            
            try:
                result = task.func(context, *task.args, **task.kwargs)
                
                with self.lock:
                    if task.status == TaskStatus.CANCELLED:
                        self.queue.task_done()
                        continue
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.finished_at = datetime.now()
                    task.result = result
                    self._db_save_task(task)
                logger.info(f"Task {task_id} completed successfully.")
            except Exception as e:
                logger.exception(f"Error running task {task_id}: {e}")
                
                should_retry = False
                with self.lock:
                    if task.status != TaskStatus.CANCELLED:
                        if task.retry_count < task.max_retries:
                            task.retry_count += 1
                            task.status = TaskStatus.QUEUED
                            task.progress = 0
                            task.started_at = None
                            self._db_save_task(task)
                            should_retry = True
                        else:
                            task.status = TaskStatus.FAILED
                            task.finished_at = datetime.now()
                            task.error = str(e)
                            self._db_save_task(task)
                            
                if should_retry:
                    logger.info(f"Retrying task {task_id} (Attempt {task.retry_count}/{task.max_retries})")
                    self.queue.put(task_id)
                else:
                    logger.error(f"Task {task_id} failed permanently: {e}")
                    
            self.queue.task_done()
