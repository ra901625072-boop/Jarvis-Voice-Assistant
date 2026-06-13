import os
import time
import logging
import threading
from modules.filesystem.fs_db import FSDatabase

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    class FileSystemEventHandler: pass
    Observer = None

logger = logging.getLogger("JARVIS.FSIndexer")

class FSIndexEventHandler(FileSystemEventHandler):
    def __init__(self, db: FSDatabase):
        self.db = db
        self.ignore_dirs = {'.git', 'node_modules', 'venv', 'AppData', 'Windows', 'Program Files', 'Program Files (x86)', '__pycache__', 'Temp', 'Local', 'Roaming'}

    def _should_ignore(self, path: str) -> bool:
        parts = os.path.normpath(path).split(os.sep)
        return any(part in self.ignore_dirs for part in parts)

    def _get_file_info(self, path: str) -> tuple:
        try:
            stat = os.stat(path)
            name = os.path.basename(path)
            filename_lower = name.lower()
            ext = os.path.splitext(filename_lower)[1]
            is_dir = 1 if os.path.isdir(path) else 0
            return (
                os.path.normpath(path),
                name,
                filename_lower,
                ext,
                stat.st_mtime,
                stat.st_size,
                is_dir
            )
        except (PermissionError, FileNotFoundError, OSError):
            return None

    def on_created(self, event):
        if self._should_ignore(event.src_path): return
        info = self._get_file_info(event.src_path)
        if info:
            self.db.save_cache_batch([info])

    def on_modified(self, event):
        if self._should_ignore(event.src_path): return
        info = self._get_file_info(event.src_path)
        if info:
            self.db.save_cache_batch([info])

    def on_deleted(self, event):
        if self._should_ignore(event.src_path): return
        self.db.remove_from_cache(os.path.normpath(event.src_path))

    def on_moved(self, event):
        if self._should_ignore(event.src_path): return
        self.db.remove_from_cache(os.path.normpath(event.src_path))
        if not self._should_ignore(event.dest_path):
            info = self._get_file_info(event.dest_path)
            if info:
                self.db.save_cache_batch([info])


class FSIndexer:
    def __init__(self, db: FSDatabase):
        self.db = db
        self.observer = None
        self.monitored_paths = []

    def get_default_paths(self):
        root_paths = []
        # Project root workspace
        workspace = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        root_paths.append(workspace)
        
        # User key folders
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            for folder in ["Documents", "Desktop", "Downloads"]:
                folder_path = os.path.join(user_profile, folder)
                if os.path.exists(folder_path):
                    root_paths.append(folder_path)
        return root_paths

    def start_background_indexer(self, root_paths: list = None):
        if root_paths is None:
            root_paths = self.get_default_paths()
            
        # 1. Start initial deep scan
        threading.Thread(target=self._initial_deep_scan, args=(root_paths,), daemon=True).start()
        
        # 2. Start realtime observer if available
        if WATCHDOG_AVAILABLE:
            self.start_realtime_observer(root_paths)
        else:
            logger.warning("watchdog package not installed. Realtime filesystem monitoring disabled.")

    def _initial_deep_scan(self, root_paths: list):
        """Walks folders to update sqlite cache."""
        handler = FSIndexEventHandler(self.db)
        chunk_size = 500
        batch = []
        
        for root_path in root_paths:
            if not os.path.exists(root_path):
                continue
            for root, dirs, files in os.walk(root_path):
                # Prune ignored folders
                dirs[:] = [d for d in dirs if d not in handler.ignore_dirs]
                
                for name in files + dirs:
                    path = os.path.join(root, name)
                    info = handler._get_file_info(path)
                    if info:
                        batch.append(info)
                        
                    if len(batch) >= chunk_size:
                        self.db.save_cache_batch(batch)
                        batch = []
                        time.sleep(0.02) # Yield execution
                        
            if batch:
                self.db.save_cache_batch(batch)
                batch = []
        logger.info("Initial deep file index completed.")

    def start_realtime_observer(self, root_paths: list):
        if self.observer:
            self.stop_realtime_observer()
            
        self.observer = Observer()
        event_handler = FSIndexEventHandler(self.db)
        
        for path in root_paths:
            if os.path.exists(path):
                try:
                    self.observer.schedule(event_handler, path, recursive=True)
                    self.monitored_paths.append(path)
                    logger.info(f"Started monitoring: {path}")
                except Exception as e:
                    logger.error(f"Failed to monitor {path}: {e}")
                    
        if self.monitored_paths:
            self.observer.start()

    def stop_realtime_observer(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
            self.monitored_paths = []
