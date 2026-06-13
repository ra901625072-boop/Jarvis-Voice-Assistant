import sqlite3
import os
import logging
import threading

logger = logging.getLogger("JARVIS.FSDatabase")

class FSDatabase:
    def __init__(self, db_path: str = None):
        if db_path is None:
            # Resolve db in backend/database folder
            db_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "database")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "file_manager.db")
            
        self.db_path = db_path
        self._db_lock = threading.Lock()
        self.db_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

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
                        is_dir INTEGER
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
                query = "SELECT path FROM file_cache WHERE 1=1"
                params = []
                
                if filename:
                    query += " AND filename_lower LIKE ?"
                    params.append(f"%{filename.lower()}%")
                    
                if extensions:
                    placeholders = ",".join(["?"] * len(extensions))
                    query += f" AND extension IN ({placeholders})"
                    params.extend([ext.lower() if ext.startswith('.') else f".{ext.lower()}" for ext in extensions])
                    
                if target_dir:
                    query += " AND path LIKE ?"
                    params.append(f"{os.path.normpath(target_dir)}%")
                    
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
