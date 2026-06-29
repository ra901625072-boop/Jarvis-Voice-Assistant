"""
modules/execution/unified_task_registry.py — Single source of truth for all background tasks.

Replaces the dual-system problem where:
  - BackgroundTaskManager (thread pool + SQLite) handled file move/copy.
  - ExecutiveController.active_tasks (in-memory dict + asyncio.create_task) handled
    background tool launches.

UnifiedTaskRegistry provides:
  - create_task()    — Queue any task (thread or asyncio) and return a task ID.
  - get_task()       — Get a TaskRecord by ID.
  - list_tasks()     — List recent tasks.
  - cancel_task()    — Cancel a running or queued task.
  - update_status()  — Update status/progress/result/error.
  - shutdown()       — Graceful teardown.
"""
import asyncio
import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("JARVIS.TaskRegistry")


# ── Data model ────────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskRecord:
    task_id: str
    task_type: str
    status: TaskStatus = TaskStatus.QUEUED
    progress: int = 0
    description: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# ── Registry ──────────────────────────────────────────────────────────────────

class UnifiedTaskRegistry:
    """
    Single source of truth for all JARVIS background tasks.

    Thread tasks  → persisted in SQLite, executed in a thread-pool worker.
    Asyncio tasks → in-memory with SQLite status mirror.

    Public API is identical regardless of task type.
    """

    _instance: Optional["UnifiedTaskRegistry"] = None
    _singleton_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._singleton_lock:
            if cls._instance is None:
                obj = super().__new__(cls)
                obj._initialized = False
                cls._instance = obj
            return cls._instance

    def __init__(self, db_path: str = None, num_workers: int = 2):
        if getattr(self, "_initialized", False):
            return

        import os
        if db_path is None:
            db_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "..",
                "database",
            )
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "unified_tasks.db")

        self._db_path = db_path
        self._lock = threading.Lock()
        self._records: Dict[str, TaskRecord] = {}
        self._asyncio_tasks: Dict[str, asyncio.Task] = {}
        self._handlers: Dict[str, Callable] = {}
        self._queue: "queue.Queue" = __import__("queue").Queue()
        self._running = True
        self._workers: List[threading.Thread] = []

        self._init_db()
        self._start_workers(num_workers)
        self._initialized = True
        logger.info("UnifiedTaskRegistry initialized.")

    # ── DB ────────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id      TEXT PRIMARY KEY,
                    task_type    TEXT NOT NULL,
                    status       TEXT NOT NULL,
                    progress     INTEGER DEFAULT 0,
                    description  TEXT DEFAULT '',
                    created_at   REAL NOT NULL,
                    started_at   REAL,
                    finished_at  REAL,
                    result       TEXT,
                    error        TEXT
                )
            """)
            conn.commit()

    def _save(self, rec: TaskRecord) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO tasks
                        (task_id, task_type, status, progress, description,
                         created_at, started_at, finished_at, result, error)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (
                    rec.task_id, rec.task_type, rec.status.value, rec.progress,
                    rec.description, rec.created_at, rec.started_at, rec.finished_at,
                    rec.result, rec.error,
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save task {rec.task_id}: {e}")

    # ── Worker pool ───────────────────────────────────────────────────────────

    def _start_workers(self, n: int) -> None:
        for i in range(n):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"JarvisTaskWorker-{i}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)

    def _worker_loop(self) -> None:
        import queue as q
        while self._running:
            try:
                task_id = self._queue.get(timeout=1.0)
            except q.Empty:
                continue
            if task_id is None:
                break

            with self._lock:
                rec = self._records.get(task_id)
                handler = self._handlers.get(rec.task_type) if rec else None
                if not rec or not handler or rec.status == TaskStatus.CANCELLED:
                    self._queue.task_done()
                    continue
                rec.status = TaskStatus.RUNNING
                rec.started_at = time.time()
            self._save(rec)

            try:
                result = handler(task_id, rec)
                with self._lock:
                    rec.status = TaskStatus.COMPLETED
                    rec.progress = 100
                    rec.finished_at = time.time()
                    rec.result = str(result) if result is not None else None
            except Exception as e:
                with self._lock:
                    rec.status = TaskStatus.FAILED
                    rec.finished_at = time.time()
                    rec.error = str(e)
                logger.error(f"Task {task_id} failed: {e}")
            finally:
                self._save(rec)
                self._queue.task_done()

    # ── Public API ────────────────────────────────────────────────────────────

    def register_handler(self, task_type: str, handler: Callable) -> None:
        """Register a thread-pool handler for a given task type."""
        with self._lock:
            self._handlers[task_type] = handler

    def create_task(
        self,
        task_type: str,
        description: str = "",
        handler: Callable = None,
        asyncio_coro=None,
        loop: asyncio.AbstractEventLoop = None,
    ) -> str:
        """
        Create and enqueue a new task.

        Provide either:
          handler=    for thread-pool tasks  (called as handler(task_id, rec))
          asyncio_coro= for asyncio tasks    (an awaitable)

        Returns the task_id.
        """
        task_id = f"task_{uuid.uuid4().hex[:10]}"
        rec = TaskRecord(task_id=task_id, task_type=task_type, description=description)

        if handler:
            self.register_handler(task_type, handler)

        with self._lock:
            self._records[task_id] = rec

        self._save(rec)

        if asyncio_coro is not None:
            # Asyncio path — schedule in the provided loop
            if loop is None:
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    pass

            if loop:
                task = loop.create_task(self._wrap_async(task_id, rec, asyncio_coro))
                with self._lock:
                    self._asyncio_tasks[task_id] = task
            else:
                logger.error(f"No event loop available for asyncio task {task_id}")
        else:
            self._queue.put(task_id)

        return task_id

    async def _wrap_async(self, task_id: str, rec: TaskRecord, coro) -> None:
        """Wrap an asyncio coroutine so status is mirrored to SQLite."""
        with self._lock:
            rec.status = TaskStatus.RUNNING
            rec.started_at = time.time()
        self._save(rec)
        try:
            result = await coro
            with self._lock:
                rec.status = TaskStatus.COMPLETED
                rec.finished_at = time.time()
                rec.result = str(result) if result is not None else None
        except asyncio.CancelledError:
            with self._lock:
                rec.status = TaskStatus.CANCELLED
                rec.finished_at = time.time()
            raise
        except Exception as e:
            with self._lock:
                rec.status = TaskStatus.FAILED
                rec.finished_at = time.time()
                rec.error = str(e)
        finally:
            self._save(rec)

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Return the TaskRecord for a task ID, or None if not found."""
        with self._lock:
            return self._records.get(task_id)

    def list_tasks(self, limit: int = 20) -> List[TaskRecord]:
        """Return the most recent `limit` task records."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
                cols = [d[0] for d in conn.execute("PRAGMA table_info(tasks)").fetchall()]
            records = []
            for row in rows:
                d = dict(zip(cols, row))
                rec = TaskRecord(
                    task_id=d["task_id"],
                    task_type=d["task_type"],
                    status=TaskStatus(d["status"]),
                    progress=d.get("progress", 0),
                    description=d.get("description", ""),
                    created_at=d.get("created_at", 0),
                    started_at=d.get("started_at"),
                    finished_at=d.get("finished_at"),
                    result=d.get("result"),
                    error=d.get("error"),
                )
                records.append(rec)
            return records
        except Exception as e:
            logger.error(f"list_tasks query failed: {e}")
            with self._lock:
                return sorted(self._records.values(), key=lambda r: r.created_at, reverse=True)[:limit]

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task. Returns True if successfully marked cancelled."""
        with self._lock:
            rec = self._records.get(task_id)
            if not rec:
                return False
            if rec.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return False
            rec.status = TaskStatus.CANCELLED
            rec.finished_at = time.time()

        # Cancel asyncio task if present
        async_task = self._asyncio_tasks.get(task_id)
        if async_task and not async_task.done():
            async_task.cancel()

        self._save(rec)
        return True

    def update_status(
        self,
        task_id: str,
        status: TaskStatus = None,
        progress: int = None,
        result: str = None,
        error: str = None,
    ) -> None:
        """Explicitly update a task's status, progress, result, or error."""
        with self._lock:
            rec = self._records.get(task_id)
            if not rec:
                return
            if status:
                rec.status = status
            if progress is not None:
                rec.progress = min(max(progress, 0), 100)
            if result is not None:
                rec.result = result
            if error is not None:
                rec.error = error
        self._save(rec)

    def shutdown(self) -> None:
        """Graceful shutdown: stop workers, cancel asyncio tasks."""
        self._running = False
        for _ in self._workers:
            self._queue.put(None)
        for t in self._workers:
            t.join(timeout=2.0)
        for at in self._asyncio_tasks.values():
            if not at.done():
                at.cancel()
        logger.info("UnifiedTaskRegistry shut down.")
