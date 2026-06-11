import os
import shutil
import logging
import string
import time
import subprocess
import platform
import threading
import sqlite3
import re
from datetime import datetime
from send2trash import send2trash
from modules.filesystem.fs_utils import get_drives, is_safe_path, close_explorer_window

logger = logging.getLogger("JARVIS.FolderManager")

class FolderManager:
    def __init__(self, db_path: str = None, file_mgr = None):
        self.file_mgr = file_mgr
        if db_path is None:
            if file_mgr:
                self.db_path = file_mgr.db_path
                self._db_lock = file_mgr._db_lock
            else:
                db_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database")
                os.makedirs(db_dir, exist_ok=True)
                self.db_path = os.path.join(db_dir, "file_manager.db")
                self._db_lock = threading.Lock()
        else:
            self.db_path = db_path
            self._db_lock = threading.Lock()
            
        logger.info(f"FolderManager initialized with DB: {self.db_path}")

    def log_folder_access(self, path: str):
        """Logs a folder access event to SQLite for search memory and ranking."""
        try:
            path = os.path.normpath(os.path.abspath(path))
            filename = os.path.basename(path)
            if not filename:
                filename = path # Fallback for drive roots
            timestamp = datetime.now().isoformat()
            with self._db_lock:
                conn = sqlite3.connect(self.db_path)
                try:
                    conn.execute("""
                        INSERT INTO file_history (path, filename, open_count, last_opened)
                        VALUES (?, ?, 1, ?)
                        ON CONFLICT(path) DO UPDATE SET
                            open_count = open_count + 1,
                            last_opened = excluded.last_opened
                    """, (path, filename, timestamp))
                    conn.commit()
                except Exception as e:
                    logger.error(f"Failed to log folder access for {path}: {e}")
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"Error logging folder access: {e}")



    def create_folder(self, path: str):
        try:
            path = os.path.normpath(os.path.abspath(path))
            if not is_safe_path(path):
                return "Error: Security Policy blocks modification of protected system folder."
            os.makedirs(path, exist_ok=True)
            self.log_folder_access(path)
            logger.info(f"Created folder: {path}")
            return True
        except PermissionError:
            return "Error: Permission Denied. Unable to create folder."
        except Exception as e:
            logger.error(f"Failed to create folder {path}: {e}")
            return f"Error: {e}"

    def list_directory(self, path: str):
        try:
            path = os.path.normpath(os.path.abspath(path))
            if os.path.isdir(path):
                self.log_folder_access(path)
                return os.listdir(path)
            return []
        except PermissionError:
            return "Error: Permission Denied. Unable to list contents of this folder."
        except Exception as e:
            logger.error(f"Failed to list directory {path}: {e}")
            return []

    def delete_folder(self, path: str):
        try:
            path = os.path.normpath(os.path.abspath(path))
            if not is_safe_path(path):
                return "Error: Security Policy blocks deletion of protected system folder."
            if not os.path.isdir(path):
                return "Error: Path is not a directory."
            send2trash(path)
            logger.info(f"Sent folder {path} to recycle bin.")
            return True
        except PermissionError:
            return "Error: Permission Denied. Unable to delete this folder."
        except Exception as e:
            logger.error(f"Failed to delete folder {path}: {e}")
            return f"Error: {e}"

    def move_folder(self, src: str, dest: str, force_sync: bool = False):
        """Moves a folder, utilizing background thread if cross-drive & large."""
        try:
            src = os.path.normpath(os.path.abspath(src))
            dest = os.path.normpath(os.path.abspath(dest))
            
            if not is_safe_path(src) or not is_safe_path(dest):
                return "Error: Security Policy blocks moving system folder."
                
            if not os.path.isdir(src):
                return "Error: Source path is not a directory."
                
            def _execute_move():
                try:
                    if os.path.exists(dest):
                        if os.path.isdir(dest):
                            shutil.rmtree(dest)
                        else:
                            os.remove(dest)
                    shutil.move(src, dest)
                    logger.info(f"Background move folder complete: {src} to {dest}")
                    self.log_folder_access(dest)
                except Exception as e:
                    logger.error(f"Background folder move failed: {e}")
            
            src_drive = os.path.splitdrive(src)[0].lower()
            dest_drive = os.path.splitdrive(dest)[0].lower()
            is_cross_drive = src_drive != dest_drive
            
            # Cross-drive directory moves are slow, run in background
            if is_cross_drive and not force_sync:
                logger.info(f"Starting background cross-drive folder move: {src} to {dest}")
                threading.Thread(target=_execute_move, daemon=True).start()
                return "BackgroundProcessStarted"
            else:
                # Synchronous move
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.move(src, dest)
                logger.info(f"Moved folder {src} to {dest}")
                self.log_folder_access(dest)
                return True
        except PermissionError:
            return "Error: Permission Denied. Unable to move this folder."
        except Exception as e:
            logger.error(f"Failed to move folder {src} to {dest}: {e}")
            return f"Error: {e}"

    def copy_folder(self, src: str, dest: str):
        """Copies a folder, merging directories instead of throwing FileExistsError."""
        try:
            src = os.path.normpath(os.path.abspath(src))
            dest = os.path.normpath(os.path.abspath(dest))
            
            if not is_safe_path(src) or not is_safe_path(dest):
                return "Error: Security Policy blocks copying system directories."
                
            if not os.path.exists(src):
                return f"Error: Source directory does not exist: {src}"
                
            if not os.path.isdir(src):
                return "Error: Source path is not a directory."
                
            os.makedirs(dest, exist_ok=True)
            for item in os.listdir(src):
                s = os.path.join(src, item)
                d = os.path.join(dest, item)
                if os.path.isdir(s):
                    self.copy_folder(s, d)
                else:
                    shutil.copy2(s, d)
            logger.info(f"Copied folder {src} to {dest}")
            self.log_folder_access(dest)
            return True
        except PermissionError:
            return "Error: Permission Denied. Unable to copy folder."
        except Exception as e:
            logger.error(f"Failed to copy folder {src} to {dest}: {e}")
            return f"Error: {e}"

    def rename_folder(self, src: str, new_name: str):
        try:
            src = os.path.normpath(os.path.abspath(src))
            if not is_safe_path(src):
                return "Error: Security Policy blocks modification of protected system folder."
            if not os.path.isdir(src):
                return "Error: Source path is not a directory."
                
            dest = os.path.join(os.path.dirname(src), new_name)
            if not is_safe_path(dest):
                return "Error: Security Policy blocks modification of protected system folder."
                
            os.rename(src, dest)
            logger.info(f"Renamed folder {src} to {dest}")
            return True
        except PermissionError:
            return "Error: Permission Denied. Unable to rename this folder."
        except Exception as e:
            logger.error(f"Failed to rename folder {src} to {new_name}: {e}")
            return f"Error: {e}"

    def close_folder(self, path: str) -> bool:
        """Closes File Explorer windows matching the folder path."""
        return close_explorer_window(path)
