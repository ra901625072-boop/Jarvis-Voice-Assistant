"""
memory_manager.py  –  JARVIS Cognitive Memory Architecture (Phase 5) Façade
=====================================================================
Centralized controller for SQLite tables, ChromaDB vector stores, and Phase 5 cognitive memory components.
Composes specialized mixin classes for schema, search, CRUD, knowledge graph, vision cache, and lifecycle management.
"""

import sqlite3
import os
import math
import logging
import threading
import asyncio
import time
import schedule
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from modules.memory.scorer import MemoryScorer, MemoryImportance
from modules.memory.lifecycle import MemoryLifecycle
from config.settings import DATA_DIR, CHROMA_DIR
from modules.shared.thread_local_db import ThreadLocalDBs
from modules.shared.read_write_lock import ReadWriteLock

# Import Mixins
from modules.memory.schema import MemorySchemaMixin
from modules.memory.store import MemoryStoreMixin
from modules.memory.search import MemorySearchMixin
from modules.knowledge.knowledge_graph import KnowledgeGraphMixin
from modules.memory.vision import MemoryVisionMixin
from modules.memory.lifecycle_mixin import MemoryLifecycleMixin

try:
    import chromadb
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False

logger = logging.getLogger("JARVIS.Memory")


class MemoryManager(
    MemorySchemaMixin,
    MemoryStoreMixin,
    MemorySearchMixin,
    KnowledgeGraphMixin,
    MemoryVisionMixin,
    MemoryLifecycleMixin
):
    """
    MemoryManager orchestrates all JARVIS memory subsystems and databases.
    It acts as a façade inheriting from schema, search, store, KG, vision, and lifecycle mixins.
    """

    def __init__(self, base_dir: str = None):
        import sys
        if not base_dir and ("pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ):
            import tempfile
            base_dir = tempfile.mkdtemp(prefix="jarvis_test_")

        self.base_dir    = base_dir or DATA_DIR
        self.memory_dir  = os.path.join(self.base_dir, "memory")
        self.vector_dir  = CHROMA_DIR
        self.backup_dir  = os.path.join(self.memory_dir, "backups")

        os.makedirs(self.memory_dir,  exist_ok=True)
        os.makedirs(self.vector_dir,  exist_ok=True)
        os.makedirs(self.backup_dir,  exist_ok=True)

        self._lock            = ReadWriteLock()
        self._pending_commits = 0
        self._scorer          = MemoryScorer()

        # Thread-local SQLite connection (WAL mode)
        db_path     = os.path.join(self.memory_dir, "memory.db")
        self.dbs    = ThreadLocalDBs(db_path)

        # ChromaDB — lazy initialisation
        self._vector_checked  = False
        self._vector_enabled  = False
        self.chroma_client    = None
        self.collection       = None
        self.workflow_collection = None
        self.memory_collection   = None

        # Phase 5 — initialize cognitive subsystems via lifecycle directly (no lazy load)
        self.lifecycle = MemoryLifecycle(self)

        # Scheduler
        if "pytest" not in sys.modules and "PYTEST_CURRENT_TEST" not in os.environ:
            schedule.every().day.at("03:00").do(self.backup_databases)
            schedule.every().day.at("03:05").do(self.run_nightly_maintenance)

            self._stop_event      = threading.Event()
            self._scheduler_thread = threading.Thread(
                target=self._run_scheduler, daemon=True
            )
        else:
            self._stop_event      = None
            self._scheduler_thread = None

        # Initialize SQLite tables and migrations
        self._init_tables()

        logger.info("JARVIS Cognitive MemoryManager (Phase 5) initialized.")

    def initialize_minimal(self) -> None:
        """Minimal initialization for MemoryManager to prevent blocking startup."""
        self._init_tables()
        import sys
        if "pytest" not in sys.modules and "PYTEST_CURRENT_TEST" not in os.environ:
            # Seed self model in background to avoid blocking
            threading.Thread(target=self._delayed_seed_self_model, daemon=True).start()
            # Warm up ChromaDB execution provider models in background
            threading.Thread(target=self._warmup_vector_store, daemon=True).start()
        else:
            # In test mode, perform self-model seeding synchronously to make scores immediately available
            try:
                self.lifecycle.seed_self_model()
            except Exception:
                pass

    def start_async_writer(self, loop) -> None:
        """Starts the background worker task that consumes write operations from the queue."""
        with self._lock.write_lock():
            if hasattr(self, "_writer_task") and self._writer_task and not self._writer_task.done():
                return
            self._write_queue = asyncio.Queue()
            self._writer_task = loop.create_task(self._async_writer_loop())
            logger.info("Async Memory Writer task started successfully.")

    async def _async_writer_loop(self):
        while True:
            try:
                func, args, kwargs = await self._write_queue.get()
                retries = 5
                for attempt in range(retries):
                    try:
                        await asyncio.to_thread(func, *args, **kwargs)
                        break
                    except sqlite3.OperationalError as op_err:
                        if "locked" in str(op_err).lower() and attempt < retries - 1:
                            await asyncio.sleep(0.2 * (2 ** attempt))
                            continue
                        raise
                self._write_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background memory writer loop: {e}")

    def enqueue_write(self, func, *args, **kwargs):
        """Enqueues a write operation to be processed in the background, falling back to sync write if no loop exists."""
        if hasattr(self, "_write_queue"):
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(self._write_queue.put_nowait, (func, args, kwargs))
                return
            except RuntimeError:
                pass
            except asyncio.QueueFull:
                logger.warning(f"Memory write queue is full. Falling back to synchronous execution of {func.__name__}")
        
        # Fallback to direct synchronous execution with retries
        logger.warning(f"No running event loop found or background task inactive. Executing write synchronously: {func.__name__}")
        retries = 5
        for attempt in range(retries):
            try:
                func(*args, **kwargs)
                break
            except sqlite3.OperationalError as op_err:
                if "locked" in str(op_err).lower() and attempt < retries - 1:
                    time.sleep(0.2 * (2 ** attempt))
                    continue
                logger.error(f"Fallback sync write failed for {func.__name__}: {op_err}")
                break
            except Exception as e:
                logger.error(f"Fallback sync write failed for {func.__name__}: {e}")
                break

    def _delayed_seed_self_model(self) -> None:
        import time
        time.sleep(5)
        try:
            self.lifecycle.seed_self_model()
        except Exception:
            pass

    def _warmup_vector_store(self) -> None:
        if self._ensure_vector_client():
            try:
                self.memory_collection.query(
                    query_texts=["warmup"],
                    n_results=1
                )
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _run_scheduler(self) -> None:
        while not self._stop_event.is_set():
            try:
                schedule.run_pending()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            time.sleep(30)

    def _ensure_vector_client(self) -> bool:
        if self._vector_checked:
            return self._vector_enabled
        with self._lock.write_lock():
            if self._vector_checked:
                return self._vector_enabled
            if _CHROMA_AVAILABLE:
                try:
                    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
                    embedding_fn = ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])
                    
                    self.chroma_client = chromadb.PersistentClient(path=self.vector_dir)
                    for col_name in ["conversations", "workflows", "memories"]:
                        try:
                            col = self.chroma_client.get_or_create_collection(
                                name=col_name,
                                embedding_function=embedding_fn
                            )
                        except Exception:
                            self.chroma_client.delete_collection(col_name)
                            col = self.chroma_client.create_collection(
                                name=col_name,
                                embedding_function=embedding_fn
                            )
                        if col_name == "conversations":
                            self.collection = col
                        elif col_name == "workflows":
                            self.workflow_collection = col
                        elif col_name == "memories":
                            self.memory_collection = col
                    self._vector_enabled = True
                    logger.info("ChromaDB initialized (conversations, workflows, memories).")
                except Exception as e:
                    logger.error(f"ChromaDB init failed: {e}")
                    self._vector_enabled = False
                finally:
                    self._vector_checked = True
            else:
                logger.warning("chromadb not installed. Semantic search disabled.")
                self._vector_enabled = False
                self._vector_checked = True
        return self._vector_enabled

    def _commit(self, force: bool = False) -> None:
        """Lazy commit helper — commits every write immediately when thread-local connections are used."""
        self.dbs.get_conn().commit()
        self._pending_commits = 0

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _age_days(self, timestamp_str: str) -> float:
        """Return age of a timestamp in days (float)."""
        try:
            dt = datetime.fromisoformat(timestamp_str)
            return (datetime.now() - dt).total_seconds() / 86400.0
        except Exception:
            return 0.0
