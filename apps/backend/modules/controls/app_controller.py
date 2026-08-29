import os
import subprocess
import logging
import psutil
import time
import re
import threading

from rapidfuzz import fuzz

logger = logging.getLogger("JARVIS.App")

class AppController:
    """
    AppController manages launching, listing, matching, and closing applications on the host OS.

    SYSTEM PROMPT:
    Use AppController to control desktop application lifecycles. Ensure to search or resolve the app name fuzzy aliases first. Never assume an app path exists without verification.

    SHORT DESCRIPTION:
    Manages local Windows OS application lifecycles including detection, startup, and termination.

    PROCESS:
    1. Indexes common applications asynchronously on initialization.
    2. Resolves application queries to absolute executable paths using known aliases, cached dynamic paths, Start Menu link searches via PowerShell, and fallback Program Files scans.
    3. Launches applications natively or via cmd protocols.
    4. Terminates applications by process name using exact, partial, or fuzzy matching via psutil.

    FLOW:
    Caller -> open_app()/close_app() -> _find_app_path() -> subprocess (PowerShell) / os.startfile() / psutil.Process.terminate() -> Caller
    """
    def __init__(self):
        # A simple mapping of common app names to executable names/paths
        browser_pref = os.environ.get("JARVIS_BROWSER_TYPE", "msedge").lower().strip()
        default_browser = "chrome.exe" if browser_pref == "chrome" else "msedge.exe"
        self.app_aliases = {
            "browser": default_browser,
            "the browser": default_browser,
            "web browser": default_browser,
            "internet": default_browser,
            "default browser": default_browser,
            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",
            "chrome browser": "chrome.exe",
            "notepad": "notepad.exe",
            "calculator": "calc.exe",
            "edge": "msedge.exe",
            "microsoft edge": "msedge.exe",
            "spotify": "spotify.exe",
            "vscode": "Code.exe",
            "visual studio code": "Code.exe",
            "vs code": "Code.exe",
            "word": "winword.exe",
            "excel": "excel.exe",
            "whatsapp": "whatsapp:",
            "file explorer": "explorer.exe",
            "explorer": "explorer.exe",
            "windows explorer": "explorer.exe",
            "cmd": "cmd.exe",
            "command prompt": "cmd.exe",
            "command line": "cmd.exe",
            "terminal": "cmd.exe",
            "powershell": "powershell.exe",
            "power shell": "powershell.exe"
        }
        
        # Special mapping for protocols or aliases to their actual process names
        self.process_aliases = {
            "whatsapp": "WhatsApp.exe",
            "whatsapp:": "WhatsApp.exe"
        }
        
        self.dynamic_app_paths = {} # {app_name: (path, timestamp)}
        
        self.running_process_cache = []
        self.last_process_cache_time = 0
        
        import sys
        if "pytest" not in sys.modules and "PYTEST_CURRENT_TEST" not in os.environ:
            threading.Thread(target=self._index_common_apps, daemon=True).start()
        
        logger.info("AppController initialized.")

    def _index_common_apps(self):
        import time
        time.sleep(10)  # Delay indexing to prioritize JARVIS startup
        logger.info("Background indexing of common applications started.")
        common_apps = ["chrome", "edge", "browser", "calculator", "notepad", "spotify", "vscode"]
        for app in common_apps:
            # Check if it's already an alias that works directly
            if app in self.app_aliases and self.app_aliases[app].endswith('.exe'):
                continue # No need to resolve if it's in PATH
            self._find_app_path(app)
        logger.info("Background indexing of common applications finished.")


    def _find_app_path(self, app_name: str) -> str:
        app_name = app_name.lower().strip()
        if app_name.startswith("the "):
            app_name = app_name[4:].strip()
        # Clean phrases like "whatsapp chat with karan" -> "whatsapp"
        for phrase in [" chat with ", " chat of ", " message to ", " dm to ", " conversation with "]:
            if phrase in app_name:
                app_name = app_name.split(phrase)[0].strip()

        # 1. Check known aliases
        import shutil
        if app_name in self.app_aliases:
            alias = self.app_aliases[app_name]
            if os.path.isabs(alias) or shutil.which(alias) or alias.endswith(':'):
                return alias

            # Check standard Windows installation directories for browser executables
            alias_lower = alias.lower()
            known_paths = []
            if alias_lower in ("msedge.exe", "edge.exe", "msedge", "browser", "browser.exe"):
                known_paths = [
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                    os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
                ]
            elif alias_lower in ("chrome.exe", "chrome"):
                known_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                ]
            for kp in known_paths:
                if os.path.exists(kp):
                    self.dynamic_app_paths[app_name] = (kp, time.time())
                    return kp

            # If the alias is not directly runnable, we fallback to searching using both
            # the query and the alias target name
            search_names = [app_name]
            clean_alias = alias[:-4] if alias.endswith('.exe') else alias
            if clean_alias not in search_names:
                search_names.append(clean_alias)
        else:
            search_names = [app_name]
            
        # 2. Check cached dynamic paths (with 5 min expiration for misses)
        for name in search_names:
            if name in self.dynamic_app_paths:
                cached_path, timestamp = self.dynamic_app_paths[name]
                if cached_path is not None:
                    return cached_path
                elif time.time() - timestamp < 300: # 5 minutes TTL for None
                    return app_name
            
        # 3. Use PowerShell to find the app in Start Menu / fallbacks
        for name in search_names:
            safe_name = name.replace("'", "''")
            safe_name = re.sub(r'[\\/*?:"<>|\[\]\(\)]', '', safe_name)
            
            ps_script = f"""
            $ErrorActionPreference = 'SilentlyContinue'
            $shell = New-Object -ComObject WScript.Shell
            $paths = @(
                "$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs",
                "$env:AppData\\Microsoft\\Windows\\Start Menu\\Programs"
            )
            $shortcuts = Get-ChildItem -Path $paths -Depth 3 -Filter "*.lnk"
            foreach ($shortcut in $shortcuts) {{
                if ($shortcut.BaseName -like "*{safe_name}*") {{
                    $link = $shell.CreateShortcut($shortcut.FullName)
                    if ($link.TargetPath -and (Test-Path $link.TargetPath)) {{
                        Write-Output $link.TargetPath
                        break
                    }}
                }}
            }}
            """
            try:
                result = subprocess.run(['powershell', '-Command', ps_script], capture_output=True, text=True, timeout=5)
                target_path = result.stdout.strip()
                if target_path and os.path.exists(target_path):
                    self.dynamic_app_paths[app_name] = (target_path, time.time())
                    return target_path
            except Exception as e:
                logger.error(f"Error finding app path via PowerShell for {name}: {e}")

            # 4. Fallback: Search common Program Files locations directly
            target_path = self._fallback_search_program_files(safe_name)
            if target_path:
                self.dynamic_app_paths[app_name] = (target_path, time.time())
                return target_path
            
        # Cache the miss so we don't run PowerShell/searches again immediately
        self.dynamic_app_paths[app_name] = (None, time.time())
        return app_name

    def _fallback_search_program_files(self, app_name: str) -> str:
        """Fallback search in common program file directories."""
        search_dirs = [
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
            os.path.join(os.environ.get("LocalAppData", "C:\\Users\\Default\\AppData\\Local"), "Programs")
        ]
        
        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            try:
                # Limit depth to 2 to avoid scanning too many files
                for root, dirs, files in os.walk(search_dir):
                    depth = root[len(search_dir) + len(os.path.sep):].count(os.path.sep)
                    if depth > 2:
                        dirs.clear() # don't go deeper
                        continue
                        
                    for file in files:
                        if file.lower().endswith(".exe"):
                            name_no_ext = file[:-4].lower()
                            if app_name.lower() in name_no_ext or fuzz.ratio(app_name.lower(), name_no_ext) > 85:
                                return os.path.join(root, file)
            except Exception:
                pass
        return None

    def open_app(self, app_name: str):
        target_path = self._find_app_path(app_name)
        
        try:
            logger.info(f"Opening application: {target_path}")
            # Try to start using os.startfile which works well for full paths or apps in PATH
            try:
                os.startfile(target_path)
            except FileNotFoundError:
                # Fallback to cmd start for UWP apps / protocols
                # Safety check to avoid blocking Windows modal error popups
                if not target_path.endswith(":"):
                    import shutil
                    if not shutil.which(target_path) and not os.path.exists(target_path):
                        logger.error(f"Application executable not found in PATH or disk: {target_path}")
                        return False
                safe_path = re.sub(r'[&|;<>]', '', target_path)
                subprocess.run(["cmd", "/c", "start", "", safe_path], check=False)
                
            return True
        except Exception as e:
            logger.error(f"Failed to open app {app_name}: {e}")
            return False

    def open_file_with_app(self, app_name: str, file_path: str):
        target_path = self._find_app_path(app_name)
        
        try:
            logger.info(f"Opening file {file_path} with application: {target_path}")
            # Ensure the file exists
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}")
                return False
                
            # If the app path is not found, fallback to os.startfile
            if target_path == app_name:
                logger.warning(f"App {app_name} not found. Opening with default application.")
                os.startfile(file_path)
                return True

            try:
                subprocess.Popen([target_path, file_path])
            except Exception as popen_err:
                logger.warning(f"Popen directly with {target_path} failed ({popen_err}). Trying os.startfile fallback.")
                os.startfile(file_path)
            return True
        except Exception as e:
            logger.error(f"Failed to open file {file_path} with app {app_name}: {e}")
            return False

    def close_app(self, app_name: str):
        target_path = self._find_app_path(app_name)
        
        # Determine executable name for process termination
        exe_name = None
        if app_name.lower() in self.process_aliases:
            exe_name = self.process_aliases[app_name.lower()]
        elif "\\" in target_path or "/" in target_path:
            exe_name = os.path.basename(target_path)
        else:
            exe_name = target_path
            if exe_name.endswith(':'):
                exe_name = exe_name[:-1]
            if not exe_name.lower().endswith('.exe'):
                exe_name = f"{exe_name}.exe"
                
        closed = False

        # Always fetch a fresh process list — a 3s cache means recently-opened
        # apps cannot be closed. psutil.process_iter is fast enough to call live.
        try:
            current_processes = list(psutil.process_iter(['name']))
        except Exception as e:
            logger.warning(f"Failed to list processes: {e}")
            current_processes = []

        for proc in current_processes:
            try:
                p_name = proc.info.get('name', '')
                if not p_name:
                    continue
                    
                # Match by exact, partial or fuzzy
                if (p_name.lower() == exe_name.lower() or 
                    exe_name.lower() in p_name.lower() or
                    fuzz.partial_ratio(exe_name.lower(), p_name.lower()) > 85):
                    
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    closed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        if closed:
            logger.info(f"Closed application: {app_name}")
            return True
        else:
            logger.warning(f"Could not find running process for: {app_name} (looked for {exe_name})")
            return False
