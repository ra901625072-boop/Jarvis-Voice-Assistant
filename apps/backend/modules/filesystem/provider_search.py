import os
import subprocess
import logging
from modules.security.manager import SecurityManager

logger = logging.getLogger("JARVIS.ProviderSearch")

class ProviderSearch:
    def __init__(self, db=None):
        self.db = db
        self._capability_cache = {
            "win_index": True,
            "everything": True
        }

    def search_windows_index(self, filename: str, extensions: list = None, target_dir: str = None, date_filter: str = None, limit: int = 100) -> list:
        if not self._capability_cache.get("win_index"):
            return []
            
        import platform
        if platform.system() != "Windows":
            self._capability_cache["win_index"] = False
            return []

        import win32com.client
        import pythoncom
        results = []
        try:
            pythoncom.CoInitialize()
            conn = win32com.client.Dispatch("ADODB.Connection")
            conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
            
            sql = "SELECT System.ItemPathDisplay FROM SystemIndex WHERE System.FileName LIKE '%" + filename + "%'"
            if target_dir:
                sql += f" AND System.ItemFolderPathDisplay LIKE '{target_dir}%'"
                
            rs = win32com.client.Dispatch("ADODB.Recordset")
            rs.Open(sql, conn)
            
            while not rs.EOF and len(results) < limit:
                path = rs.Fields.Item("System.ItemPathDisplay").Value
                if path and SecurityManager().is_safe_path(path):
                    if extensions:
                        ext = os.path.splitext(path)[1].lower()
                        if ext in extensions:
                            results.append(path)
                    else:
                        results.append(path)
                rs.MoveNext()
            rs.Close()
            conn.Close()
        except Exception as e:
            logger.debug(f"Windows Index Search failed, caching as unavailable: {e}")
            self._capability_cache["win_index"] = False
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
        return results

    def search_everything(self, filename: str, extensions: list = None, target_dir: str = None, date_filter: str = None, limit: int = 100) -> list:
        if not self._capability_cache.get("everything"):
            return []
            
        import platform
        if platform.system() != "Windows":
            self._capability_cache["everything"] = False
            return []
            
        try:
            import ctypes
            import time
            try:
                everything = ctypes.windll.Everything64
            except (OSError, AttributeError):
                try:
                    everything = ctypes.CDLL("Everything64.dll")
                except OSError:
                    self._capability_cache["everything"] = False
                    return []
                    
            everything.Everything_SetSearchW.argtypes = [ctypes.c_wchar_p]
            everything.Everything_SetSearchW.restype = None
            everything.Everything_QueryW.argtypes = [ctypes.c_bool]
            everything.Everything_QueryW.restype = ctypes.c_bool
            everything.Everything_GetNumResults.argtypes = []
            everything.Everything_GetNumResults.restype = ctypes.c_uint32
            everything.Everything_GetResultFullPathNameW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_uint32]
            everything.Everything_GetResultFullPathNameW.restype = None
            
            everything.Everything_SetSearchW(filename)
            if not everything.Everything_QueryW(True):
                return []
                
            num_results = everything.Everything_GetNumResults()
            scan_limit = min(num_results, limit * 10 if (extensions or target_dir or date_filter) else limit)
            
            results = []
            buf_size = 4096
            buf = ctypes.create_unicode_buffer(buf_size)
            
            ext_set = None
            if extensions:
                ext_set = {ext.lower() if ext.startswith('.') else f".{ext.lower()}" for ext in extensions}
                
            target_dir_norm = None
            if target_dir:
                target_dir_norm = os.path.normpath(target_dir).lower()
                
            now = time.time() if date_filter else None
            one_day = 86400
            
            sec = SecurityManager()
            for i in range(num_results):
                if len(results) >= limit:
                    break
                if i >= scan_limit:
                    break
                    
                everything.Everything_GetResultFullPathNameW(i, buf, buf_size)
                path = buf.value
                if not path:
                    continue
                    
                if not sec.is_safe_path(path):
                    continue
                    
                if target_dir_norm:
                    path_norm = os.path.normpath(path).lower()
                    if not path_norm.startswith(target_dir_norm):
                        continue
                        
                if ext_set:
                    ext = os.path.splitext(path)[1].lower()
                    if ext not in ext_set:
                        continue
                        
                if date_filter and now:
                    try:
                        mtime = os.path.getmtime(path)
                        if date_filter == "today":
                            if mtime < now - one_day:
                                continue
                        elif date_filter == "yesterday":
                            if mtime < now - 2 * one_day or mtime >= now - one_day:
                                continue
                    except OSError:
                        continue
                        
                results.append(path)
            return results
        except Exception as e:
            logger.debug(f"Everything SDK Search failed, caching as unavailable: {e}")
            self._capability_cache["everything"] = False
        return []


    def search_cli_fallback(self, variant: str, root_dir: str = None) -> list:
        results = []
        import platform
        sys_name = platform.system()
        sec = SecurityManager()
        search_paths = [root_dir] if root_dir else sec._get_drives()
        
        for path in search_paths:
            if not os.path.exists(path):
                continue
                
            if sys_name == "Windows":
                try:
                    # Upgrade to PowerShell Get-ChildItem instead of cmd dir
                    cmd = ["powershell.exe", "-NoProfile", "-Command", 
                           f"Get-ChildItem -Path '{path}' -Filter '*{variant}*' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName"]
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                    if proc.stdout:
                        for line in proc.stdout.splitlines():
                            line = line.strip()
                            if line and sec.is_safe_path(line):
                                results.append(line)
                            if len(results) >= 100:
                                return results
                except subprocess.TimeoutExpired:
                    logger.warning(f"CLI search PowerShell timeout on {path} for variant '{variant}'")
            elif sys_name == "Darwin":
                try:
                    cmd = ["mdfind", "-onlyin", path, f'kMDItemFSName == "*{variant}*"c']
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                    if proc.stdout:
                        for line in proc.stdout.splitlines():
                            if sec.is_safe_path(line):
                                results.append(line)
                            if len(results) >= 100:
                                return results
                except subprocess.TimeoutExpired:
                    logger.warning(f"CLI search timeout on {path} for variant '{variant}'")
            else:
                try:
                    cmd = ["find", path, "-iname", f"*{variant}*", "-type", "f"]
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                    if proc.stdout:
                        for line in proc.stdout.splitlines():
                            if sec.is_safe_path(line):
                                results.append(line)
                            if len(results) >= 100:
                                return results
                except subprocess.TimeoutExpired:
                    logger.warning(f"CLI search timeout on {path} for variant '{variant}'")
        return results
