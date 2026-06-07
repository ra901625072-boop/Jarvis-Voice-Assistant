import os
import shutil
import logging
import string
import time
import subprocess
import platform
from rapidfuzz import fuzz
from send2trash import send2trash

logger = logging.getLogger("JARVIS.FileManager")

class FileManager:
    def __init__(self):
        self._path_cache = {}
        logger.info("FileManager initialized.")

    def get_drives(self) -> list:
        """Returns a list of all available drive letters on Windows."""
        drives = []
        if platform.system() == "Windows":
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives.append(drive)
        else:
            drives = ["/"]
        return drives

    def search_file(self, filename: str, root_dir: str = None, limit: int = 5, extensions: list = None) -> list:
        """
        Searches for a file or folder using fuzzy matching.
        Searches all drives if root_dir is None (on Windows).
        """
        logger.info(f"Searching for item '{filename}'...")
        results = []
        filename = filename.lower()
        
        # Ignored directories to speed up search
        ignore_dirs = {'.git', 'node_modules', 'venv', 'AppData', 'Windows', 'Program Files', 'Program Files (x86)', '__pycache__', 'Temp', 'Local', 'Roaming'}
        max_depth = 6
        
        start_time = time.time()
        max_time = 15.0 # increased timeout for multi-drive search
        max_items = 100000 
        items_scanned = 0
        
        # Normalize extensions
        if extensions:
            extensions = [ext.lower() if ext.startswith('.') else f".{ext.lower()}" for ext in extensions]
        
        def _scan(current_path, current_depth):
            nonlocal items_scanned
            if current_depth > max_depth:
                return
                
            try:
                with os.scandir(current_path) as it:
                    for entry in it:
                        items_scanned += 1
                        
                        if items_scanned % 500 == 0:
                            if items_scanned >= max_items or time.time() - start_time > max_time:
                                return
                                
                        name_lower = entry.name.lower()
                        name_without_ext, ext = os.path.splitext(name_lower)
                        
                        # Apply extension filter if provided and it's a file
                        if extensions and entry.is_file(follow_symlinks=False):
                            if ext not in extensions:
                                continue

                        if filename in name_without_ext:
                            results.append((100, entry.path))
                        elif abs(len(filename) - len(name_without_ext)) <= max(5, len(filename) * 0.3): # Stricter length constraint
                            score = fuzz.ratio(filename, name_without_ext) # ratio is faster than partial_ratio
                            if score > 85:
                                results.append((score, entry.path))
                                
                        if entry.is_dir(follow_symlinks=False) and entry.name not in ignore_dirs:
                            _scan(entry.path, current_depth + 1)
            except (PermissionError, FileNotFoundError, OSError):
                pass

        if root_dir:
            _scan(root_dir, 0)
        else:
            for drive in self.get_drives():
                if time.time() - start_time > max_time or items_scanned >= max_items:
                    break
                _scan(drive, 0)
        
        results.sort(key=lambda x: x[0], reverse=True)
        # return unique paths in case of duplicates
        unique_results = []
        seen = set()
        for score, path in results:
            if path not in seen:
                seen.add(path)
                unique_results.append(path)
            if len(unique_results) >= limit:
                break
                
        return unique_results

    def resolve_path(self, query: str) -> str:
        """Resolves a natural language query like 'open resume' to an absolute path."""
        # Check cache
        if query in self._path_cache and os.path.exists(self._path_cache[query]):
            return self._path_cache[query]
            
        # Check if query itself is a valid path
        if os.path.exists(query):
            self._path_cache[query] = query
            return query
            
        results = self.search_file(query, limit=1)
        if results:
            path = results[0]
            self._path_cache[query] = path
            return path
            
        return None

    def create_folder(self, path: str):
        try:
            os.makedirs(path, exist_ok=True)
            logger.info(f"Created folder: {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to create folder {path}: {e}")
            return False

    def create_file(self, path: str, content: str = ""):
        try:
            # Ensure parent folder exists
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Created file: {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to create file {path}: {e}")
            return False

    def read_file(self, path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read file {path}: {e}")
            return None
            
    def write_file(self, path: str, content: str):
        return self.create_file(path, content)

    def delete_item(self, path: str):
        try:
            send2trash(path)
            logger.info(f"Sent {path} to recycle bin.")
            return True
        except Exception as e:
            logger.error(f"Failed to delete {path}: {e}")
            return False

    def move_item(self, src: str, dest: str):
        try:
            shutil.move(src, dest)
            logger.info(f"Moved {src} to {dest}")
            return True
        except Exception as e:
            logger.error(f"Failed to move {src} to {dest}: {e}")
            return False

    def copy_item(self, src: str, dest: str):
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
            logger.info(f"Copied {src} to {dest}")
            return True
        except Exception as e:
            logger.error(f"Failed to copy {src} to {dest}: {e}")
            return False

    def rename_item(self, src: str, new_name: str):
        try:
            ext = os.path.splitext(src)[1]
            if "." not in new_name:
                new_name += ext
                
            dest = os.path.join(os.path.dirname(src), new_name)
            os.rename(src, dest)
            logger.info(f"Renamed {src} to {dest}")
            return True
        except Exception as e:
            logger.error(f"Failed to rename {src} to {new_name}: {e}")
            return False

    def open_item(self, path: str):
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
            logger.info(f"Opened item: {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to open item {path}: {e}")
            return False

    def get_file_info(self, path: str):
        try:
            stat = os.stat(path)
            return {
                "size": stat.st_size,
                "created": stat.st_ctime,
                "modified": stat.st_mtime,
                "is_file": os.path.isfile(path),
                "is_dir": os.path.isdir(path)
            }
        except Exception as e:
            logger.error(f"Failed to get info for {path}: {e}")
            return None

    def list_directory(self, path: str):
        try:
            if os.path.isdir(path):
                return os.listdir(path)
            return []
        except Exception as e:
            logger.error(f"Failed to list directory {path}: {e}")
            return []

    def close_item(self, path: str):
        path = os.path.normpath(path)
        try:
            import win32com.client
            shell = win32com.client.Dispatch("Shell.Application")
            closed_explorer = False
            for window in shell.Windows():
                try:
                    if window.Name in ["File Explorer", "Windows Explorer"]:
                        window_path = os.path.normpath(window.Document.Folder.Self.Path)
                        if window_path.lower() == path.lower():
                            window.Quit()
                            closed_explorer = True
                except Exception:
                    pass
            
            if closed_explorer:
                logger.info(f"Closed folder window for: {path}")
                return True
                
            # If not closed or it's a file, try to find window by title
            basename = os.path.basename(path)
            if not basename:
                basename = path # fallback if it's just a drive letter
                
            import win32gui
            import win32con
            
            closed_window = False
            def enum_windows_callback(hwnd, ctx):
                nonlocal closed_window
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if basename.lower() in title.lower():
                        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                        closed_window = True
                        
            win32gui.EnumWindows(enum_windows_callback, None)
            
            if closed_window:
                logger.info(f"Closed window matching: {basename}")
                return True
            else:
                logger.warning(f"Could not find an open window for: {path}")
                return False
                
        except ImportError:
            logger.error("win32com or win32gui not available.")
            return False
        except Exception as e:
            logger.error(f"Failed to close item {path}: {e}")
            return False
