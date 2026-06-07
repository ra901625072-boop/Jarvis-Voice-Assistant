import sqlite3
import os
import logging
import threading
import shutil
import schedule
import time
from datetime import datetime, timedelta

logger = logging.getLogger("JARVIS.Memory")

# Threshold for SQLite lazy commits (Lowered for safety)
_LAZY_COMMIT_THRESHOLD = 3

class MemoryManager:
    def __init__(self, base_dir: str = "database"):
        self.base_dir = base_dir
        self.memory_dir = os.path.join(base_dir, "memory")
        self.vector_dir = os.path.join(base_dir, "vector_memory", "chromadb")
        self.backup_dir = os.path.join(self.memory_dir, "backups")
        
        os.makedirs(self.memory_dir, exist_ok=True)
        os.makedirs(self.vector_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)

        self._lock = threading.Lock()
        self._pending_commits = 0

        # Setup modular SQLite connections
        self.dbs = {
            "conversations": sqlite3.connect(os.path.join(self.memory_dir, "conversations.db"), check_same_thread=False),
            "user": sqlite3.connect(os.path.join(self.memory_dir, "user.db"), check_same_thread=False),
            "tasks": sqlite3.connect(os.path.join(self.memory_dir, "tasks.db"), check_same_thread=False)
        }

        with self._lock:
            for db_name, conn in self.dbs.items():
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")

        self._init_tables()
        
        # Initialize Vector Memory (Semantic Search)
        try:
            import chromadb
            self.chroma_client = chromadb.PersistentClient(path=self.vector_dir)
            self.collection = self.chroma_client.get_or_create_collection(name="conversations")
            self.vector_enabled = True
            logger.info("ChromaDB vector memory enabled.")
        except ImportError:
            logger.warning("chromadb not installed. Semantic search disabled. Falling back to FTS.")
            self.vector_enabled = False
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
            self.vector_enabled = False

        # Schedule automatic backups at 3 AM daily
        schedule.every().day.at("03:00").do(self.backup_databases)
        
        self._stop_event = threading.Event()
        self._scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self._scheduler_thread.start()
        
        logger.info("Advanced MemoryManager initialized.")

    def _run_scheduler(self):
        while not self._stop_event.is_set():
            schedule.run_pending()
            time.sleep(1)

    def _init_tables(self) -> None:
        with self._lock:
            # --- CONVERSATIONS DB ---
            c_cursor = self.dbs["conversations"].cursor()
            c_cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT    NOT NULL,
                    role      TEXT    NOT NULL,
                    content   TEXT    NOT NULL
                )
            """)
            c_cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON conversations(timestamp)")
            c_cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts 
                USING fts5(content, content='conversations', content_rowid='id')
            """)
            c_cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS conversations_ai AFTER INSERT ON conversations BEGIN
                    INSERT INTO conversations_fts(rowid, content) VALUES (new.id, new.content);
                END;
            """)
            c_cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS conversations_ad AFTER DELETE ON conversations BEGIN
                    INSERT INTO conversations_fts(conversations_fts, rowid, content) VALUES('delete', old.id, old.content);
                END;
            """)
            c_cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS conversations_au AFTER UPDATE ON conversations BEGIN
                    INSERT INTO conversations_fts(conversations_fts, rowid, content) VALUES('delete', old.id, old.content);
                    INSERT INTO conversations_fts(rowid, content) VALUES (new.id, new.content);
                END;
            """)
            
            c_cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary TEXT,
                    created_at TEXT
                )
            """)
            self.dbs["conversations"].commit()

            # --- USER DB ---
            u_cursor = self.dbs["user"].cursor()
            u_cursor.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            u_cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attribute TEXT NOT NULL,
                    value TEXT NOT NULL
                )
            """)
            self.dbs["user"].commit()

            # --- TASKS DB ---
            t_cursor = self.dbs["tasks"].cursor()
            t_cursor.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    due_time TEXT,
                    completed INTEGER DEFAULT 0
                )
            """)
            t_cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending'
                )
            """)
            self.dbs["tasks"].commit()

    # ------------------------------------------------------------------
    # Core Operations
    # ------------------------------------------------------------------

    def log_conversation(self, role: str, content: str) -> None:
        timestamp = datetime.now().isoformat()
        
        # 1. SQLite Insert
        with self._lock:
            cursor = self.dbs["conversations"].execute(
                "INSERT INTO conversations (timestamp, role, content) VALUES (?, ?, ?)",
                (timestamp, role, content),
            )
            inserted_id = cursor.lastrowid
            
            self._pending_commits += 1
            if self._pending_commits >= _LAZY_COMMIT_THRESHOLD:
                self.dbs["conversations"].commit()
                self._pending_commits = 0

        # 2. Vector DB Insert
        if self.vector_enabled:
            try:
                self.collection.add(
                    documents=[content],
                    metadatas=[{"role": role, "timestamp": timestamp}],
                    ids=[str(inserted_id)]
                )
            except Exception as e:
                logger.error(f"Failed to insert into vector DB: {e}")

    def get_recent_history(self, limit: int = 10) -> list:
        with self._lock:
            cursor = self.dbs["conversations"].execute(
                "SELECT role, content FROM conversations ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            results = cursor.fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(results)]

    def search_history(self, query: str, limit: int = 5) -> list:
        # First try vector search if available (much better semantic matching)
        if self.vector_enabled:
            try:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=limit
                )
                
                if results and results['documents'] and results['documents'][0]:
                    docs = results['documents'][0]
                    metas = results['metadatas'][0]
                    return [{"timestamp": m["timestamp"], "role": m["role"], "content": d} 
                            for d, m in zip(docs, metas)]
            except Exception as e:
                logger.error(f"Vector search failed, falling back to FTS: {e}")

        # Fallback to standard SQLite FTS
        with self._lock:
            safe_query = query.replace('"', '').replace("'", "")
            cursor = self.dbs["conversations"].execute('''
                SELECT c.timestamp, c.role, c.content 
                FROM conversations c
                JOIN conversations_fts fts ON c.id = fts.rowid
                WHERE conversations_fts MATCH ?
                ORDER BY fts.rank
                LIMIT ?
            ''', (f'"{safe_query}*"', limit))
            results = cursor.fetchall()
        return [{"timestamp": r[0], "role": r[1], "content": r[2]} for r in results]

    # ------------------------------------------------------------------
    # Full Context Pipeline
    # ------------------------------------------------------------------

    def get_full_context(self, current_query: str = None) -> str:
        """
        Builds a comprehensive context string for the LLM prompt.
        Includes semantic memory, user preferences, and pending tasks.
        """
        context_parts = []

        # 1. User Preferences
        prefs = self.get_all_preferences()
        if prefs:
            prefs_str = "\n".join([f"- {k}: {v}" for k, v in prefs.items()])
            context_parts.append(f"--- USER PREFERENCES ---\n{prefs_str}")

        # 2. Pending Tasks & Reminders
        with self._lock:
            t_cursor = self.dbs["tasks"].execute("SELECT description FROM tasks WHERE status='pending'")
            tasks = t_cursor.fetchall()
            r_cursor = self.dbs["tasks"].execute("SELECT title, due_time FROM reminders WHERE completed=0")
            reminders = r_cursor.fetchall()

        if tasks or reminders:
            task_str = "--- PENDING TASKS & REMINDERS ---\n"
            for t in tasks: task_str += f"- Task: {t[0]}\n"
            for r in reminders: task_str += f"- Reminder: {r[0]} (Due: {r[1]})\n"
            context_parts.append(task_str.strip())

        # 3. Semantic Memory (if query provided)
        if current_query and self.vector_enabled:
            semantic_matches = self.search_history(current_query, limit=3)
            if semantic_matches:
                mem_str = "--- RELEVANT PAST MEMORIES ---\n"
                for m in semantic_matches:
                    mem_str += f"[{m['timestamp']}] {m['role']}: {m['content'][:200]}...\n"
                context_parts.append(mem_str.strip())

        return "\n\n".join(context_parts)

    # ------------------------------------------------------------------
    # Maintenance & Safety
    # ------------------------------------------------------------------

    def prune_old_conversations(self, days: int = 90):
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            cursor = self.dbs["conversations"].execute("DELETE FROM conversations WHERE timestamp < ?", (cutoff_date,))
            self.dbs["conversations"].commit()
            logger.info(f"Pruned {cursor.rowcount} old conversations.")

    def backup_databases(self):
        logger.info("Running automated database backup...")
        with self._lock:
            # Force commit all
            for db in self.dbs.values():
                db.commit()
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            for db_name in self.dbs:
                src = os.path.join(self.memory_dir, f"{db_name}.db")
                dst = os.path.join(self.backup_dir, f"{db_name}_{timestamp}.bak")
                if os.path.exists(src):
                    shutil.copy2(src, dst)
        logger.info("Database backup complete.")

    def close(self) -> None:
        if hasattr(self, '_stop_event'):
            self._stop_event.set()
        with self._lock:
            for db_name, conn in self.dbs.items():
                if conn:
                    if self._pending_commits > 0 and db_name == "conversations":
                        try:
                            conn.commit()
                        except Exception:
                            pass
                    conn.close()
            self.dbs.clear()
        logger.info("MemoryManager closed safely.")

    # ------------------------------------------------------------------
    # Preferences API
    # ------------------------------------------------------------------

    def set_preference(self, key: str, value: str) -> None:
        with self._lock:
            self.dbs["user"].execute("INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)", (key, value))
            self.dbs["user"].commit()

    def get_preference(self, key: str, default=None):
        with self._lock:
            cursor = self.dbs["user"].execute("SELECT value FROM preferences WHERE key = ?", (key,))
            result = cursor.fetchone()
        return result[0] if result else default

    def get_all_preferences(self) -> dict:
        with self._lock:
            cursor = self.dbs["user"].execute("SELECT key, value FROM preferences")
            results = cursor.fetchall()
        return {k: v for k, v in results}

    def delete_preference(self, key: str) -> bool:
        with self._lock:
            cursor = self.dbs["user"].execute("DELETE FROM preferences WHERE key = ?", (key,))
            self.dbs["user"].commit()
            return cursor.rowcount > 0

    def clear_history(self) -> None:
        with self._lock:
            self.dbs["conversations"].execute("DELETE FROM conversations")
            self.dbs["conversations"].commit()
            if self.vector_enabled:
                try:
                    self.chroma_client.delete_collection("conversations")
                    self.collection = self.chroma_client.create_collection("conversations")
                except Exception:
                    pass
