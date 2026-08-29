import sqlite3
import os
import logging
import threading

logger = logging.getLogger("JARVIS.FSDatabase")

class FSDatabase:
    """
    FSDatabase provides persistent SQLite database storage for file indexing and usage histories.

    SYSTEM PROMPT:
    Query FSDatabase to fetch or update historical file accesses, searches, and directories caches.

    SHORT DESCRIPTION:
    Manages SQLite database storage operations for filesystem indexing caches and usage logs.

    PROCESS:
    1. Opens SQLite connection with Write-Ahead Logging (WAL) and synchronous normal options.
    2. Constructs file_history and file_cache tables.
    3. Handles logs logging, cached inserts in batch chunks, deletions, and lookup queries.

    FLOW:
    Caller -> log_access() / save_cache_batch() / search_cache() -> sqlite3 library -> SQLite file_manager.db -> Caller
    """
    def __init__(self, db_path: str = None):
        if db_path is None:
            from config.settings import DATA_DIR
            os.makedirs(DATA_DIR, exist_ok=True)
            db_path = os.path.join(DATA_DIR, "file_manager.db")
            
        self.db_path = db_path
        self._db_lock = threading.Lock()
        
        from modules.shared.thread_local_db import ThreadLocalDBs
        self.dbs = ThreadLocalDBs(self.db_path)
        
        self.use_fts = True
        self._init_db()

    @property
    def db_conn(self) -> sqlite3.Connection:
        return self.dbs.get_conn()

    def _init_db(self):
        """Initializes the SQLite database tables."""
        with self._db_lock:
            try:
                self.db_conn.execute("PRAGMA journal_mode=WAL")
                self.db_conn.execute("PRAGMA synchronous=NORMAL")
                
                # History of opened / modified files
                self.db_conn.execute("""
                    CREATE TABLE IF NOT EXISTS file_history (
                        path TEXT PRIMARY KEY,
                        filename TEXT NOT NULL,
                        open_count INTEGER DEFAULT 1,
                        last_opened TEXT NOT NULL
                    )
                """)
                
                # Local index cache of files
                self.db_conn.execute("""
                    CREATE TABLE IF NOT EXISTS file_cache (
                        path TEXT PRIMARY KEY,
                        filename TEXT NOT NULL,
                        filename_lower TEXT NOT NULL,
                        extension TEXT,
                        last_modified REAL,
                        size INTEGER,
                        is_dir INTEGER,
                        source TEXT DEFAULT 'local'
                    )
                """)
                
                # Indexes for faster file_cache lookup
                self.db_conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_filename_lower ON file_cache(filename_lower)")
                self.db_conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_extension ON file_cache(extension)")

                # Create FTS5 virtual table if supported
                try:
                    self.db_conn.execute("""
                        CREATE VIRTUAL TABLE IF NOT EXISTS file_cache_fts USING fts5(
                            path UNINDEXED,
                            filename_lower,
                            tokenize="trigram"
                        )
                    """)
                except sqlite3.OperationalError as e:
                    logger.warning(f"SQLite FTS5 trigram tokenizer not supported: {e}. Falling back to LIKE.")
                    self.use_fts = False

                if self.use_fts:
                    # Sync triggers
                    self.db_conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS fts_after_insert AFTER INSERT ON file_cache BEGIN
                            INSERT INTO file_cache_fts (path, filename_lower) VALUES (new.path, new.filename_lower);
                        END;
                    """)
                    self.db_conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS fts_after_delete AFTER DELETE ON file_cache BEGIN
                            DELETE FROM file_cache_fts WHERE path = old.path;
                        END;
                    """)
                    self.db_conn.execute("""
                        CREATE TRIGGER IF NOT EXISTS fts_after_update AFTER UPDATE OF filename_lower ON file_cache BEGIN
                            DELETE FROM file_cache_fts WHERE path = old.path;
                            INSERT INTO file_cache_fts (path, filename_lower) VALUES (new.path, new.filename_lower);
                        END;
                    """)
                    
                    # Backfill existing cache rows if FTS is empty but cache has files
                    cursor = self.db_conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM file_cache_fts")
                    fts_count = cursor.fetchone()[0]
                    cursor.execute("SELECT COUNT(*) FROM file_cache")
                    cache_count = cursor.fetchone()[0]
                    if fts_count < cache_count:
                        logger.info(f"Backfilling FTS table with {cache_count - fts_count} rows...")
                        self.db_conn.execute("DELETE FROM file_cache_fts")
                        self.db_conn.execute("""
                            INSERT INTO file_cache_fts (path, filename_lower)
                            SELECT path, filename_lower FROM file_cache
                        """)
                        self.db_conn.commit()


                # Alias table for learning engine
                self.db_conn.execute("""
                    CREATE TABLE IF NOT EXISTS file_aliases (
                        query_normalized TEXT,
                        path TEXT,
                        hit_count INTEGER DEFAULT 1,
                        confidence REAL DEFAULT 100.0,
                        last_used TEXT,
                        PRIMARY KEY(query_normalized, path)
                    )
                """)

                # Search sessions for resumable scanning
                self.db_conn.execute("""
                    CREATE TABLE IF NOT EXISTS search_sessions (
                        task_id TEXT PRIMARY KEY,
                        status TEXT,
                        drives_scanned TEXT,
                        current_drive TEXT,
                        progress REAL DEFAULT 0.0,
                        started_at TEXT
                    )
                """)

                # Search audit for tracking operations across security boundaries
                self.db_conn.execute("""
                    CREATE TABLE IF NOT EXISTS search_audit (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        query TEXT,
                        resolved_path TEXT,
                        stage TEXT,
                        drive TEXT,
                        blocked_by_permission INTEGER,
                        timestamp TEXT
                    )
                """)
                self.db_conn.commit()
            except Exception as e:
                logger.error(f"Failed to initialize database: {e}")

    def log_access(self, path: str, timestamp: str):
        try:
            path = os.path.normpath(os.path.abspath(path))
            filename = os.path.basename(path)
            if not filename:
                filename = path # Fallback for drive roots
                
            with self._db_lock:
                try:
                    self.db_conn.execute("""
                        INSERT INTO file_history (path, filename, open_count, last_opened)
                        VALUES (?, ?, 1, ?)
                        ON CONFLICT(path) DO UPDATE SET
                            open_count = open_count + 1,
                            last_opened = excluded.last_opened
                    """, (path, filename, timestamp))
                    self.db_conn.commit()
                except Exception as e:
                    logger.error(f"Failed to log file access for {path}: {e}")
        except Exception as e:
            logger.error(f"Error logging file access: {e}")

    def save_cache_batch(self, batch: list):
        with self._db_lock:
            try:
                self.db_conn.executemany("""
                    INSERT OR REPLACE INTO file_cache (path, filename, filename_lower, extension, last_modified, size, is_dir)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, batch)
                self.db_conn.commit()
            except Exception as e:
                logger.error(f"Failed to save index batch to database: {e}")

    def remove_from_cache(self, path: str):
        with self._db_lock:
            try:
                self.db_conn.execute("DELETE FROM file_cache WHERE path = ?", (path,))
                self.db_conn.commit()
            except Exception as e:
                logger.error(f"Failed to delete {path} from cache: {e}")

    def search_cache(self, filename: str, extensions: list = None, target_dir: str = None, date_filter: str = None, limit: int = 100) -> list:
        """Queries local sqlite database index cache."""
        results = []
        with self._db_lock:
            try:
                cursor = self.db_conn.cursor()
                params = []
                if self.use_fts and filename:
                    query = "SELECT path FROM file_cache WHERE path IN (SELECT path FROM file_cache_fts WHERE filename_lower MATCH ?)"
                    escaped_filename = filename.lower().replace('"', '""')
                    params.append(f'"{escaped_filename}"')

                else:
                    query = "SELECT path FROM file_cache WHERE 1=1"
                    if filename:
                        query += " AND filename_lower LIKE ? ESCAPE '\\'"
                        escaped_filename = filename.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                        params.append(f"%{escaped_filename}%")

                    
                if extensions:
                    placeholders = ",".join(["?"] * len(extensions))
                    query += f" AND extension IN ({placeholders})"
                    params.extend([ext.lower() if ext.startswith('.') else f".{ext.lower()}" for ext in extensions])
                    
                if target_dir:
                    query += " AND path LIKE ? ESCAPE '\\'"
                    escaped_target_dir = os.path.normpath(target_dir).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                    params.append(f"{escaped_target_dir}%")
                    
                if date_filter:
                    import time
                    now = time.time()
                    one_day = 86400
                    if date_filter == "today":
                        query += " AND last_modified >= ?"
                        params.append(now - one_day)
                    elif date_filter == "yesterday":
                        query += " AND last_modified >= ? AND last_modified < ?"
                        params.append(now - 2 * one_day)
                        params.append(now - one_day)
                        
                query += f" LIMIT {limit}"
                cursor.execute(query, params)
                results = [r[0] for r in cursor.fetchall()]
            except Exception as e:
                logger.error(f"SQLite cache query failed: {e}")
        return results

    def get_all_filenames(self, target_dir: str = None, extensions: list = None) -> list:
        results = []
        with self._db_lock:
            try:
                cursor = self.db_conn.cursor()
                query = "SELECT path, filename FROM file_cache WHERE 1=1"
                params = []
                if extensions:
                    placeholders = ",".join(["?"] * len(extensions))
                    query += f" AND extension IN ({placeholders})"
                    params.extend([ext.lower() if ext.startswith('.') else f".{ext.lower()}" for ext in extensions])
                if target_dir:
                    escaped_target_dir = os.path.normpath(target_dir).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                    query += " AND path LIKE ? ESCAPE '\\'"
                    params.append(f"{escaped_target_dir}%")
                cursor.execute(query, params)
                results = cursor.fetchall()
            except Exception as e:
                logger.error(f"SQLite fetch all failed: {e}")
        return results

    def get_history(self) -> dict:
        history = {}
        with self._db_lock:
            try:
                cursor = self.db_conn.cursor()
                cursor.execute("SELECT path, open_count, last_opened FROM file_history")
                for row in cursor.fetchall():
                    history[row[0]] = {"count": row[1], "last_opened": row[2]}
            except Exception as e:
                logger.warning(f"Failed to fetch history: {e}")
        return history

    def prune_stale_cache(self, max_paths_to_check: int = 5000) -> None:
        """Query cached paths in SQLite and remove those that no longer exist on disk without blocking SQLite."""
        logger.info("FSDatabase: Pruning stale file cache paths that no longer exist on disk...")
        try:
            with self._db_lock:
                cursor = self.db_conn.cursor()
                cursor.execute("SELECT path FROM file_cache LIMIT ?", (max_paths_to_check,))
                rows = cursor.fetchall()
            
            paths_to_delete = []
            for i, (path,) in enumerate(rows):
                try:
                    if not os.path.exists(path):
                        paths_to_delete.append(path)
                except Exception:
                    pass
                    
                if i % 100 == 0:
                    import time
                    time.sleep(0.001)  # Yield to foreground queries
                    
                if len(paths_to_delete) >= 500:
                    with self._db_lock:
                        self.db_conn.executemany("DELETE FROM file_cache WHERE path = ?", [(p,) for p in paths_to_delete])
                        self.db_conn.commit()
                    paths_to_delete = []
                    
            if paths_to_delete:
                with self._db_lock:
                    self.db_conn.executemany("DELETE FROM file_cache WHERE path = ?", [(p,) for p in paths_to_delete])
                    self.db_conn.commit()
            logger.info("FSDatabase: Pruning completed successfully.")
        except Exception as e:
            logger.error(f"FSDatabase: Error pruning stale cache: {e}")

    def close(self):
        with self._db_lock:
            try:
                self.dbs.clear()
            except Exception as e:
                logger.error(f"Failed to close SQLite connections: {e}")

