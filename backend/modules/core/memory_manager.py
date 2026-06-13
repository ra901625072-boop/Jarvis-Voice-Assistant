"""
memory_manager.py  –  JARVIS Cognitive Memory Architecture (Phase 5)
=====================================================================
Full cognitive memory system:

  Phase 4 (foundation)
  • Four memory types  : semantic, episodic, procedural, working
  • Importance scoring : 1–10 applied to every stored entry
  • Knowledge graph    : entities + relationships
  • Project namespaces : isolated memory per project
  • Hybrid retrieval   : 0.5×vector + 0.3×importance + 0.2×recency
  • Nightly scheduler  : consolidation, decay, reflection, backup
  • Persistent state   : agent_state table (crash recovery)

  Phase 5 (cognitive layer)
  • Memory Gate        : filters noise — only ~20% of turns become long-term memories
  • Conflict Resolver  : detects contradictions, marks obsolete facts as superseded
  • Experience Replay  : nightly lesson extraction from failures → procedural_memories
  • Goal Memory        : active goals + goal-relevance in hybrid retrieval
  • Tool Memory        : per-tool success/fail tracking via EMA reliability score
  • Memory Lifecycle   : orchestrates full observe→gate→store→reflect→replay pipeline
  • Context Budget Mgr : trims LLM context to configurable token budget
  • Agent Self-Model   : JARVIS's known capabilities seeded at startup
  • Backward-compat    : all original public methods preserved unchanged
"""

import sqlite3
import os
import json
import math
import logging
import threading
import shutil
import time
import schedule
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from modules.core.memory_scorer import MemoryScorer, MemoryImportance

logger = logging.getLogger("JARVIS.Memory")

_LAZY_COMMIT_THRESHOLD = 5


# ============================================================
# Helper
# ============================================================

