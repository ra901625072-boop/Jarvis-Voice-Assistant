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
import contextlib
from datetime import datetime, timedelta
from rapidfuzz import fuzz
from send2trash import send2trash
from modules.filesystem.fs_utils import get_drives, is_safe_path, close_explorer_window

logger = logging.getLogger("JARVIS.FileManager")

class LockTimeoutError(TimeoutError):
    pass

class ResourceLockManager:
    def __init__(self):
        self._locks = {}
        self._master_lock = threading.Lock()
        self._metrics = {}

    def _get_key(self, resource_type: str, path: str) -> str:
        norm_path = os.path.normpath(os.path.abspath(path)).lower()
        return f"{resource_type}:{norm_path}"

    @contextlib.contextmanager
    def lock(self, resource_type: str, path: str, timeout: float = 30.0):
        key = self._get_key(resource_type, path)
        with self._master_lock:
            if key not in self._locks:
                self._locks[key] = threading.RLock()
            lock = self._locks[key]
            if key not in self._metrics:
                self._metrics[key] = {
                    "resource": key,
                    "owner_thread": None,
                    "acquired_at": None,
                    "hold_duration": 0.0,
                    "wait_count": 0
                }
            self._metrics[key]["wait_count"] += 1

        start_wait = time.time()
        acquired = lock.acquire(timeout=timeout)
        if not acquired:
            with self._master_lock:
                self._metrics[key]["wait_count"] -= 1
            raise LockTimeoutError(f"Failed to acquire lock for {key} within {timeout} seconds.")

        acquired_at = time.time()
        current_thread_name = threading.current_thread().name
        with self._master_lock:
            self._metrics[key]["owner_thread"] = current_thread_name
            self._metrics[key]["acquired_at"] = acquired_at
            self._metrics[key]["wait_count"] -= 1

        try:
            yield
        finally:
            hold_dur = time.time() - acquired_at
            with self._master_lock:
                self._metrics[key]["hold_duration"] += hold_dur
                self._metrics[key]["owner_thread"] = None
                self._metrics[key]["acquired_at"] = None
            lock.release()

    @contextlib.contextmanager
    def lock_resources(self, resources_list: list, timeout: float = 30.0):
        canonical_keys = {}
        for r_type, path in resources_list:
            key = self._get_key(r_type, path)
            canonical_keys[key] = (r_type, path)
        sorted_keys = sorted(canonical_keys.keys())
        with contextlib.ExitStack() as stack:
            for key in sorted_keys:
                r_type, path = canonical_keys[key]
                stack.enter_context(self.lock(r_type, path, timeout=timeout))
            yield

    def active_locks(self) -> dict:
        with self._master_lock:
            return {
                key: metrics
                for key, metrics in self._metrics.items()
                if metrics["owner_thread"] is not None
            }

class LegacyLockWrapper:
    def __init__(self, lock_manager, resource_type, path):
        self.lock_manager = lock_manager
        self.resource_type = resource_type
        self.path = path
        self._local = threading.local()

    def __enter__(self):
        ctx = self.lock_manager.lock(self.resource_type, self.path)
        self._local.ctx = ctx
        return ctx.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        ctx = getattr(self._local, 'ctx', None)
        if ctx:
            ctx.__exit__(exc_type, exc_val, exc_tb)

