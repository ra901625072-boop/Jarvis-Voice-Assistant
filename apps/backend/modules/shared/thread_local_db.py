"""
thread_local_db.py  –  Shared thread-local SQLite connection pool
=================================================================
Provides a single ThreadLocalDBs class that creates one SQLite
connection per thread with WAL mode, NORMAL synchronous, and
foreign-key enforcement.  Shared across modules to avoid duplicating
connection-management logic.
"""

import sqlite3
import threading


class ThreadLocalDBs:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        self._all_conns = []
        self._lock = threading.Lock()

    def get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA wal_autocheckpoint=1000")
            self._local.conn = conn
            with self._lock:
                self._all_conns.append(conn)
        return self._local.conn

    def __contains__(self, key):
        """Returns True if the key is a valid database alias string."""
        return isinstance(key, str)

    def __getitem__(self, key):
        return self.get_conn()

    def values(self):
        with self._lock:
            return list(self._all_conns)

    def commit_all_and_close(self):
        """Commit and close all connections across all threads."""
        with self._lock:
            for conn in self._all_conns:
                try:
                    conn.commit()
                except Exception:
                    import logging
                    logging.getLogger("JARVIS.ThreadLocalDBs").warning(f"Failed to commit connection: {conn}", exc_info=True)
                try:
                    conn.close()
                except Exception:
                    import logging
                    logging.getLogger("JARVIS.ThreadLocalDBs").warning(f"Failed to close connection: {conn}", exc_info=True)
            self._all_conns.clear()
        if hasattr(self._local, "conn"):
            del self._local.conn

    def clear(self):
        with self._lock:
            for conn in self._all_conns:
                try:
                    conn.close()
                except Exception:
                    pass
            self._all_conns.clear()
        if hasattr(self._local, "conn"):
            del self._local.conn