def _safe_alter(conn: sqlite3.Connection, table: str, col: str, col_def: str) -> None:
    """Add a column to a table only if it does not already exist."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
    except sqlite3.OperationalError:
        pass  # column already exists


# ============================================================
# MemoryManager
# ============================================================


import time
from functools import wraps

def ttl_cache(maxsize=100, ttl=300):
    cache = {}
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            key = str(args) + str(kwargs)
            now = time.time()
            if key in cache:
                result, timestamp = cache[key]
                if now - timestamp < ttl:
                    return result
            result = func(self, *args, **kwargs)
            cache[key] = (result, now)
            if len(cache) > maxsize:
                cache.pop(next(iter(cache)))
            return result
        return wrapper
    return decorator

class MemoryManager:

    """
    Orchestrates all JARVIS memory subsystems.

    Public API (backward-compatible layer)
    ----------------------------------------
    log_conversation(role, content)
    get_recent_history(limit)
    search_history(query, limit)           ← now uses hybrid retrieval
    get_full_context(current_query)        ← enriched with typed memories
    save_workflow(goal, subtasks)
    search_workflows(query, limit)
    set_preference(key, value)
    get_preference(key, default)
    get_all_preferences()
    delete_preference(key)
    clear_history()
    prune_old_conversations(days)
    backup_databases()
    close()

    New public API
    ---------------
    store_memory(content, memory_type, project, importance, tags)
    search_memories(query, memory_type, project, limit)
    get_project_context(project_name)
    add_entity(name, entity_type, description)
    add_relationship(entity_a, relation, entity_b, confidence)
    get_knowledge_context(entity_name)
    get_working_memory(key)
    set_working_memory(key, value, ttl_seconds)
    store_episodic(content, project, importance)
    store_procedural(skill_name, content, importance)
    get_agent_reflections(days)
    update_workflow_stats(goal_pattern, success, exec_time_ms, error)
    persist_agent_state(goal, plan_dict, history, screen_ctx)
    restore_agent_state()
    run_nightly_maintenance()
    """

    def __init__(self, base_dir: str = "database"):
        self.base_dir    = base_dir
        self.memory_dir  = os.path.join(base_dir, "memory")
        self.vector_dir  = os.path.join(base_dir, "vector_memory", "chromadb")
        self.backup_dir  = os.path.join(self.memory_dir, "backups")

        os.makedirs(self.memory_dir,  exist_ok=True)
        os.makedirs(self.vector_dir,  exist_ok=True)
        os.makedirs(self.backup_dir,  exist_ok=True)

        self._lock            = threading.Lock()
        self._pending_commits = 0
        self._scorer          = MemoryScorer()

        # Single shared SQLite connection (WAL mode)
        db_path     = os.path.join(self.memory_dir, "memory.db")
        shared_conn = sqlite3.connect(db_path, check_same_thread=False)
        self.dbs    = {
            "conversations": shared_conn,
            "user":          shared_conn,
            "tasks":         shared_conn,
        }

        with self._lock:
            shared_conn.execute("PRAGMA journal_mode=WAL")
            shared_conn.execute("PRAGMA synchronous=NORMAL")
            shared_conn.execute("PRAGMA foreign_keys=ON")

        # ChromaDB — lazy initialisation
        self._vector_checked  = False
        self._vector_enabled  = False
        self.chroma_client    = None
        self.collection       = None
        self.workflow_collection = None
        self.memory_collection   = None

        # Phase 5 — lazy-init cognitive subsystems via lifecycle
        self._lifecycle: Optional[Any] = None

        # Scheduler
        schedule.every().day.at("03:00").do(self.backup_databases)
        schedule.every().day.at("03:05").do(self.run_nightly_maintenance)

        self._stop_event      = threading.Event()
        self._scheduler_thread = threading.Thread(
            target=self._run_scheduler, daemon=True
        )
        self._scheduler_thread.start()

        logger.info("JARVIS Cognitive MemoryManager (Phase 5) initialized.")

    def initialize_minimal(self) -> None:
        """Minimal initialization for MemoryManager to prevent blocking startup."""
        self._init_tables()
        # Seed self model in background to avoid blocking
        threading.Thread(target=self._delayed_seed_self_model, daemon=True).start()
        # Warm up ChromaDB execution provider models in background
        threading.Thread(target=self._warmup_vector_store, daemon=True).start()

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
        with self._lock:
            if self._vector_checked:
                return self._vector_enabled
            try:
                import chromadb
                self.chroma_client = chromadb.PersistentClient(path=self.vector_dir)
                self.collection = self.chroma_client.get_or_create_collection(
                    name="conversations"
                )
                self.workflow_collection = self.chroma_client.get_or_create_collection(
                    name="workflows"
                )
                self.memory_collection = self.chroma_client.get_or_create_collection(
                    name="memories"
                )
                self._vector_enabled = True
                logger.info("ChromaDB initialized (conversations, workflows, memories).")
            except ImportError:
                logger.warning("chromadb not installed. Semantic search disabled.")
                self._vector_enabled = False
            except Exception as e:
                logger.error(f"ChromaDB init failed: {e}")
                self._vector_enabled = False
            finally:
                self._vector_checked = True
        return self._vector_enabled

    def _commit(self, force: bool = False) -> None:
        """Lazy commit helper — commits every N writes or when forced."""
        self._pending_commits += 1
        if force or self._pending_commits >= _LAZY_COMMIT_THRESHOLD:
            next(iter(self.dbs.values())).commit()
            self._pending_commits = 0

    def _now(self) -> str:
        return datetime.now().isoformat()

    @property
    def lifecycle(self):
        """Lazy-initialize the MemoryLifecycle orchestrator."""
        if self._lifecycle is None:
            from modules.core.memory_lifecycle import MemoryLifecycle
            self._lifecycle = MemoryLifecycle(self)
        return self._lifecycle

    # ------------------------------------------------------------------ #
    # Schema initialisation                                                #
    # ------------------------------------------------------------------ #

    def _init_tables(self) -> None:
        with self._lock:
            conn = next(iter(self.dbs.values()))
            c    = conn.cursor()

            # ── Original tables (kept for backward compatibility) ─────────

            c.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT NOT NULL,
                    role        TEXT NOT NULL,
                    content     TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON conversations(timestamp)")

            # Migration: add new columns to existing conversations table
            _safe_alter(conn, "conversations", "importance",    "INTEGER DEFAULT 3")
            _safe_alter(conn, "conversations", "memory_type",   "TEXT DEFAULT 'general'")
            _safe_alter(conn, "conversations", "project",       "TEXT DEFAULT 'general'")
            _safe_alter(conn, "conversations", "consolidated",  "INTEGER DEFAULT 0")

            c.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts
                USING fts5(content, content='conversations', content_rowid='id')
            """)
            # Triggers (safe: IF NOT EXISTS not supported for triggers, ignore errors)
            for trig_sql in [
                """CREATE TRIGGER IF NOT EXISTS conversations_ai
                   AFTER INSERT ON conversations BEGIN
                     INSERT INTO conversations_fts(rowid, content) VALUES (new.id, new.content);
                   END;""",
                """CREATE TRIGGER IF NOT EXISTS conversations_ad
                   AFTER DELETE ON conversations BEGIN
                     INSERT INTO conversations_fts(conversations_fts, rowid, content)
                     VALUES ('delete', old.id, old.content);
                   END;""",
                """CREATE TRIGGER IF NOT EXISTS conversations_au
                   AFTER UPDATE ON conversations BEGIN
                     INSERT INTO conversations_fts(conversations_fts, rowid, content)
                     VALUES ('delete', old.id, old.content);
                     INSERT INTO conversations_fts(rowid, content) VALUES (new.id, new.content);
                   END;""",
            ]:
                try:
                    c.execute(trig_sql)
                except Exception:
                    pass

            c.execute("""
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary    TEXT NOT NULL,
                    period     TEXT DEFAULT 'daily',
                    topic      TEXT DEFAULT 'general',
                    created_at TEXT NOT NULL
                )
            """)
            _safe_alter(conn, "conversation_summaries", "period", "TEXT DEFAULT 'daily'")
            _safe_alter(conn, "conversation_summaries", "topic",  "TEXT DEFAULT 'general'")

            c.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS user_profile (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    attribute TEXT NOT NULL,
                    value     TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    title     TEXT NOT NULL,
                    due_time  TEXT,
                    completed INTEGER DEFAULT 0
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    description TEXT NOT NULL,
                    status      TEXT DEFAULT 'pending'
                )
            """)


            c.execute("""
                CREATE TABLE IF NOT EXISTS session_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    duration REAL NOT NULL,
                    disconnect_reason TEXT NOT NULL
                )
            """)

            # ── New tables ────────────────────────────────────────────────

            c.execute("""
                CREATE TABLE IF NOT EXISTS semantic_memories (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    content     TEXT NOT NULL,
                    importance  INTEGER DEFAULT 5,
                    project     TEXT DEFAULT 'general',
                    tags        TEXT DEFAULT '',
                    decay_score REAL DEFAULT 1.0,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_sem_project ON semantic_memories(project)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sem_importance ON semantic_memories(importance)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS episodic_memories (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    content     TEXT NOT NULL,
                    importance  INTEGER DEFAULT 5,
                    project     TEXT DEFAULT 'general',
                    event_date  TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_ep_event_date ON episodic_memories(event_date)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS procedural_memories (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name    TEXT NOT NULL,
                    content       TEXT NOT NULL,
                    importance    INTEGER DEFAULT 5,
                    success_count INTEGER DEFAULT 0,
                    fail_count    INTEGER DEFAULT 0,
                    created_at    TEXT NOT NULL,
                    updated_at    TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS working_memory (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    key        TEXT UNIQUE NOT NULL,
                    value      TEXT NOT NULL,
                    expires_at TEXT,
                    updated_at TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS agent_reflections (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    reflection  TEXT NOT NULL,
                    period      TEXT DEFAULT 'daily',
                    created_at  TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS project_memories (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_name TEXT NOT NULL,
                    content      TEXT NOT NULL,
                    importance   INTEGER DEFAULT 5,
                    tags         TEXT DEFAULT '',
                    created_at   TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_pm_project ON project_memories(project_name)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT UNIQUE NOT NULL,
                    entity_type TEXT NOT NULL,
                    description TEXT,
                    created_at  TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS relationships (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_a   TEXT NOT NULL,
                    relation   TEXT NOT NULL,
                    entity_b   TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    UNIQUE(entity_a, relation, entity_b)
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_rel_a ON relationships(entity_a)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_rel_b ON relationships(entity_b)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS workflow_stats (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_pattern    TEXT UNIQUE NOT NULL,
                    success_count   INTEGER DEFAULT 0,
                    fail_count      INTEGER DEFAULT 0,
                    avg_exec_time_ms INTEGER DEFAULT 0,
                    last_error      TEXT,
                    updated_at      TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS agent_state (
                    id                    INTEGER PRIMARY KEY CHECK (id = 1),
                    current_goal          TEXT,
                    active_plan_json      TEXT,
                    execution_history_json TEXT,
                    screen_context_json   TEXT,
                    updated_at            TEXT NOT NULL
                )
            """)

            # ── Phase 5 tables ────────────────────────────────────────────

            c.execute("""
                CREATE TABLE IF NOT EXISTS gate_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT NOT NULL,
                    decision     TEXT NOT NULL,
                    reason       TEXT,
                    created_at   TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS lessons_learned (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    lesson           TEXT NOT NULL,
                    source_pattern   TEXT UNIQUE NOT NULL,
                    occurrence_count INTEGER DEFAULT 1,
                    importance       INTEGER DEFAULT 8,
                    created_at       TEXT NOT NULL,
                    last_triggered   TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS active_goals (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal       TEXT NOT NULL,
                    goal_type  TEXT DEFAULT 'task',
                    parent_id  INTEGER DEFAULT NULL,
                    priority   INTEGER DEFAULT 5,
                    project    TEXT DEFAULT 'general',
                    status     TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (parent_id) REFERENCES active_goals(id) ON DELETE CASCADE
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_goals_status ON active_goals(status)")

            c.execute("""
                CREATE TABLE IF NOT EXISTS goal_progress (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id    INTEGER NOT NULL REFERENCES active_goals(id),
                    milestone  TEXT NOT NULL,
                    status     TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS tool_memory (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name           TEXT UNIQUE NOT NULL,
                    success_count       INTEGER DEFAULT 0,
                    fail_count          INTEGER DEFAULT 0,
                    avg_exec_time_ms    INTEGER DEFAULT 0,
                    last_failure_reason TEXT,
                    last_used           TEXT,
                    reliability_score   REAL DEFAULT 1.0,
                    updated_at          TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS agent_self_model (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    capability TEXT NOT NULL,
                    category   TEXT DEFAULT 'general',
                    confidence REAL DEFAULT 1.0,
                    notes      TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_self_model_cap ON agent_self_model(capability)")

            # Phase 5 migration: add superseded columns to semantic_memories
            _safe_alter(conn, "semantic_memories", "superseded",    "INTEGER DEFAULT 0")
            _safe_alter(conn, "semantic_memories", "superseded_by", "INTEGER")
            # Phase 5 migration: enrich relationships table
            _safe_alter(conn, "relationships", "source_memory",  "INTEGER")
            _safe_alter(conn, "relationships", "last_verified",  "TEXT")

            conn.commit()
            logger.info("All memory tables (Phase 4 + Phase 5) initialised.")

    # ================================================================== #
    # BACKWARD-COMPATIBLE PUBLIC API                                       #
    # ================================================================== #

    # ── Conversation logging ──────────────────────────────────────────── #

    def log_conversation(self, role: str, content: str) -> None:
        """Log a conversation turn. Scores, gates, resolves conflicts, then stores."""
        import time
        start_t = time.perf_counter()
        
        timestamp    = self._now()
        meta         = self._scorer.analyze(content, role)
        importance   = meta["importance"]
        memory_type  = meta["memory_type"]
        project      = meta["project"]
        tags         = meta["tags"]

        # Always write to the raw conversations table (full audit log)
        with self._lock:
            cursor = self.dbs["conversations"].execute(
                """INSERT INTO conversations
                   (timestamp, role, content, importance, memory_type, project)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (timestamp, role, content, importance, memory_type, project),
            )
            inserted_id = cursor.lastrowid
            self._commit()

        # Phase 5: route through memory lifecycle (gate + resolve + store)
        _FAST_CHAT_MODE = os.getenv("JARVIS_FAST_CHAT", "1") == "1"
        if _FAST_CHAT_MODE and importance < MemoryImportance.MEDIUM:
            stored = False
        else:
            try:
                stored = self.lifecycle.on_new_message(
                    content=content,
                    role=role,
                    importance=importance,
                    memory_type=memory_type,
                    project=project,
                    tags=tags,
                    timestamp=timestamp,
                )
            except Exception as e:
                logger.error(f"Lifecycle on_new_message failed, falling back: {e}")
                # Fallback: direct store if lifecycle fails
                stored = False
                if importance >= MemoryImportance.MEDIUM:
                    self._store_typed_memory(content, memory_type, project, importance, tags, timestamp)
                    stored = True

        # Vector store with rich metadata (only if important enough)
        if importance >= MemoryImportance.MEDIUM and self._ensure_vector_client():
            def _bg_vector_add():
                try:
                    self.collection.add(
                        documents=[content],
                        metadatas=[{
                            "role":        role,
                            "importance":  importance,
                            "memory_type": memory_type,
                            "project":     project,
                            "tags":        tags,
                            "timestamp":   timestamp,
                        }],
                        ids=[str(inserted_id)],
                    )
                except Exception as e:
                    logger.error(f"Vector insert failed: {e}")
            threading.Thread(target=_bg_vector_add, daemon=True).start()
            
        logger.info(f"Memory write: {time.perf_counter() - start_t:.3f}s")

    def get_recent_history(self, limit: int = 10) -> list:
        with self._lock:
            cursor = self.dbs["conversations"].execute(
                "SELECT role, content FROM conversations ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            results = cursor.fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(results)]

    def search_history(self, query: str, limit: int = 5) -> list:
        """Hybrid retrieval: vector similarity + importance + recency."""
        return self._hybrid_search(query, collection=self.collection, limit=limit)

    def get_full_context(self, current_query: str = None) -> str:
        """
        Builds a comprehensive context string for the LLM prompt.
        Phase 5: Delegates to MemoryLifecycle.build_context() which:
          - Applies a token budget (default 3000 tokens)
          - Prioritises: goals > preferences > tasks > memories > KG > lessons > reflections
          - Includes goal-relevance scores and agent self-model
        """
        try:
            return self.lifecycle.build_context(current_query=current_query)
        except Exception as e:
            logger.error(f"Lifecycle context build failed, using fallback: {e}")
            # Fallback to basic context
            parts = []
            prefs = self.get_all_preferences()
            if prefs:
                parts.append("--- USER PREFERENCES ---\n" + "\n".join(f"- {k}: {v}" for k, v in prefs.items()))
            return "\n\n".join(parts)

    # ── Workflow memory ───────────────────────────────────────────────── #

    def save_workflow(self, goal: str, subtasks: list) -> None:
        """Save a successful workflow plan to vector DB."""
        if not self._ensure_vector_client():
            return
        try:
            workflow_id = f"wf_{int(time.time())}"
            content = f"Goal: {goal}\nSteps:\n" + "\n".join(f"- {t}" for t in subtasks)
            self.workflow_collection.add(
                documents=[content],
                metadatas=[{"goal": goal, "timestamp": self._now()}],
                ids=[workflow_id],
            )
            logger.info(f"Workflow saved: '{goal}'")
        except Exception as e:
            logger.error(f"Failed to save workflow: {e}")

    def search_workflows(self, query: str, limit: int = 3) -> list:
        """Search past successful plans."""
        if not self._ensure_vector_client():
            return []
        try:
            res = self.workflow_collection.query(query_texts=[query], n_results=limit)
            if res and res["documents"] and res["documents"][0]:
                return [
                    {"goal": m["goal"], "plan": d}
                    for d, m in zip(res["documents"][0], res["metadatas"][0])
                ]
        except Exception as e:
            logger.error(f"Workflow search failed: {e}")
        return []

    # ── Preferences ───────────────────────────────────────────────────── #

    def set_preference(self, key: str, value: str) -> None:
        with self._lock:
            self.dbs["user"].execute(
                "INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)", (key, value)
            )
            self.dbs["user"].commit()
        # Mirror important preferences to semantic memory
        content = f"User preference: {key} = {value}"
        importance = MemoryImportance.HIGH
        with self._lock:
            self.dbs["user"].execute(
                """INSERT INTO semantic_memories
                   (content, importance, project, tags, decay_score, created_at, updated_at)
                   VALUES (?, ?, 'general', 'preference', 1.0, ?, ?)""",
                (content, importance, self._now(), self._now()),
            )
            self._commit()

    def get_preference(self, key: str, default=None):
        with self._lock:
            cursor = self.dbs["user"].execute(
                "SELECT value FROM preferences WHERE key = ?", (key,)
            )
            result = cursor.fetchone()
        return result[0] if result else default

    def get_all_preferences(self) -> dict:
        with self._lock:
            cursor = self.dbs["user"].execute("SELECT key, value FROM preferences")
            results = cursor.fetchall()
        return {k: v for k, v in results}

    def delete_preference(self, key: str) -> bool:
        with self._lock:
            cursor = self.dbs["user"].execute(
                "DELETE FROM preferences WHERE key = ?", (key,)
            )
            self.dbs["user"].commit()
            return cursor.rowcount > 0

    # ── Maintenance ───────────────────────────────────────────────────── #

    def prune_old_conversations(self, days: int = 90) -> None:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            cursor = self.dbs["conversations"].execute(
                "DELETE FROM conversations WHERE timestamp < ?", (cutoff,)
            )
            self.dbs["conversations"].commit()
            logger.info(f"Pruned {cursor.rowcount} old conversations.")


    def log_session_disconnect(self, duration: float, disconnect_reason: str) -> None:
        try:
            with self._lock:
                conn = next(iter(self.dbs.values()))
                conn.execute(
                    "INSERT INTO session_metrics (timestamp, duration, disconnect_reason) VALUES (?, ?, ?)",
                    (self._now(), duration, disconnect_reason)
                )
                self._commit(force=True)
        except Exception as e:
            import logging
            logging.getLogger("JARVIS.Memory").error(f"Failed to log session disconnect: {e}")

    def backup_databases(self) -> None:
        logger.info("Running automated database backup...")
        with self._lock:
            next(iter(self.dbs.values())).commit()
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            src = os.path.join(self.memory_dir, "memory.db")
            dst = os.path.join(self.backup_dir, f"memory_{ts}.bak")
            if os.path.exists(src):
                shutil.copy2(src, dst)
        logger.info("Database backup complete.")

    def clear_history(self) -> None:
        with self._lock:
            self.dbs["conversations"].execute("DELETE FROM conversations")
            self.dbs["conversations"].commit()
            if self._ensure_vector_client():
                try:
                    self.chroma_client.delete_collection("conversations")
                    self.collection = self.chroma_client.create_collection("conversations")
                except Exception as e:
                    logger.debug(f"ChromaDB reset: {e}")

    def run_nightly_maintenance(self) -> None:
        """Delegates to MemoryLifecycle.run_nightly() for full maintenance pipeline."""
        logger.info("Triggering nightly maintenance via MemoryLifecycle...")
        try:
            self.lifecycle.run_nightly()
        except Exception as e:
            logger.error(f"Nightly maintenance error: {e}", exc_info=True)

    def close(self) -> None:
        if hasattr(self, "_stop_event"):
            self._stop_event.set()
        with self._lock:
            unique_conns = list(set(self.dbs.values()))
            if unique_conns:
                conn = unique_conns[0]
                if self._pending_commits > 0:
                    try:
                        conn.commit()
                    except Exception:
                        pass
                for c in unique_conns:
                    try:
                        c.close()
                    except Exception:
                        pass
            self.dbs.clear()
        logger.info("MemoryManager closed.")

    # ================================================================== #
    # NEW PUBLIC API                                                       #
    # ================================================================== #

    # ── Typed memory storage ──────────────────────────────────────────── #

    def store_memory(
        self,
        content: str,
        memory_type: str = "semantic",
        project: str = "general",
        importance: int = None,
        tags: str = None,
    ) -> int:
        """
        Explicitly store a memory entry.  Returns the new row id.
        importance is auto-scored if not provided.
        """
        if importance is None:
            importance = self._scorer.score(content)
        if tags is None:
            tags = ",".join(self._scorer.extract_tags(content))
        ts = self._now()

        row_id = self._store_typed_memory(
            content=content,
            memory_type=memory_type,
            project=project,
            importance=importance,
            tags=tags,
            timestamp=ts,
        )

        # Also embed in ChromaDB memories collection
        if self._ensure_vector_client() and row_id:
            try:
                self.memory_collection.add(
                    documents=[content],
                    metadatas=[{
                        "memory_type": memory_type,
                        "project":     project,
                        "importance":  importance,
                        "tags":        tags,
                        "timestamp":   ts,
                    }],
                    ids=[f"mem_{row_id}_{memory_type}"],
                )
            except Exception as e:
                logger.error(f"Failed to embed memory: {e}")
        return row_id

    def store_episodic(self, content: str, project: str = "general", importance: int = None) -> None:
        """Shortcut: store an episodic (experience) memory."""
        if importance is None:
            importance = self._scorer.score(content)
        ts = self._now()
        with self._lock:
            self.dbs["conversations"].execute(
                """INSERT INTO episodic_memories
                   (content, importance, project, event_date, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (content, importance, project, ts, ts),
            )
            self._commit()

    def store_procedural(self, skill_name: str, content: str, importance: int = 5) -> None:
        """Shortcut: store a procedural (how-to) memory."""
        ts = self._now()
        with self._lock:
            self.dbs["conversations"].execute(
                """INSERT OR REPLACE INTO procedural_memories
                   (skill_name, content, importance, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (skill_name, content, importance, ts, ts),
            )
            self._commit()

    # ── Typed search ─────────────────────────────────────────────────── #

    @ttl_cache(maxsize=100, ttl=300)
    def search_memories(
        self,
        query: str,
        memory_type: str = None,
        project: str = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search across all typed memories.
        Filters by memory_type and/or project if provided.
        """
        import time
        start_t = time.perf_counter()
        
        # Try SQLite FTS first for speed
        fts_results = self._fts_memory_fallback(query, memory_type, project, limit=10)
        
        # If we got strong results from SQLite, return them and skip ChromaDB
        if fts_results and len(fts_results) >= limit // 2:
            logger.info(f"Memory retrieval (SQLite): {time.perf_counter() - start_t:.3f}s")
            return fts_results[:limit]
            
        # Try ChromaDB memories collection as fallback
        if self._ensure_vector_client():
            try:
                where_filter = {}
                if memory_type:
                    where_filter["memory_type"] = {"$eq": memory_type}
                if project:
                    where_filter["project"] = {"$eq": project}

                kwargs: Dict[str, Any] = {
                    "query_texts": [query],
                    "n_results":   min(limit * 3, 50),
                }
                if where_filter:
                    kwargs["where"] = where_filter

                res = self.memory_collection.query(**kwargs)
                if res and res["documents"] and res["documents"][0]:
                    candidates = []
                    for doc, meta, dist in zip(
                        res["documents"][0],
                        res["metadatas"][0],
                        res["distances"][0],
                    ):
                        vector_sim   = max(0.0, 1.0 - dist)
                        imp          = meta.get("importance", 5) / 10.0
                        ts_str       = meta.get("timestamp", self._now())
                        age_days     = self._age_days(ts_str)
                        recency      = math.exp(-0.05 * age_days)
                        final_score  = 0.5 * vector_sim + 0.3 * imp + 0.2 * recency
                        candidates.append({
                            "content":     doc,
                            "memory_type": meta.get("memory_type", "semantic"),
                            "project":     meta.get("project", "general"),
                            "importance":  meta.get("importance", 5),
                            "tags":        meta.get("tags", ""),
                            "score":       final_score,
                        })
                    candidates.sort(key=lambda x: x["score"], reverse=True)
                    logger.info(f"Memory retrieval (Hybrid DB): {time.perf_counter() - start_t:.3f}s")
                    return candidates[:limit]
            except Exception as e:
                logger.error(f"Memory search (ChromaDB) failed: {e}")

        # SQLite fallback if vector search fails completely
        logger.info(f"Memory retrieval (Fallback): {time.perf_counter() - start_t:.3f}s")
        return fts_results[:limit]

    @ttl_cache(maxsize=100, ttl=300)
    def get_project_context(self, project_name: str) -> str:
        """Return all memories tagged to a specific project as a formatted string."""
        with self._lock:
            rows = self.dbs["conversations"].execute(
                """SELECT content, importance FROM semantic_memories
                   WHERE project = ? ORDER BY importance DESC, updated_at DESC LIMIT 20""",
                (project_name,),
            ).fetchall()
            pm_rows = self.dbs["conversations"].execute(
                """SELECT content, importance FROM project_memories
                   WHERE project_name = ? ORDER BY importance DESC LIMIT 10""",
                (project_name,),
            ).fetchall()

        all_rows = sorted(rows + pm_rows, key=lambda r: r[1], reverse=True)
        if not all_rows:
            return f"No memories found for project: {project_name}"

        lines = [f"--- PROJECT CONTEXT: {project_name.upper()} ---"]
        for content, imp in all_rows[:15]:
            lines.append(f"[imp:{imp}] {content[:250]}")
        return "\n".join(lines)

    # ── Knowledge Graph ───────────────────────────────────────────────── #

    def add_entity(
        self, name: str, entity_type: str, description: str = ""
    ) -> None:
        """Add or update a knowledge graph node."""
        ts = self._now()
        with self._lock:
            self.dbs["conversations"].execute(
                """INSERT OR REPLACE INTO entities (name, entity_type, description, created_at)
                   VALUES (?, ?, ?, ?)""",
                (name, entity_type, description, ts),
            )
            self._commit()

    def add_relationship(
        self,
        entity_a: str,
        relation: str,
        entity_b: str,
        confidence: float = 1.0,
    ) -> None:
        """Add a directed relationship between two entities."""
        ts = self._now()
        with self._lock:
            self.dbs["conversations"].execute(
                """INSERT OR REPLACE INTO relationships
                   (entity_a, relation, entity_b, confidence, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (entity_a, relation, entity_b, confidence, ts),
            )
            self._commit()

    def get_knowledge_context(self, entity_name: str) -> str:
        """
        Return a formatted string of all relationships for an entity —
        used for reasoning beyond vector similarity.
        """
        with self._lock:
            outgoing = self.dbs["conversations"].execute(
                "SELECT relation, entity_b FROM relationships WHERE entity_a = ?",
                (entity_name,),
            ).fetchall()
            incoming = self.dbs["conversations"].execute(
                "SELECT entity_a, relation FROM relationships WHERE entity_b = ?",
                (entity_name,),
            ).fetchall()
            entity = self.dbs["conversations"].execute(
                "SELECT entity_type, description FROM entities WHERE name = ?",
                (entity_name,),
            ).fetchone()

        if not outgoing and not incoming and not entity:
            return ""

        lines = [f"Entity: {entity_name}"]
        if entity:
            lines.append(f"  Type: {entity[0]}  |  {entity[1]}")
        for rel, target in outgoing:
            lines.append(f"  → {rel} → {target}")
        for source, rel in incoming:
            lines.append(f"  ← {rel} ← {source}")
        return "\n".join(lines)

    # ── Working memory ────────────────────────────────────────────────── #

    def set_working_memory(
        self, key: str, value: str, ttl_seconds: int = 3600
    ) -> None:
        """Store a volatile working-memory entry with a TTL."""
        ts         = self._now()
        expires_at = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()
        with self._lock:
            self.dbs["conversations"].execute(
                """INSERT OR REPLACE INTO working_memory (key, value, expires_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (key, value, expires_at, ts),
            )
            self._commit()

    def get_working_memory(self, key: str) -> Optional[str]:
        """Retrieve a working-memory entry if not expired."""
        now = self._now()
        with self._lock:
            row = self.dbs["conversations"].execute(
                """SELECT value FROM working_memory
                   WHERE key = ? AND (expires_at IS NULL OR expires_at > ?)""",
                (key, now),
            ).fetchone()
        return row[0] if row else None

    # ── Workflow stats ────────────────────────────────────────────────── #

    def update_workflow_stats(
        self,
        goal_pattern: str,
        success: bool,
        exec_time_ms: int = 0,
        error: str = None,
    ) -> None:
        """Record outcome of a workflow execution for adaptive learning."""
        ts = self._now()
        with self._lock:
            existing = self.dbs["conversations"].execute(
                "SELECT id, success_count, fail_count, avg_exec_time_ms FROM workflow_stats WHERE goal_pattern = ?",
                (goal_pattern,),
            ).fetchone()

            if existing:
                row_id, succ, fail, avg_ms = existing
                new_succ = succ + (1 if success else 0)
                new_fail = fail + (0 if success else 1)
                total    = new_succ + new_fail
                new_avg  = int((avg_ms * (total - 1) + exec_time_ms) / total) if total else 0
                self.dbs["conversations"].execute(
                    """UPDATE workflow_stats
                       SET success_count=?, fail_count=?, avg_exec_time_ms=?, last_error=?, updated_at=?
                       WHERE id=?""",
                    (new_succ, new_fail, new_avg, error, ts, row_id),
                )
            else:
                self.dbs["conversations"].execute(
                    """INSERT INTO workflow_stats
                       (goal_pattern, success_count, fail_count, avg_exec_time_ms, last_error, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        goal_pattern,
                        1 if success else 0,
                        0 if success else 1,
                        exec_time_ms,
                        error,
                        ts,
                    ),
                )
            self._commit()

    def get_workflow_stats(self, goal_pattern: str) -> Optional[Dict[str, Any]]:
        """Return success/fail stats for a given goal pattern."""
        with self._lock:
            row = self.dbs["conversations"].execute(
                "SELECT success_count, fail_count, avg_exec_time_ms FROM workflow_stats WHERE goal_pattern = ?",
                (goal_pattern,),
            ).fetchone()
        if not row:
            return None
        succ, fail, avg = row
        total = succ + fail
        rate  = round(succ / total * 100, 1) if total else 0.0
        return {
            "success_count":   succ,
            "fail_count":      fail,
            "success_rate":    rate,
            "avg_exec_time_ms": avg,
        }

    # ── Agent reflections ─────────────────────────────────────────────── #

    def get_agent_reflections(self, days: int = 7) -> List[Dict[str, Any]]:
        """Return recent reflections generated by the reflection engine."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            rows = self.dbs["conversations"].execute(
                """SELECT reflection, period, created_at FROM agent_reflections
                   WHERE created_at >= ? ORDER BY created_at DESC LIMIT 20""",
                (cutoff,),
            ).fetchall()
        return [{"reflection": r[0], "period": r[1], "created_at": r[2]} for r in rows]

    # ── Persistent agent state ────────────────────────────────────────── #

    def persist_agent_state(
        self,
        goal: Optional[str],
        plan_dict: Optional[Dict],
        history: Optional[List],
        screen_ctx: Optional[Dict],
    ) -> None:
        """Checkpoint the current agent state to SQLite for crash recovery."""
        ts = self._now()
        with self._lock:
            self.dbs["conversations"].execute(
                """INSERT OR REPLACE INTO agent_state
                   (id, current_goal, active_plan_json, execution_history_json, screen_context_json, updated_at)
                   VALUES (1, ?, ?, ?, ?, ?)""",
                (
                    goal,
                    json.dumps(plan_dict) if plan_dict else None,
                    json.dumps(history)   if history   else None,
                    json.dumps(screen_ctx) if screen_ctx else None,
                    ts,
                ),
            )
            self._commit(force=True)

    def restore_agent_state(self) -> Optional[Dict[str, Any]]:
        """Restore the last persisted agent state.  Returns None if none exists."""
        with self._lock:
            row = self.dbs["conversations"].execute(
                """SELECT current_goal, active_plan_json, execution_history_json,
                          screen_context_json, updated_at
                   FROM agent_state WHERE id = 1"""
            ).fetchone()
        if not row:
            return None
        return {
            "current_goal":   row[0],
            "active_plan":    json.loads(row[1]) if row[1] else None,
            "history":        json.loads(row[2]) if row[2] else [],
            "screen_context": json.loads(row[3]) if row[3] else {},
            "saved_at":       row[4],
        }

    # ── Nightly maintenance ───────────────────────────────────────────── #

    def run_nightly_maintenance(self) -> None:
        """
        Called nightly at 03:05.
        1. Consolidate yesterday's conversations into summaries.
        2. Apply memory decay to low-importance semantic memories.
        3. Generate a daily reflection.
        4. Purge expired working memory entries.
        5. Prune old consolidated conversations.
        """
        logger.info("Starting nightly memory maintenance...")
        try:
            from modules.core.memory_consolidator import MemoryConsolidator
            from modules.core.reflection_engine   import ReflectionEngine

            consolidator = MemoryConsolidator(self)
            consolidator.run()

            reflector = ReflectionEngine(self)
            reflector.run()

        except ImportError as e:
            logger.warning(f"Consolidation/reflection module not yet available: {e}")
        except Exception as e:
            logger.error(f"Nightly maintenance error: {e}")

        # Purge expired working memory
        self._purge_working_memory()

        # Prune consolidated old conversations
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        with self._lock:
            self.dbs["conversations"].execute(
                "DELETE FROM conversations WHERE consolidated = 1 AND timestamp < ?",
                (cutoff,),
            )
            self._commit(force=True)

        logger.info("Nightly maintenance complete.")

    # ================================================================== #
    # PRIVATE HELPERS                                                      #
    # ================================================================== #

    def _store_typed_memory(
        self,
        content: str,
        memory_type: str,
        project: str,
        importance: int,
        tags: str,
        timestamp: str,
    ) -> Optional[int]:
        """Write to the appropriate typed memory table and return the row id."""
        with self._lock:
            if memory_type == "episodic":
                cursor = self.dbs["conversations"].execute(
                    """INSERT INTO episodic_memories
                       (content, importance, project, event_date, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (content, importance, project, timestamp, timestamp),
                )
            elif memory_type == "procedural":
                cursor = self.dbs["conversations"].execute(
                    """INSERT INTO procedural_memories
                       (skill_name, content, importance, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (content[:60], content, importance, timestamp, timestamp),
                )
            else:
                # default: semantic
                cursor = self.dbs["conversations"].execute(
                    """INSERT INTO semantic_memories
                       (content, importance, project, tags, decay_score, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 1.0, ?, ?)""",
                    (content, importance, project, tags, timestamp, timestamp),
                )
                # If project-specific, also record in project_memories
                if project != "general":
                    self.dbs["conversations"].execute(
                        """INSERT INTO project_memories
                           (project_name, content, importance, tags, created_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (project, content, importance, tags, timestamp),
                    )
            self._commit()
            return cursor.lastrowid

    def _hybrid_search(
        self,
        query: str,
        collection=None,
        memory_type: str = None,
        project: str = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Phase 5 hybrid retrieval:
          Score = 0.40 x vector_similarity
                + 0.25 x (importance / 10)
                + 0.20 x recency
                + 0.15 x goal_relevance     <- Phase 5 addition
        Falls back to FTS if ChromaDB is unavailable.
        """
        candidates = []

        # Pre-compute goal relevance scorer (lazy — avoid circular init)
        try:
            _goal_scorer = self.lifecycle.goal_memory.goal_relevance_score
        except Exception:
            _goal_scorer = None

        # --- Vector path ---
        if self._ensure_vector_client() and collection is not None:
            try:
                kwargs: Dict[str, Any] = {
                    "query_texts": [query],
                    "n_results":   min(limit * 4, 50),
                }
                res = collection.query(**kwargs)
                if res and res["documents"] and res["documents"][0]:
                    for doc, meta, dist in zip(
                        res["documents"][0],
                        res["metadatas"][0],
                        res["distances"][0],
                    ):
                        vector_sim   = max(0.0, 1.0 - dist)
                        imp          = meta.get("importance", 3) / 10.0
                        ts_str       = meta.get("timestamp", self._now())
                        age_days     = self._age_days(ts_str)
                        recency      = math.exp(-0.05 * age_days)
                        goal_rel     = _goal_scorer(doc) if _goal_scorer else 0.0
                        final_score  = (0.40 * vector_sim
                                      + 0.25 * imp
                                      + 0.20 * recency
                                      + 0.15 * goal_rel)
                        candidates.append({
                            "timestamp":   ts_str,
                            "role":        meta.get("role", "user"),
                            "content":     doc,
                            "memory_type": meta.get("memory_type", "general"),
                            "project":     meta.get("project", "general"),
                            "importance":  meta.get("importance", 3),
                            "score":       final_score,
                        })
            except Exception as e:
                logger.error(f"Hybrid vector search failed: {e}")

        # --- FTS fallback / supplement ---
        if len(candidates) < limit:
            fts_rows = self._fts_search_raw(query, limit * 2)
            existing_contents = {c["content"] for c in candidates}
            for row in fts_rows:
                if row["content"] not in existing_contents:
                    imp        = row.get("importance", 3) / 10.0
                    age_days   = self._age_days(row.get("timestamp", self._now()))
                    recency    = math.exp(-0.05 * age_days)
                    goal_rel   = _goal_scorer(row["content"]) if _goal_scorer else 0.0
                    row["score"] = (0.25 * imp + 0.20 * recency + 0.15 * goal_rel)
                    candidates.append(row)

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:limit]

    def _fts_search_raw(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Raw FTS search against conversations table."""
        try:
            safe_q = query.replace('"', "").replace("'", "")
            with self._lock:
                rows = self.dbs["conversations"].execute(
                    """SELECT c.timestamp, c.role, c.content,
                              COALESCE(c.importance, 3),
                              COALESCE(c.memory_type, 'general'),
                              COALESCE(c.project, 'general')
                       FROM conversations c
                       JOIN conversations_fts fts ON c.id = fts.rowid
                       WHERE conversations_fts MATCH ?
                       ORDER BY fts.rank
                       LIMIT ?""",
                    (f'"{safe_q}*"', limit),
                ).fetchall()
            return [
                {
                    "timestamp":   r[0],
                    "role":        r[1],
                    "content":     r[2],
                    "importance":  r[3],
                    "memory_type": r[4],
                    "project":     r[5],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"FTS search failed: {e}")
            return []

    def _fts_memory_fallback(
        self,
        query: str,
        memory_type: Optional[str],
        project: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Fallback: search semantic_memories by keyword."""
        try:
            sql = "SELECT content, importance, project, tags FROM semantic_memories WHERE content LIKE ?"
            params: list = [f"%{query}%"]
            if memory_type:
                pass  # semantic_memories doesn't store type column — future improvement
            if project:
                sql += " AND project = ?"
                params.append(project)
            sql += " ORDER BY importance DESC LIMIT ?"
            params.append(limit)
            with self._lock:
                rows = self.dbs["conversations"].execute(sql, params).fetchall()
            return [
                {
                    "content":     r[0],
                    "importance":  r[1],
                    "project":     r[2],
                    "tags":        r[3],
                    "memory_type": "semantic",
                    "score":       r[1] / 10.0,
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"FTS memory fallback failed: {e}")
            return []

    def _build_kg_context(self, query: str) -> str:
        """Extract knowledge-graph context relevant to the query."""
        try:
            # Find entities whose names appear in the query
            words = re.findall(r"\b\w{4,}\b", query.lower()) if query else []
            lines = []
            for word in words[:5]:
                with self._lock:
                    rows = self.dbs["conversations"].execute(
                        "SELECT name FROM entities WHERE LOWER(name) LIKE ?",
                        (f"%{word}%",),
                    ).fetchall()
                for (name,) in rows:
                    ctx = self.get_knowledge_context(name)
                    if ctx:
                        lines.append(ctx)
            return "\n".join(lines[:6])  # cap at 6 entity blocks
        except Exception as e:
            logger.debug(f"KG context build failed: {e}")
            return ""

    def _age_days(self, timestamp_str: str) -> float:
        """Return age of a timestamp in days (float)."""
        try:
            dt = datetime.fromisoformat(timestamp_str)
            return (datetime.now() - dt).total_seconds() / 86400.0
        except Exception:
            return 0.0

    def _purge_working_memory(self) -> None:
        """Delete expired working memory entries."""
        now = self._now()
        with self._lock:
            self.dbs["conversations"].execute(
                "DELETE FROM working_memory WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            self._commit()


import re  # ensure re is available for _build_kg_context
