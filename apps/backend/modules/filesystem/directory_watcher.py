import os
import time
import logging
import threading
from typing import Dict
from modules.filesystem.document_parser import DocumentParser

logger = logging.getLogger("JARVIS.DirectoryWatcher")

class DirectoryWatcher:
    """
    Scans a workspace folder in the background to detect new or modified files,
    parses them using DocumentParser, and indexes the chunks into SemanticEngine.
    """
    def __init__(self, watch_path: str, semantic_engine, interval_seconds: int = 10):
        self.watch_path = os.path.normpath(watch_path)
        self.se = semantic_engine
        self.interval = interval_seconds
        self.parser = DocumentParser()
        self.file_mtimes: Dict[str, float] = {}
        self.running = False
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self.running:
                return
            self.running = True
            self._thread = threading.Thread(target=self._run, daemon=True, name="JarvisDirWatcher")
            self._thread.start()
            logger.info(f"DirectoryWatcher started watching: {self.watch_path}")

    def stop(self):
        with self._lock:
            self.running = False
        if self._thread:
            self._thread.join(timeout=2)
            logger.info("DirectoryWatcher stopped.")

    def _run(self):
        # Initial scan to seed existing mtimes
        try:
            self._scan(index_new=False)
        except Exception as e:
            logger.error(f"Initial scan failed: {e}")
            
        while True:
            with self._lock:
                if not self.running:
                    break
            try:
                self._scan(index_new=True)
            except Exception as e:
                logger.error(f"DirectoryWatcher scan iteration failed: {e}")
            time.sleep(self.interval)

    def _scan(self, index_new: bool = True):
        if not os.path.exists(self.watch_path):
            return
            
        current_files = {}
        for root, dirs, files in os.walk(self.watch_path):
            # Prune ignored directories in-place so os.walk does not descend into them
            dirs[:] = [d for d in dirs if d.lower() not in {
                "node_modules", ".git", "venv", "__pycache__", 
                ".pytest_cache", ".agents", ".gemini", "logs", 
                "database", "chroma", "temp", "tmp", ".ruff_cache"
            }]
                
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in (".log", ".db", ".sqlite", ".sqlite3", ".pyc", ".zip", ".tar", ".gz", ".exe", ".bin"):
                    continue
                full_path = os.path.join(root, file)
                try:
                    mtime = os.path.getmtime(full_path)
                    current_files[full_path] = mtime
                except OSError:
                    continue

        # Detect new or changed files
        for path, mtime in current_files.items():
            old_mtime = self.file_mtimes.get(path)
            if old_mtime is None:
                # New file
                self.file_mtimes[path] = mtime
                if index_new:
                    self._index_file(path)
            elif mtime > old_mtime:
                # Modified file
                self.file_mtimes[path] = mtime
                self._index_file(path)

        # Detect deleted files
        deleted = [p for p in self.file_mtimes if p not in current_files]
        for path in deleted:
            del self.file_mtimes[path]

    def _index_file(self, path: str):
        logger.info(f"DirectoryWatcher: File modified/new: {path}")
        chunks = self.parser.chunk_file(path)
        if chunks:
            self.se.index_document_chunks(path, chunks)
