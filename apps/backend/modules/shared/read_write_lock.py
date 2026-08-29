"""
read_write_lock.py — A fair read-write lock for concurrent memory access.

Allows multiple concurrent readers while giving writers exclusive access.
Uses threading.Condition for efficient waiting (no busy-wait/spin).

Usage:
    rwlock = ReadWriteLock()

    # Read path (concurrent):
    with rwlock.read_lock():
        data = db.execute("SELECT ...").fetchall()

    # Write path (exclusive):
    with rwlock.write_lock():
        db.execute("INSERT ...")
        db.commit()
"""

import threading
from contextlib import contextmanager


class ReadWriteLock:
    """Fair reentrant read-write lock using threading.Condition.

    Multiple readers can hold the lock concurrently.
    A writer gets exclusive access, blocking new readers and
    waiting for existing readers to finish.

    Reentrant support: If the same thread that holds a write lock
    attempts to acquire another write lock or read lock, it is granted
    access immediately without deadlocking.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers: int = 0
        self._writer: bool = False
        self._writer_waiting: int = 0
        self._writer_thread = None
        self._writer_count: int = 0
        self._local = threading.local()

    def __enter__(self):
        # Default to a write lock (exclusive) for compatibility
        self._local.active_mgr = self.write_lock()
        self._local.active_mgr.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self._local, "active_mgr"):
            self._local.active_mgr.__exit__(exc_type, exc_val, exc_tb)
            del self._local.active_mgr

    @contextmanager
    def read_lock(self):
        """Context manager for acquiring a read (shared) lock."""
        tid = threading.get_ident()
        with self._cond:
            if self._writer_thread == tid:
                self._readers += 1
            else:
                while self._writer or self._writer_waiting > 0:
                    self._cond.wait()
                self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    @contextmanager
    def write_lock(self):
        """Context manager for acquiring a write (exclusive) lock."""
        tid = threading.get_ident()
        with self._cond:
            if self._writer_thread == tid:
                self._writer_count += 1
                reentrant = True
            else:
                reentrant = False
                self._writer_waiting += 1
                while self._writer or self._readers > 0:
                    self._cond.wait()
                self._writer_waiting -= 1
                self._writer = True
                self._writer_thread = tid
                self._writer_count = 1
        try:
            yield
        finally:
            with self._cond:
                if reentrant:
                    self._writer_count -= 1
                else:
                    self._writer_count -= 1
                    if self._writer_count <= 0:
                        self._writer = False
                        self._writer_thread = None
                        self._cond.notify_all()