class FileManager:
    def __init__(self, db_path: str = None):
        if db_path is None:
            # Resolve db in backend/database folder
            db_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "file_manager.db")
        self.db_path = db_path
        self.lock_manager = ResourceLockManager()
        self._db_lock = LegacyLockWrapper(self.lock_manager, 'db', self.db_path)
        self._init_db()
        self._path_cache = {}
        
        # Start background indexer for workspace and key folders
        self.start_background_indexer()
        logger.info(f"FileManager initialized with DB: {db_path}")

    def _init_db(self):
        """Initializes the SQLite database tables."""
        with self._db_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                
                # History of opened / modified files
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS file_history (
                        path TEXT PRIMARY KEY,
                        filename TEXT NOT NULL,
                        open_count INTEGER DEFAULT 1,
                        last_opened TEXT NOT NULL
                    )
                """)
                
                # Local index cache of files
                conn.execute("""
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
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to initialize database: {e}")
            finally:
                conn.close()

    def log_file_access(self, path: str):
        """Logs a file access event to SQLite for search memory and ranking."""
        try:
            path = os.path.normpath(os.path.abspath(path))
            filename = os.path.basename(path)
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
                    logger.error(f"Failed to log file access for {path}: {e}")
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"Error logging file access: {e}")


    def parse_nlp_query(self, query: str) -> dict:
        """Parses natural language requests into structured filters."""
        query_lower = query.lower()
        filters = {
            "clean_query": "",
            "extensions": [],
            "date_filter": None,
            "sort_by": None,
            "target_dir": None
        }
        
        # Detect sorting/recency
        if any(w in query_lower for w in ["latest", "newest", "recent"]):
            filters["sort_by"] = "modified_desc"
            
        # Detect date filter
        if "today" in query_lower:
            filters["date_filter"] = "today"
        elif "yesterday" in query_lower:
            filters["date_filter"] = "yesterday"
            
        # Detect target directory (Downloads folder)
        if any(w in query_lower for w in ["downloaded", "downloads", "download"]):
            filters["target_dir"] = os.path.join(os.path.expanduser("~"), "Downloads")
            
        # Detect file type / extensions mapping
        extension_map = {
            "pdf": [".pdf"],
            "docx": [".docx", ".doc"],
            "word": [".docx", ".doc"],
            "xlsx": [".xlsx", ".xls"],
            "excel": [".xlsx", ".xls"],
            "csv": [".csv"],
            "txt": [".txt"],
            "text": [".txt"],
            "png": [".png"],
            "jpg": [".jpg", ".jpeg"],
            "jpeg": [".jpeg", ".jpg"],
            "image": [".png", ".jpg", ".jpeg", ".gif"],
            "photo": [".png", ".jpg", ".jpeg"],
            "zip": [".zip", ".rar"],
            "rar": [".rar", ".zip"],
            "archive": [".zip", ".rar", ".7z"],
            "pptx": [".pptx", ".ppt"],
            "powerpoint": [".pptx", ".ppt"]
        }
        
        for word, exts in extension_map.items():
            if re.search(r'\b' + re.escape(word) + r'\b', query_lower):
                filters["extensions"].extend(exts)
                
        # Clean the query of all metadata modifiers and filler words
        fillers = [
            r"\bopen\b", r"\bmy\b", r"\bthe\b", r"\bshow\b", r"\bview\b", r"\bfind\b", r"\bget\b", r"\bplease\b",
            r"\blatest\b", r"\bnewest\b", r"\brecent\b", r"\btoday(?:'s)?\b", r"\byesterday(?:'s)?\b",
            r"\bdownloaded\b", r"\bdownloads?\b", r"\bfiles?\b", r"\bfolders?\b", r"\blast\b", r"\bme\b",
            r"\bnamed\b", r"\bfrom\b", r"\bsearch\b", r"\bfor\b", r"\band\b", r"\bwith\b"
        ]
        for filler in fillers:
            query_lower = re.sub(filler, "", query_lower)
            
        for word in extension_map.keys():
            query_lower = re.sub(r'\b' + re.escape(word) + r'\b', "", query_lower)
            
        # Strip special characters and clean multiple spaces
        query_lower = re.sub(r'[^\w\s\-\.]', ' ', query_lower)
        query_lower = re.sub(r'\s+', ' ', query_lower).strip()
        
        filters["clean_query"] = query_lower
        return filters

    def start_background_indexer(self, root_paths: list = None):
        """Launches directory crawling to cache files in SQLite."""
        if root_paths is None:
            # Project root workspace
            workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            root_paths = [workspace]
            
            # User key folders
            user_profile = os.environ.get("USERPROFILE")
            if user_profile:
                for folder in ["Documents", "Desktop", "Downloads"]:
                    folder_path = os.path.join(user_profile, folder)
                    if os.path.exists(folder_path):
                        root_paths.append(folder_path)
                        
        thread = threading.Thread(target=self._background_index_task, args=(root_paths,), daemon=True)
        thread.start()

    def _background_index_task(self, root_paths: list):
        """Walks folders to update sqlite cache."""
        ignore_dirs = {'.git', 'node_modules', 'venv', 'AppData', 'Windows', 'Program Files', 'Program Files (x86)', '__pycache__', 'Temp', 'Local', 'Roaming'}
        chunk_size = 500
        batch = []
        
        for root_path in root_paths:
            if not os.path.exists(root_path):
                continue
            for root, dirs, files in os.walk(root_path):
                # Prune ignored folders
                dirs[:] = [d for d in dirs if d not in ignore_dirs]
                
                for name in files + dirs:
                    path = os.path.join(root, name)
                    try:
                        stat = os.stat(path)
                        filename_lower = name.lower()
                        ext = os.path.splitext(filename_lower)[1]
                        is_dir = 1 if os.path.isdir(path) else 0
                        batch.append((
                            os.path.normpath(path),
                            name,
                            filename_lower,
                            ext,
                            stat.st_mtime,
                            stat.st_size,
                            is_dir
                        ))
                    except (PermissionError, FileNotFoundError, OSError):
                        continue
                        
                    if len(batch) >= chunk_size:
                        self._save_cache_batch(batch)
                        batch = []
                        time.sleep(0.02) # Yield execution for system responsiveness
                        
            if batch:
                self._save_cache_batch(batch)
                batch = []
        logger.info("Background file index completed indexing.")

    def _save_cache_batch(self, batch: list):
        with self._db_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.executemany("""
                    INSERT OR REPLACE INTO file_cache (path, filename, filename_lower, extension, last_modified, size, is_dir)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, batch)
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to save index batch to database: {e}")
            finally:
                conn.close()

    def _search_everything(self, query: str, limit: int = 100) -> list:
        """Queries Everything SDK via ctypes DLL."""
        results = []
        try:
            import ctypes
            try:
                everything = ctypes.windll.Everything64
            except (OSError, AttributeError):
                try:
                    everything = ctypes.CDLL("Everything64.dll")
                except OSError:
                    return []
            
            everything.Everything_SetSearchW.argtypes = [ctypes.c_wchar_p]
            everything.Everything_SetSearchW.restype = None
            everything.Everything_QueryW.argtypes = [ctypes.c_bool]
            everything.Everything_QueryW.restype = ctypes.c_bool
            everything.Everything_GetNumResults.argtypes = []
            everything.Everything_GetNumResults.restype = ctypes.c_uint32
            everything.Everything_GetResultFullPathNameW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_uint32]
            everything.Everything_GetResultFullPathNameW.restype = None
            
            everything.Everything_SetSearchW(query)
            if not everything.Everything_QueryW(True):
                return []
                
            num_results = everything.Everything_GetNumResults()
            count = min(num_results, limit)
            
            buf_size = 4096
            buf = ctypes.create_unicode_buffer(buf_size)
            
            for i in range(count):
                everything.Everything_GetResultFullPathNameW(i, buf, buf_size)
                path = buf.value
                if path:
                    results.append(path)
        except Exception as e:
            logger.debug(f"Everything SDK search unavailable: {e}")
        return results

    def _search_windows_index(self, filename: str, extensions: list = None, target_dir: str = None, date_filter: str = None, limit: int = 100) -> list:
        """Queries Windows Search Index database via ADODB."""
        results = []
        if platform.system() != "Windows":
            return []
            
        try:
            import win32com.client
            conn = win32com.client.Dispatch("ADODB.Connection")
            conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
            recordset = win32com.client.Dispatch("ADODB.Recordset")
            
            select_clause = f"SELECT TOP {limit} System.ItemPathDisplay"
            from_clause = "FROM SystemIndex"
            
            where_conditions = ["Scope='file:'"]
            
            if filename:
                where_conditions.append(f"System.ItemName LIKE '%{filename}%'")
                
            if extensions:
                ext_conditions = []
                for ext in extensions:
                    ext_val = ext.lower() if ext.startswith('.') else f".{ext.lower()}"
                    ext_conditions.append(f"System.FileExtension = '{ext_val}'")
                if ext_conditions:
                    where_conditions.append("(" + " OR ".join(ext_conditions) + ")")
                    
            if target_dir:
                target_dir_norm = os.path.normpath(target_dir).replace("\\", "/")
                where_conditions.append(f"directory='file:{target_dir_norm}'")
                
            if date_filter:
                now = datetime.now()
                if date_filter == "today":
                    today_str = now.strftime("%Y-%m-%d 00:00:00")
                    where_conditions.append(f"System.DateModified >= '{today_str}'")
                elif date_filter == "yesterday":
                    yesterday = now - timedelta(days=1)
                    yesterday_start = yesterday.strftime("%Y-%m-%d 00:00:00")
                    yesterday_end = yesterday.strftime("%Y-%m-%d 23:59:59")
                    where_conditions.append(f"System.DateModified >= '{yesterday_start}' AND System.DateModified <= '{yesterday_end}'")
                    
            where_clause = "WHERE " + " AND ".join(where_conditions)
            query = f"{select_clause} {from_clause} {where_clause}"
            
            recordset.Open(query, conn)
            while not recordset.EOF:
                path = recordset.Fields.Item("System.ItemPathDisplay").Value
                if path:
                    results.append(path)
                recordset.MoveNext()
                
            recordset.Close()
            conn.Close()
            
            seen = set()
            unique_results = []
            for r in results:
                norm_p = os.path.normpath(r)
                if norm_p not in seen:
                    seen.add(norm_p)
                    unique_results.append(norm_p)
            return unique_results
        except Exception as e:
            logger.warning(f"Windows Search Index query failed: {e}")
            return []

    def _search_sqlite_cache(self, filename: str, extensions: list = None, target_dir: str = None, date_filter: str = None, limit: int = 100) -> list:
        """Queries local sqlite database index cache."""
        results = []
        with self._db_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.cursor()
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
            finally:
                conn.close()
        return results

    def _search_threaded_scan(self, filename: str, root_dir: str = None, limit: int = 100, extensions: list = None) -> list:
        """Parallel, threaded directory crawler fallback."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        search_paths = [root_dir] if root_dir else get_drives()
        ignore_dirs = {'.git', 'node_modules', 'venv', 'AppData', 'Windows', 'Program Files', 'Program Files (x86)', '__pycache__', 'Temp', 'Local', 'Roaming'}
        
        results = []
        filename = filename.lower()
        
        if extensions:
            extensions = [ext.lower() if ext.startswith('.') else f".{ext.lower()}" for ext in extensions]
            
        def scan_folder(folder_path):
            folder_results = []
            subfolders = []
            try:
                with os.scandir(folder_path) as it:
                    for entry in it:
                        name_lower = entry.name.lower()
                        name_without_ext, ext = os.path.splitext(name_lower)
                        
                        if extensions and entry.is_file(follow_symlinks=False):
                            if ext not in extensions:
                                continue
                                
                        if filename in name_without_ext:
                            folder_results.append(entry.path)
                            
                        if entry.is_dir(follow_symlinks=False) and entry.name not in ignore_dirs:
                            subfolders.append(entry.path)
                return folder_results, subfolders
            except (PermissionError, OSError):
                return [], []

        to_scan = list(search_paths)
        scanned_count = 0
        max_scanned = 5000
        
        with ThreadPoolExecutor(max_workers=8) as executor:
            while to_scan and len(results) < limit and scanned_count < max_scanned:
                futures = {executor.submit(scan_folder, folder): folder for folder in to_scan[:50]}
                to_scan = to_scan[50:]
                
                for future in as_completed(futures):
                    scanned_count += 1
                    folder_results, subfolders = future.result()
                    results.extend(folder_results)
                    to_scan.extend(subfolders)
                    if len(results) >= limit:
                        break
                        
        return results

    def _rank_results(self, paths: list, keyword: str, extensions: list = None, sort_by: str = None) -> list:
        """Scores and ranks file path matches based on fuzzy similarity, recency, workspace location, and history."""
        if not paths:
            return []
            
        ranked_results = []
        keyword_lower = keyword.lower() if keyword else ""
        workspace = os.path.normpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).lower()
        
        # Load open history from SQLite database
        history = {}
        with self._db_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT path, open_count, last_opened FROM file_history")
                for row in cursor.fetchall():
                    history[row[0]] = {"count": row[1], "last_opened": row[2]}
            except Exception as e:
                logger.warning(f"Failed to fetch history for ranking: {e}")
            finally:
                conn.close()
                
        now = time.time()
        file_details = []
        for path in paths:
            try:
                stat = os.stat(path)
                mtime = stat.st_mtime
            except Exception as e:
                logger.debug(f"Failed to get mtime for {path}: {e}")
                mtime = 0
            file_details.append((path, mtime))
            
        max_mtime = max([item[1] for item in file_details]) if file_details else now
        min_mtime = min([item[1] for item in file_details]) if file_details else 0
        mtime_range = max_mtime - min_mtime if max_mtime > min_mtime else 1
        
        for path, mtime in file_details:
            name = os.path.basename(path)
            name_lower = name.lower()
            name_without_ext = os.path.splitext(name_lower)[0]
            
            # 1. Fuzzy matching score (0-100)
            if not keyword_lower:
                fuzzy_score = 100.0
            elif keyword_lower in name_without_ext:
                fuzzy_score = 90.0 + (len(keyword_lower) / len(name_without_ext) * 10.0)
            else:
                fuzzy_score = fuzz.ratio(keyword_lower, name_without_ext)
                
            # 2. File modified recency score (0-100)
            recency_score = ((mtime - min_mtime) / mtime_range) * 100.0 if mtime > 0 else 0.0
            
            # 3. Workspace location boost (0 or 100)
            workspace_boost = 100.0 if path.lower().startswith(workspace) else 0.0
            
            # 4. History boost based on usage count and open recency (0-100)
            history_boost = 0.0
            path_norm = os.path.normpath(path)
            if path_norm in history:
                hist = history[path_norm]
                count_boost = min(hist["count"] * 10, 50)
                try:
                    last_opened_ts = datetime.fromisoformat(hist["last_opened"]).timestamp()
                    recency_boost = max(0.0, 50.0 - (now - last_opened_ts) / 86400 * 5)
                except Exception as e:
                    logger.debug(f"Failed to parse last_opened timestamp for {path_norm}: {e}")
                    recency_boost = 0.0
                history_boost = count_boost + recency_boost
                
            # Combine score parts
            score = (fuzzy_score * 0.5) + (recency_score * 0.25) + (workspace_boost * 0.1) + (history_boost * 0.15)
            
            # NLP modifier overrides
            if sort_by == "modified_desc":
                score = (recency_score * 0.75) + (fuzzy_score * 0.25)
            elif sort_by == "access_desc":
                score = (history_boost * 0.75) + (fuzzy_score * 0.25)
                
            ranked_results.append((score, path))
            
        ranked_results.sort(key=lambda x: x[0], reverse=True)
        return ranked_results

    def search_file(self, filename: str, root_dir: str = None, limit: int = 5, extensions: list = None, target_dir: str = None, date_filter: str = None, sort_by: str = None) -> list:
        """
        Searches for a file or folder using fuzzy matching and multiple search providers.
        """
        logger.info(f"Searching for item '{filename}'...")
        
        parsed = self.parse_nlp_query(filename)
        search_keyword = parsed["clean_query"] if parsed["clean_query"] else filename
        search_exts = extensions if extensions else parsed["extensions"]
        search_dir = root_dir if root_dir else (target_dir if target_dir else parsed["target_dir"])
        search_date = date_filter if date_filter else parsed["date_filter"]
        search_sort = sort_by if sort_by else parsed["sort_by"]
        
        # 1. Try Windows Search Index (instant, PC-wide)
        results = self._search_windows_index(
            filename=search_keyword,
            extensions=search_exts,
            target_dir=search_dir,
            date_filter=search_date,
            limit=100
        )
        
        # 2. Try Everything SDK (DLL search)
        if not results:
            results = self._search_everything(search_keyword, limit=100)
            
        # 3. Try Local SQLite cache (background indexed files)
        if not results:
            results = self._search_sqlite_cache(
                filename=search_keyword,
                extensions=search_exts,
                target_dir=search_dir,
                date_filter=search_date,
                limit=100
            )
            
        # 4. Fallback to Threaded Scanning
        if not results:
            results = self._search_threaded_scan(
                filename=search_keyword,
                root_dir=search_dir,
                extensions=search_exts,
                limit=100
            )
            
        # Rank results
        ranked_results = self._rank_results(
            paths=results,
            keyword=search_keyword,
            extensions=search_exts,
            sort_by=search_sort
        )
        
        final_paths = []
        for score, path in ranked_results:
            if os.path.exists(path):
                final_paths.append(path)
                
        return final_paths[:limit]

    def resolve_path(self, query: str) -> str:
        """
        Resolves a natural language query like 'open resume' to an absolute path.
        Detects duplicates/ambiguity and returns multiple matches if found.
        """
        query = query.strip()
        
        # Check cache
        if query in self._path_cache:
            cached_path = self._path_cache[query]
            if isinstance(cached_path, list):
                valid_cached = [p for p in cached_path if os.path.exists(p)]
                if len(valid_cached) == 1:
                    return valid_cached[0]
                elif len(valid_cached) > 1:
                    return valid_cached
            elif os.path.exists(cached_path):
                return cached_path
            
        # Check if query itself is a valid path
        if os.path.exists(query):
            self._path_cache[query] = query
            self.log_file_access(query)
            return query
            
        # Parse query for NLP filters
        parsed = self.parse_nlp_query(query)
        search_keyword = parsed["clean_query"] if parsed["clean_query"] else query
        
        # Search for candidates
        results = self.search_file(query, limit=5)
        if not results:
            return None
            
        # Detect ambiguity: if multiple files match target search and have same name
        candidates = []
        first_name = os.path.basename(results[0]).lower()
        
        for r in results:
            name = os.path.basename(r).lower()
            if name == first_name or fuzz.ratio(name, first_name) > 90:
                candidates.append(r)
                
        if len(candidates) == 1:
            resolved_path = candidates[0]
            self._path_cache[query] = resolved_path
            self.log_file_access(resolved_path)
            return resolved_path
            
        # Store list of options in cache and return list for ambiguity handling
        self._path_cache[query] = candidates
        for c in candidates:
            self.log_file_access(c)
        return candidates


    def create_file(self, path: str, content: str = ""):
        try:
            path = os.path.normpath(os.path.abspath(path))
            if not is_safe_path(path):
                return "Error: Security Policy blocks modification of protected system path."
            with self.lock_manager.lock('file', path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            logger.info(f"Created file: {path}")
            return True
        except PermissionError:
            return "Error: Permission Denied. Unable to write to this location."
        except Exception as e:
            logger.error(f"Failed to create file {path}: {e}")
            return f"Error: {e}"

    def read_file(self, path: str):
        try:
            path = os.path.normpath(os.path.abspath(path))
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except PermissionError:
            return "Error: Permission Denied. You do not have permission to read this file."
        except Exception as e:
            logger.error(f"Failed to read file {path}: {e}")
            return f"Error: {e}"
            
    def write_file(self, path: str, content: str):
        return self.create_file(path, content)

    def delete_item(self, path: str):
        try:
            path = os.path.normpath(os.path.abspath(path))
            if not is_safe_path(path):
                return "Error: Security Policy blocks deletion of protected system folder/file."
            if os.path.isdir(path):
                return "Error: Path is a directory, not a file."
            with self.lock_manager.lock('file', path):
                send2trash(path)
            logger.info(f"Sent file {path} to recycle bin.")
            return True
        except PermissionError:
            return "Error: Permission Denied. Unable to delete this file."
        except Exception as e:
            logger.error(f"Failed to delete file {path}: {e}")
            return f"Error: {e}"

    def move_item(self, src: str, dest: str, force_sync: bool = False):
        """Moves a file, utilizing background thread if cross-drive & large."""
        try:
            src = os.path.normpath(os.path.abspath(src))
            dest = os.path.normpath(os.path.abspath(dest))
            
            if not is_safe_path(src) or not is_safe_path(dest):
                return "Error: Security Policy blocks moving system folder/file."
                
            if os.path.isdir(src):
                return "Error: Source path is a directory, not a file."
                
            def _execute_move():
                try:
                    with self.lock_manager.lock_resources([('file', src), ('file', dest)]):
                        if os.path.exists(dest):
                            if os.path.isdir(dest):
                                shutil.rmtree(dest)
                            else:
                                os.remove(dest)
                        shutil.move(src, dest)
                        logger.info(f"Background move complete: {src} to {dest}")
                        self.log_file_access(dest)
                except Exception as e:
                    logger.error(f"Background move failed: {e}")
            
            src_drive = os.path.splitdrive(src)[0].lower()
            dest_drive = os.path.splitdrive(dest)[0].lower()
            is_cross_drive = src_drive != dest_drive
            
            large_file = False
            if is_cross_drive:
                try:
                    large_file = os.path.getsize(src) > 50 * 1024 * 1024 # > 50MB
                except Exception as e:
                    logger.debug(f"Failed to get size for {src}: {e}")
            
            if is_cross_drive and large_file and not force_sync:
                logger.info(f"Starting background move: {src} to {dest}")
                threading.Thread(target=_execute_move, daemon=True).start()
                return "BackgroundProcessStarted"
            else:
                with self.lock_manager.lock_resources([('file', src), ('file', dest)]):
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.move(src, dest)
                    logger.info(f"Moved file {src} to {dest}")
                    self.log_file_access(dest)
                    return True
        except PermissionError:
            return "Error: Permission Denied. Unable to move file."
        except Exception as e:
            logger.error(f"Failed to move file {src} to {dest}: {e}")
            return f"Error: {e}"

    def copy_item(self, src: str, dest: str):
        try:
            src = os.path.normpath(os.path.abspath(src))
            dest = os.path.normpath(os.path.abspath(dest))
            
            if not is_safe_path(src) or not is_safe_path(dest):
                return "Error: Security Policy blocks copying to/from system directories."
                
            if not os.path.exists(src):
                return f"Error: Source path does not exist: {src}"
                
            if os.path.isdir(src):
                return "Error: Source path is a directory, not a file."
                
            resolved_dest = os.path.join(dest, os.path.basename(src)) if os.path.isdir(dest) else dest
            with self.lock_manager.lock_resources([('file', src), ('file', resolved_dest)]):
                if not os.path.isdir(dest):
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(src, resolved_dest)
                logger.info(f"Copied file {src} to {resolved_dest}")
                self.log_file_access(resolved_dest)
                return True
        except PermissionError:
            return "Error: Permission Denied. Unable to copy files."
        except Exception as e:
            logger.error(f"Failed to copy file {src} to {dest}: {e}")
            return f"Error: {e}"

    def rename_item(self, src: str, new_name: str):
        try:
            src = os.path.normpath(os.path.abspath(src))
            if not is_safe_path(src):
                return "Error: Security Policy blocks modification of protected system folder/file."
                
            if os.path.isdir(src):
                return "Error: Source path is a directory, not a file."
                
            ext = os.path.splitext(src)[1]
            if "." not in new_name:
                new_name += ext
                
            dest = os.path.join(os.path.dirname(src), new_name)
            if not is_safe_path(dest):
                return "Error: Security Policy blocks modification of protected system folder/file."
                
            with self.lock_manager.lock_resources([('file', src), ('file', dest)]):
                os.rename(src, dest)
            logger.info(f"Renamed file {src} to {dest}")
            return True
        except PermissionError:
            return "Error: Permission Denied. Unable to rename file."
        except Exception as e:
            logger.error(f"Failed to rename file {src} to {new_name}: {e}")
            return f"Error: {e}"

    def _focus_existing_window(self, path: str) -> bool:
        """Attempts to find and focus an already opened window matching the path."""
        if platform.system() != "Windows":
            return False
            
        try:
            import win32gui
            import win32con
            import win32com.client
            
            path_norm = os.path.normpath(os.path.abspath(path))
            
            # 1. Search open File Explorer windows
            try:
                shell = win32com.client.Dispatch("Shell.Application")
                for window in shell.Windows():
                    try:
                        if window.Name in ["File Explorer", "Windows Explorer"]:
                            window_path = os.path.normpath(window.Document.Folder.Self.Path)
                            if window_path.lower() == path_norm.lower():
                                hwnd = window.HWND
                                wscript = win32com.client.Dispatch("WScript.Shell")
                                wscript.SendKeys('%')
                                if win32gui.IsIconic(hwnd):
                                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                                else:
                                    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                                win32gui.SetForegroundWindow(hwnd)
                                return True
                    except Exception as e:
                        logger.debug(f"Ignored error during explorer window check: {e}")
            except Exception as e:
                logger.debug(f"Explorer focus check failed: {e}")
                
            # 2. General application window matching filename
            basename = os.path.basename(path_norm)
            if not basename:
                basename = path_norm
            basename_lower = basename.lower()
            
            hwnd_found = None
            def enum_windows_cb(hwnd, lparam):
                nonlocal hwnd_found
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd).lower()
                    if basename_lower in title:
                        hwnd_found = hwnd
                        return False
                return True
                
            win32gui.EnumWindows(enum_windows_cb, None)
            if hwnd_found:
                wscript = win32com.client.Dispatch("WScript.Shell")
                wscript.SendKeys('%')
                if win32gui.IsIconic(hwnd_found):
                    win32gui.ShowWindow(hwnd_found, win32con.SW_RESTORE)
                else:
                    win32gui.ShowWindow(hwnd_found, win32con.SW_SHOW)
                win32gui.SetForegroundWindow(hwnd_found)
                return True
        except Exception as e:
            logger.debug(f"Window focus check failed: {e}")
            
        return False

    def open_item(self, path: str):
        try:
            path = os.path.normpath(os.path.abspath(path))
            self.log_file_access(path)
            
            # Focus existing window if open
            if self._focus_existing_window(path):
                logger.info(f"Focused existing window for path: {path}")
                return True
                
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.run(["/usr/bin/open", path], check=False)
            else:
                subprocess.run(["/usr/bin/xdg-open", path], check=False)
            logger.info(f"Opened item: {path}")
            return True
        except PermissionError:
            return "Error: Permission Denied. You do not have permission to open this file/folder."
        except Exception as e:
            logger.error(f"Failed to open item {path}: {e}")
            return f"Error: {e}"

    def get_file_info(self, path: str):
        try:
            path = os.path.normpath(os.path.abspath(path))
            stat = os.stat(path)
            return {
                "size": stat.st_size,
                "created": stat.st_ctime,
                "modified": stat.st_mtime,
                "is_file": os.path.isfile(path),
                "is_dir": os.path.isdir(path)
            }
        except PermissionError:
            return "Error: Permission Denied. Unable to retrieve information for this path."
        except Exception as e:
            logger.error(f"Failed to get info for {path}: {e}")
            return None

    def close_item(self, path: str):
        path = os.path.normpath(os.path.abspath(path))
        try:
            if close_explorer_window(path):
                return True
                
            basename = os.path.basename(path)
            if not basename:
                basename = path
                
            import win32gui
            import win32con
            
            closed_window = False
            basename_lower = basename.lower()
            
            def enum_windows_callback(hwnd, ctx):
                nonlocal closed_window
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd).lower()
                    if basename_lower in title:
                        pattern = r'(?:^|[\s\-\|])' + re.escape(basename_lower) + r'(?:$|[\s\-\|])'
                        if re.search(pattern, title) or title == basename_lower:
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
