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
from modules.filesystem.fs_utils import get_drives, close_explorer_window
from modules.filesystem.fs_db import FSDatabase
from modules.filesystem.fs_indexer import FSIndexer
from modules.security.manager import SecurityManager

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
                # Reclaim resources if no other thread is waiting
                if self._metrics[key]["wait_count"] <= 0:
                    self._locks.pop(key, None)
                    self._metrics.pop(key, None)

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
    """
    FileManager coordinates local disk operations, file matching, and search history logs.

    SYSTEM PROMPT:
    Use FileManager to handle single file management, reads, writes, searches, and path resolutions. Always resolve query names fuzzy-matched aliases.

    SHORT DESCRIPTION:
    Handles creation, deletion, moving, indexing, and fuzzy searching of system files with SQLite logs tracking.

    PROCESS:
    1. Indexes folders in background using SQLite database storage.
    2. Parses natural language queries into target directories, dates, extensions, and sorted filters.
    3. Resolves files by query keyword, querying Windows Search, Everything DLL, SQLite caches, or parallel disk walks.
    4. Handles CRUD options on target paths using custom thread locks.

    FLOW:
    Caller -> search_file() / create_file() -> resolve_path() -> SQLite caches / thread locks / OS filesystem API -> Caller
    """
    def __init__(self, db_path: str = None, security_manager=None):
        if db_path is None:
            from config.settings import DATA_DIR
            os.makedirs(DATA_DIR, exist_ok=True)
            db_path = os.path.join(DATA_DIR, "file_manager.db")
        self.db_path = db_path
        self.db = FSDatabase(self.db_path)
        self.background_task = None
        self.indexer = FSIndexer(self.db)
        from modules.filesystem.provider_search import ProviderSearch
        self.provider_search = ProviderSearch(self.db)
        from modules.filesystem.learning_engine import LearningEngine
        self.learning_engine = LearningEngine(self.db)
        self.lock_manager = ResourceLockManager()
        self._path_cache = {}
        self._indexer_started = False
        logger.info(f"FileManager initialized with DB: {db_path}")
        from modules.security.manager import SecurityManager
        self._security = security_manager or SecurityManager()


    def log_file_access(self, path: str):
        self.db.log_access(path, datetime.now().isoformat())


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
            
        # Detect target directory (Drive or Downloads folder)
        drive_match = re.search(r'\b(?:in\s+|on\s+|to\s+)?([a-zA-Z])\s*:\s*(?:\\|/)?', query_lower)
        if not drive_match:
            drive_match = re.search(r'\b(?:in\s+|on\s+|to\s+)?([a-zA-Z])\s+drive\b', query_lower)
        if not drive_match:
            drive_match = re.search(r'\bdrive\s+([a-zA-Z])\b', query_lower)
            
        if drive_match:
            drive_letter = drive_match.group(1).upper()
            filters["target_dir"] = f"{drive_letter}:\\"
            query_lower = re.sub(r'\b(?:in\s+|on\s+|to\s+)?' + re.escape(drive_match.group(0)) + r'\b', '', query_lower)
            query_lower = re.sub(r'\b[a-zA-Z]\s+drive\b', '', query_lower)
            query_lower = re.sub(r'\bdrive\s+[a-zA-Z]\b', '', query_lower)
            query_lower = re.sub(r'\b[a-zA-Z]:(?:\\|/)?', '', query_lower)
        elif any(w in query_lower for w in ["downloaded", "downloads", "download"]):
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
        if getattr(self, '_indexer_started', False):
            return
        self._indexer_started = True
        self.indexer.start_background_indexer(root_paths)

    def generate_query_variants(self, query: str) -> list:
        variants = []
        q = query.strip()
        if not q:
            return variants
            
        try:
            from unidecode import unidecode
            q_unidecode = unidecode(q)
        except ImportError:
            q_unidecode = q
            
        for base_q in set([q, q_unidecode]):
            variants.append(base_q)
            variants.append(base_q.lower())
            norm = re.sub(r'[\-_\.]+', ' ', base_q)
            norm = re.sub(r'\s+', ' ', norm).strip()
            if norm not in variants:
                variants.append(norm)
            stripped = re.sub(r'\s+', '', norm)
            if stripped not in variants:
                variants.append(stripped)
            variants.append(norm.replace(' ', '_'))
            variants.append(norm.replace(' ', '-'))
            variants.append(norm.replace(' ', '.'))
            tokens = norm.split()
            if 1 < len(tokens) <= 4:
                variants.append(" ".join(reversed(tokens)))
            if len(tokens) >= 2:
                variants.append("".join([t[0] for t in tokens if t]))
                
        try:
            import jellyfish
            # Add phonetic representations if appropriate (for english-like words)
            phonetic = jellyfish.metaphone(q)
            if phonetic and phonetic not in variants:
                variants.append(phonetic)
            soundex = jellyfish.soundex(q)
            if soundex and soundex not in variants:
                variants.append(soundex)
        except ImportError:
            pass
            
        seen = set()
        unique_variants = []
        for v in variants:
            if v and v not in seen:
                seen.add(v)
                unique_variants.append(v)
        return unique_variants[:20]

    def _search_sqlite_cache(self, filename: str, extensions: list = None, target_dir: str = None, date_filter: str = None, limit: int = 100) -> list:
        return self.db.search_cache(filename, extensions, target_dir, date_filter, limit)

    def _search_threaded_scan(self, variants: list, root_dir: str = None, limit: int = 100, extensions: list = None) -> list:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        search_paths = [root_dir] if root_dir else get_drives()
        ignore_dirs = {'.git', 'node_modules', 'venv', 'AppData', 'Windows', 'Program Files', 'Program Files (x86)', '__pycache__', 'Temp', 'Local', 'Roaming'}
        results = []
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
                        if entry.is_file(follow_symlinks=False):
                            if any(v in name_without_ext for v in variants):
                                folder_results.append(entry.path)
                        elif entry.is_dir(follow_symlinks=False) and entry.name not in ignore_dirs:
                            subfolders.append(entry.path)
                subfolders.sort(key=lambda f: 0 if any(v in os.path.basename(f).lower() for v in variants) else 1)
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
                    to_scan = subfolders + to_scan
                    if len(results) >= limit:
                        break
        return results

    def _rank_results(self, paths: list, keyword: str, extensions: list = None, sort_by: str = None, source_metadata: dict = None) -> list:
        """Scores and ranks file path matches based on fuzzy similarity, recency, workspace location, and history."""
        if not paths:
            return []
            
        ranked_results = []
        keyword_lower = keyword.lower() if keyword else ""
        workspace = os.path.normpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).lower()
        
        # Load open history from SQLite database
        history = self.db.get_history()
            
                
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
            
            # 5. Source confidence & Alias confidence
            alias_conf = 0.0
            source_conf = 0.0
            if source_metadata and path in source_metadata:
                meta = source_metadata[path]
                alias_conf = meta.get("alias_confidence", 0.0)
                src = meta.get("source", "unknown")
                if src in ("index", "alias"):
                    source_conf = 100.0
                elif src == "priority_scan":
                    source_conf = 75.0
                elif src == "drive_scan":
                    source_conf = 55.0
                elif src == "terminal":
                    source_conf = 35.0
                
            # Combine score parts using dynamic weights
            w = self.learning_engine.state.get("weights", {
                "fuzzy_score": 0.35, "recency_score": 0.15, "history_boost": 0.15, 
                "alias_confidence": 0.20, "source_confidence": 0.15
            })
            score = (fuzzy_score * w.get("fuzzy_score", 0.35)) \
                  + (recency_score * w.get("recency_score", 0.15)) \
                  + (history_boost * w.get("history_boost", 0.15)) \
                  + (alias_conf * w.get("alias_confidence", 0.20)) \
                  + (source_conf * w.get("source_confidence", 0.15))
            
            # NLP modifier overrides
            if sort_by == "modified_desc":
                score = (recency_score * 0.75) + (fuzzy_score * 0.25)
            elif sort_by == "access_desc":
                score = (history_boost * 0.75) + (fuzzy_score * 0.25)
                
            ranked_results.append((score, path))
            
        ranked_results.sort(key=lambda x: x[0], reverse=True)
        return ranked_results

    def search_file(self, filename: str, root_dir: str = None, limit: int = 5, extensions: list = None, target_dir: str = None, date_filter: str = None, sort_by: str = None) -> list:
        logger.info(f"Searching for item '{filename}'...")
        self.start_background_indexer()
        
        parsed = self.parse_nlp_query(filename)
        search_keyword = parsed["clean_query"] if parsed["clean_query"] else filename
        search_exts = extensions if extensions else parsed["extensions"]
        search_dir = root_dir if root_dir else (target_dir if target_dir else parsed["target_dir"])
        if search_dir and re.match(r'^[a-zA-Z]:$', search_dir.strip()):
            search_dir = search_dir.strip() + '\\'
        search_date = date_filter if date_filter else parsed["date_filter"]
        search_sort = sort_by if sort_by else parsed["sort_by"]
        
        variants = self.generate_query_variants(search_keyword)
        # Adaptively cap variants based on query length/complexity
        if len(search_keyword.split()) > 3:
            variants = variants[:5]
        else:
            variants = variants[:12]
            
        results = []
        source_metadata = {}
        
        # 1. Try Windows Search Index, Everything SDK, Local SQLite cache
        from concurrent.futures import ThreadPoolExecutor
        
        for provider in [self.provider_search.search_windows_index, self.provider_search.search_everything, self._search_sqlite_cache]:
            provider_results = []
            
            if provider == self.provider_search.search_everything:
                # Everything SDK DLL is not thread-safe; query sequentially
                for variant in variants:
                    try:
                        res = provider(filename=variant, extensions=search_exts, target_dir=search_dir, date_filter=search_date, limit=100)
                        if res:
                            for r in res:
                                if r not in provider_results:
                                    provider_results.append(r)
                            # Short-circuit: exact filename match found
                            if any(
                                os.path.splitext(os.path.basename(r))[0].lower() == variant.lower()
                                for r in res
                            ):
                                logger.info(f"Exact filename match on variant '{variant}'; stopping variant loop.")
                                break
                    except Exception as e:
                        logger.debug(f"Everything SDK variant search failed: {e}")
            else:
                # Windows Index and SQLite cache are thread-safe or locked; query concurrently
                with ThreadPoolExecutor(max_workers=min(len(variants), 8)) as executor:
                    futures = {
                        executor.submit(
                            provider,
                            filename=variant,
                            extensions=search_exts,
                            target_dir=search_dir,
                            date_filter=search_date,
                            limit=100
                        ): variant for variant in variants
                    }
                    for future in futures:
                        try:
                            res = future.result()
                            if res:
                                for r in res:
                                    if r not in provider_results:
                                        provider_results.append(r)
                        except Exception as e:
                            logger.debug(f"Provider search variant failed: {e}")
            
            if provider_results:
                for r in provider_results:
                    if r not in results:
                        results.append(r)
                        source_metadata[r] = {"source": "index", "alias_confidence": 0.0}
                
                # Dynamic early exit check
                provider_ranked = self._rank_results(paths=provider_results, keyword=search_keyword, extensions=search_exts, sort_by=search_sort, source_metadata=source_metadata)
                if provider_ranked and provider_ranked[0][0] > 85.0:
                    logger.info(f"Confident match found (score {provider_ranked[0][0]:.1f}); exiting provider loop early.")
                    break
        
        # 2. Fuzzy sweep if nothing matched
        if not results:
            from rapidfuzz import process, fuzz
            all_cache_files = self.db.get_all_filenames(target_dir=search_dir, extensions=search_exts)
            valid_paths = {f[0]: f[1] for f in all_cache_files}
            if valid_paths:
                extracted = process.extract(search_keyword, valid_paths, processor=lambda x: os.path.splitext(x.lower())[0], scorer=fuzz.WRatio, limit=50)
                for match in extracted:
                    if match[1] >= 60:
                        results.append(match[2])
                        source_metadata[match[2]] = {"source": "index", "alias_confidence": 0.0}
        
        # 3. Fallback to Threaded Scanning
        if not results:
            results = self._search_threaded_scan(variants=variants, root_dir=search_dir, limit=100, extensions=search_exts)
            for r in results:
                source_metadata[r] = {"source": "drive_scan", "alias_confidence": 0.0}
            
        # 4. Terminal / CLI Fallback
        if not results:
            for variant in variants:
                cli_res = self.provider_search.search_cli_fallback(variant, root_dir=search_dir)
                if cli_res:
                    for r in cli_res:
                        if r not in results:
                            results.append(r)
                            source_metadata[r] = {"source": "terminal", "alias_confidence": 0.0}
                    break
                    
        # Rank results
        ranked_results = self._rank_results(paths=results, keyword=search_keyword, extensions=search_exts, sort_by=search_sort, source_metadata=source_metadata)
        
        final_paths = []
        for score, path in ranked_results:
            if os.path.exists(path):
                final_paths.append(path)
                
        # Record outcome in learning engine
        outcome = "success" if final_paths else "not_found"
        best_match = final_paths[0] if final_paths else ""
        self.learning_engine.record(filename, best_match, "search_pipeline", 85.0 if final_paths else 0.0, outcome=outcome)
        
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
            if cached_path is None:
                return None
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
        
        # Direct check for target_dir + search_keyword if target drive/folder was parsed
        if parsed.get("target_dir") and search_keyword:
            candidate_path = os.path.normpath(os.path.join(parsed["target_dir"], search_keyword))
            if os.path.exists(candidate_path):
                self._path_cache[query] = candidate_path
                self.log_file_access(candidate_path)
                return candidate_path
        
        # Search for candidates using parsed filters
        results = self.search_file(
            search_keyword,
            root_dir=parsed.get("target_dir"),
            extensions=parsed.get("extensions"),
            date_filter=parsed.get("date_filter"),
            sort_by=parsed.get("sort_by"),
            limit=5
        )
        if not results:
            # If target_dir was specified on a valid drive, return candidate path for creation/resolution
            if parsed.get("target_dir") and search_keyword and os.path.exists(parsed["target_dir"]):
                candidate_path = os.path.normpath(os.path.join(parsed["target_dir"], search_keyword))
                return candidate_path
            self._path_cache[query] = None
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
            if not self._security.is_safe_path(path):
                return "Error: Security Policy blocks modification of protected system path."
            
            # Auto-format JSON content if applicable
            if isinstance(content, str):
                trimmed = content.strip()
                if (trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]")):
                    try:
                        import json
                        parsed = json.loads(trimmed)
                        if isinstance(parsed, (list, dict)):
                            content = json.dumps(parsed, indent=2, ensure_ascii=False)
                    except Exception:
                        pass

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
            if not self._security.is_safe_path(path):
                return "Error: Security Policy blocks reading of protected system path."
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
            if not self._security.is_safe_path(path):
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
            
            if not self._security.is_safe_path(src) or not self._security.is_safe_path(dest):
                return "Error: Security Policy blocks moving system folder/file."
                
            if os.path.isdir(src):
                return "Error: Source path is a directory, not a file."
                
            def _execute_move():
                try:
                    with self.lock_manager.lock_resources([('file', src), ('file', dest)]):
                        if os.path.exists(dest):
                            send2trash(dest)
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
                    if os.path.exists(dest):
                        send2trash(dest)
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
            
            if not self._security.is_safe_path(src) or not self._security.is_safe_path(dest):
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
            if not self._security.is_safe_path(src):
                return "Error: Security Policy blocks modification of protected system folder/file."
                
            if os.path.isdir(src):
                return "Error: Source path is a directory, not a file."
                
            ext = os.path.splitext(src)[1]
            if "." not in new_name:
                new_name += ext
                
            dest = os.path.join(os.path.dirname(src), new_name)
            if not self._security.is_safe_path(dest):
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

    def open_item(self, path: str, app_name: str = None):
        try:
            path = os.path.normpath(os.path.abspath(path))
            if not os.path.exists(path):
                return f"Error: Path does not exist: {path}"
            if not self._security.is_safe_path(path):
                return "Error: Security Policy blocks opening of protected system path."
            
            if app_name:
                from modules.controls.app_controller import AppController
                success = AppController().open_file_with_app(app_name, path)
                if success:
                    self.log_file_access(path)
                    return True
                else:
                    return f"Failed to open '{path}' with {app_name}."

            # Focus existing window if open
            if self._focus_existing_window(path):
                logger.info(f"Focused existing window for path: {path}")
                return True
                
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.call(('open', path))
            else:
                subprocess.call(('xdg-open', path))
            self.log_file_access(path)
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

    def close(self):
        if hasattr(self, 'learning_engine') and self.learning_engine:
            try:
                self.learning_engine.close()
            except Exception as e:
                logger.error(f"Failed to close learning_engine: {e}")
        if hasattr(self, 'indexer') and self.indexer:
            try:
                self.indexer.stop_realtime_observer()
            except Exception as e:
                logger.error(f"Failed to stop indexer observer: {e}")
        if hasattr(self, 'db') and self.db:
            try:
                self.db.close()
            except Exception as e:
                logger.error(f"Failed to close db: {e}")

