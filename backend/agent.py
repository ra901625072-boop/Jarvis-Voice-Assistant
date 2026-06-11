import os
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path, override=False)

import asyncio
import inspect
from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent, llm
from livekit.plugins import (
    google,
)

# Import all controllers from our modules
from modules.controls.app_controller import AppController
from modules.controls.browser_controller import BrowserController
from modules.controls.volume_controller import VolumeController
from modules.controls.brightness_controller import BrightnessController
from modules.controls.keyboard_controller import KeyboardController
from modules.controls.mouse_controller import MouseController
from modules.filesystem.file_manager import FileManager
from modules.filesystem.folder_manager import FolderManager
from modules.controls.window_controller import WindowController
from modules.controls.system_controller import SystemController, capture_screen
from modules.perception.vision import analyze_screen, extract_text_from_screen
from modules.perception.screen_observer import ScreenObserver
from modules.perception.ui_mapper import UIMapper
from modules.planning.action_verifier import ActionVerifier
from modules.core.memory_manager import MemoryManager
from modules.core.security_manager import SecurityManager
from modules.core.cognitive_coordinator import CognitiveCoordinator
from modules.execution.executive_controller import ExecutiveController
from modules.planning.behavior import JarvisBehavior
from modules.planning.task_manager import BackgroundTaskManager, TaskStatus
from modules.planning.task_planner import TaskPlannerTools
from modules.execution.world_state import WorldStateManager
from modules.execution.verification_engine import VerificationEngine
from modules.filesystem.fs_utils import is_safe_path

# Initialize global background task manager and global file/folder manager instances
_db_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database")
os.makedirs(_db_dir, exist_ok=True)
task_manager = BackgroundTaskManager(db_path=os.path.join(_db_dir, "tasks.db"))

_global_file_mgr = FileManager()
_global_folder_mgr = FolderManager(file_mgr=_global_file_mgr)
_global_screen_observer = ScreenObserver(cache_duration=3.0)
_global_ui_mapper = UIMapper(observer=_global_screen_observer)
_global_action_verifier = ActionVerifier(observer=_global_screen_observer)

def handle_move_file(context, src, dest):
    context.update_progress(10)
    res = _global_file_mgr.move_item(src, dest, force_sync=True)
    if isinstance(res, str) and res.startswith("Error:"):
        raise RuntimeError(res)
    context.update_progress(100)
    return res

def handle_move_folder(context, src, dest):
    context.update_progress(10)
    res = _global_folder_mgr.move_folder(src, dest, force_sync=True)
    if isinstance(res, str) and res.startswith("Error:"):
        raise RuntimeError(res)
    context.update_progress(100)
    return res

def handle_copy_file(context, src, dest):
    context.update_progress(10)
    res = _global_file_mgr.copy_item(src, dest)
    if isinstance(res, str) and res.startswith("Error:"):
        raise RuntimeError(res)
    context.update_progress(100)
    return res

def handle_copy_folder(context, src, dest):
    context.update_progress(10)
    res = _global_folder_mgr.copy_folder(src, dest)
    if isinstance(res, str) and res.startswith("Error:"):
        raise RuntimeError(res)
    context.update_progress(100)
    return res

# Register handlers and start background task runner
task_manager.register_handler("move_file", handle_move_file)
task_manager.register_handler("move_folder", handle_move_folder)
task_manager.register_handler("copy_file", handle_copy_file)
task_manager.register_handler("copy_folder", handle_copy_folder)
task_manager.start()

class JarvisToolset(llm.Toolset):
    def __init__(self, security: SecurityManager = None, room=None):
        super().__init__(id=self.__class__.__name__.lower())
        self.security = security
        self.room = room

    async def safe_execute(
        self, func, *args,
        confirmation_category=None, confirmation_action=None,
        confirmed=False, success_msg=None, error_msg=None,
    ):
        import time as _time
        tool_name = getattr(func, "__name__", str(func))
        t0 = _time.monotonic()
        try:
            if self.room:
                msg = '{"type": "processing_start"}'
                await self.room.local_participant.publish_data(msg.encode('utf-8'))

            if confirmation_category and confirmation_action and self.security:
                if self.security.requires_confirmation(confirmation_category, confirmation_action) and not confirmed:
                    return (
                        f"SECURITY WARNING: This action requires user confirmation. "
                        f"Please ask the user to confirm they want to {confirmation_action}. "
                        f"Once they agree, call this tool again with confirmed=True."
                    )

            if inspect.iscoroutinefunction(func):
                result = await func(*args)
            else:
                result = await asyncio.to_thread(func, *args)
            exec_ms = int((_time.monotonic() - t0) * 1000)

            is_error = (
                result is False
                or (isinstance(result, str) and result.startswith("Error:"))
            )

            # Phase 5: auto-record tool outcome to tool_memory
            try:
                if hasattr(self, 'memory') and hasattr(self.memory, 'lifecycle'):
                    self.memory.lifecycle.tool_memory.record(
                        tool_name, not is_error, exec_ms,
                        error=str(result)[:200] if is_error else None,
                    )
            except Exception:
                pass

            if is_error:
                return error_msg or result or "Failed to execute tool."
            if result is True and success_msg:
                return success_msg
            if success_msg:
                return success_msg
            return result

        except Exception as e:
            exec_ms = int((_time.monotonic() - t0) * 1000)
            # Record failure
            try:
                if hasattr(self, 'memory') and hasattr(self.memory, 'lifecycle'):
                    self.memory.lifecycle.tool_memory.record(
                        tool_name, False, exec_ms, error=str(e)[:200]
                    )
            except Exception:
                pass
            return f"Error: {e}"

class VerificationTools(JarvisToolset):
    def __init__(self, verification: VerificationEngine, security: SecurityManager, room=None):
        super().__init__(security, room)
        self.verification = verification

    @llm.function_tool(
        description="Programmatically verify the outcome of an action. "
                    "MUST be called after taking an action like opening an app or creating a file to confirm success. "
                    "condition_type: 'process_running', 'window_exists', 'file_exists', 'clipboard_contains'. "
                    "target: process name (e.g., 'chrome'), window title, file path, or clipboard text."
    )
    async def verify_execution(self, condition_type: str, target: str) -> str:
        # We need access to state_manager to update state to VERIFYING
        from modules.core.state_manager import AgentStateManager, AgentState
        sm = AgentStateManager()
        sm.set_agent_state(AgentState.VERIFYING)
        
        result = await asyncio.to_thread(self.verification.verify, condition_type, target)
        
        # Revert state back to EXECUTING after verification
        sm.set_agent_state(AgentState.EXECUTING)
        
        if result:
            return f"Verification SUCCESS: {condition_type} -> '{target}' is TRUE."
        else:
            return f"Verification FAILED: {condition_type} -> '{target}' is FALSE."

class SystemTools(JarvisToolset):
    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self.system_ctrl = SystemController()

    @llm.function_tool(
        description="""
Capture a temporary screenshot only when visual information is required.

Use this tool to:
- Read screen text
- Identify applications
- Detect errors
- Describe UI elements
- Analyze images or documents currently visible

Do not call this tool unless visual information is necessary for answering the user's request.

The screenshot is automatically deleted after analysis.
"""
    )
    async def analyze_current_screen(self) -> str:
        image_path, screen_hash, _ = _global_screen_observer.get_screenshot()
        if not image_path:
            return "Error: Failed to capture screen."
        result = await asyncio.to_thread(analyze_screen, image_path, screen_hash)
        return result

    @llm.function_tool(
        description="Read text visible on the screen."
    )
    async def read_screen_text(self) -> str:
        image_path, screen_hash, _ = _global_screen_observer.get_screenshot()
        if not image_path:
            return "Error: Failed to capture screen."
        result = await asyncio.to_thread(extract_text_from_screen, image_path, screen_hash)
        return result

    @llm.function_tool(description="Verify if a visual outcome or state was achieved on screen (e.g. 'Login page is visible', 'Error message popped up').")
    async def verify_action(self, expected_state: str, window_title: str = None) -> str:
        result = await asyncio.to_thread(_global_action_verifier.verify_state, expected_state, window_title)
        if result:
            return f"Verified: '{expected_state}' is present on the screen."
        else:
            return f"Verification Failed: '{expected_state}' was not detected on the screen."

    @llm.function_tool(description="Shutdown the computer system. Requires user confirmation.")
    async def shutdown_system(self, confirmed: bool = False) -> str:
        return await self.safe_execute(self.system_ctrl.shutdown, confirmation_category="power", confirmation_action="shutdown", confirmed=confirmed, success_msg="Shutting down the system...")

    @llm.function_tool(description="Restart the computer system. Requires user confirmation.")
    async def restart_system(self, confirmed: bool = False) -> str:
        return await self.safe_execute(self.system_ctrl.restart, confirmation_category="power", confirmation_action="restart", confirmed=confirmed, success_msg="Restarting the system...")

    @llm.function_tool(description="Put the computer to sleep.")
    async def sleep_system(self) -> str:
        return await self.safe_execute(self.system_ctrl.sleep, success_msg="System entering sleep mode.")

    @llm.function_tool(description="Lock the computer workstation.")
    async def lock_pc(self) -> str:
        return await self.safe_execute(self.system_ctrl.lock_pc, success_msg="Workstation locked.")

    @llm.function_tool(description="Log out the current user.")
    async def logout_user(self, confirmed: bool = False) -> str:
        return await self.safe_execute(self.system_ctrl.logout, confirmation_category="power", confirmation_action="logout", confirmed=confirmed, success_msg="Logging out...")

    @llm.function_tool(description="Copy text to the system clipboard.")
    async def copy_to_clipboard(self, text: str) -> str:
        return await self.safe_execute(self.system_ctrl.copy_text, text, success_msg="Text copied to clipboard.")

    @llm.function_tool(description="Get the current text from the system clipboard.")
    async def get_from_clipboard(self) -> str:
        content = await self.safe_execute(self.system_ctrl.get_clipboard)
        return f"Clipboard content: {content}" if not str(content).startswith("Error:") and content else "Clipboard is empty."

    @llm.function_tool(description="Clear the system clipboard.")
    async def clear_clipboard(self) -> str:
        return await self.safe_execute(self.system_ctrl.clear_clipboard, success_msg="Clipboard cleared.")

    @llm.function_tool(description="Take a screenshot of the computer screen.")
    async def take_screenshot(self) -> str:
        result = await self.safe_execute(self.system_ctrl.take_screenshot)
        if result is True or (isinstance(result, str) and not result.startswith("Error:")):
            path = os.path.abspath("screenshot.jpg")
            return f"Screenshot saved at {path}"
        return str(result)

    @llm.function_tool(description="Open the Windows system settings app.")
    async def open_settings(self) -> str:
        return await self.safe_execute(self.system_ctrl.open_settings, success_msg="Settings opened.")

class WindowTools(JarvisToolset):
    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self.window_ctrl = WindowController()

    @llm.function_tool(description="Minimize a window by its title keyword, or the active window if none provided.")
    async def minimize_window(self, title_keyword: str = None) -> str:
        return await self.safe_execute(self.window_ctrl.minimize_window, title_keyword, success_msg="Window minimized.", error_msg="Failed to find or minimize window.")

    @llm.function_tool(description="Maximize a window by its title keyword, or the active window if none provided.")
    async def maximize_window(self, title_keyword: str = None) -> str:
        return await self.safe_execute(self.window_ctrl.maximize_window, title_keyword, success_msg="Window maximized.", error_msg="Failed to find or maximize window.")

    @llm.function_tool(description="Restore a window to its normal size by its title keyword, or the active window if none provided.")
    async def restore_window(self, title_keyword: str = None) -> str:
        return await self.safe_execute(self.window_ctrl.restore_window, title_keyword, success_msg="Window restored.", error_msg="Failed to find or restore window.")

    @llm.function_tool(description="Close a window by its title keyword, or the active window if none provided.")
    async def close_window(self, title_keyword: str = None) -> str:
        return await self.safe_execute(self.window_ctrl.close_window, title_keyword, success_msg="Window closed.", error_msg="Failed to find or close window.")

    @llm.function_tool(description="Bring a window to the foreground and focus it by its title keyword.")
    async def focus_window(self, title_keyword: str = None) -> str:
        return await self.safe_execute(self.window_ctrl.focus_window, title_keyword, success_msg="Window focused.", error_msg="Failed to find or focus window.")

    @llm.function_tool(description="Switch to the next window (simulates Alt+Tab).")
    async def switch_window(self) -> str:
        return await self.safe_execute(self.window_ctrl.switch_window, success_msg="Switched window.")

    @llm.function_tool(description="Show the desktop (minimizes all windows).")
    async def show_desktop(self) -> str:
        return await self.safe_execute(self.window_ctrl.show_desktop, success_msg="Showing desktop.")

class AppTools(JarvisToolset):
    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self.app_ctrl = AppController()

    @llm.function_tool(description="Open an application by its name (e.g., notepad, calculator, chrome)")
    async def open_application(self, app_name: str) -> str:
        return await self.safe_execute(self.app_ctrl.open_app, app_name, success_msg=f"Successfully opened {app_name}.", error_msg=f"Failed to open {app_name}.")

    @llm.function_tool(description="Close a running application by its name")
    async def close_application(self, app_name: str) -> str:
        return await self.safe_execute(self.app_ctrl.close_app, app_name, success_msg=f"Attempted to close {app_name}.")

class BrowserTools(JarvisToolset):
    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self.browser_ctrl = BrowserController()

    @llm.function_tool(description="Open a specific URL in the browser")
    async def open_url(self, url: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"]:
            return "Error: Invalid URL scheme. Only http and https are allowed."
        return await self.safe_execute(self.browser_ctrl.open_url, url, success_msg=f"Opened {url} in the browser.")

    @llm.function_tool(description="Close a specific website tab by domain or title")
    async def close_website(self, domain_or_title: str) -> str:
        return await self.safe_execute(self.browser_ctrl.close_website, domain_or_title, success_msg=f"Closed website tab matching '{domain_or_title}'.", error_msg=f"Could not find or close website tab matching '{domain_or_title}'.")

    @llm.function_tool(description="Search Google for a specific query")
    async def search_google(self, query: str) -> str:
        return await self.safe_execute(self.browser_ctrl.search, query, success_msg=f"Performed Google search for {query}.")

    @llm.function_tool(
        description="Search live for a query, parse top results, extract page contents, and return results. By default, queries Google first and falls back to Wikipedia if blocked or empty. You can also explicitly request a specific engine using the engine parameter ('google', 'wikipedia')."
    )
    async def search_google_live(self, query: str, engine: str = "google") -> str:
        return await self.safe_execute(self.browser_ctrl.search_live, query, 3, engine)

    @llm.function_tool(description="Search YouTube for a specific query")
    async def search_youtube(self, query: str) -> str:
        return await self.safe_execute(self.browser_ctrl.search_youtube, query, success_msg=f"Performed YouTube search for {query}.")

    @llm.function_tool(description="Search YouTube and automatically play the first video result")
    async def play_youtube(self, query: str) -> str:
        return await self.safe_execute(self.browser_ctrl.play_youtube, query, success_msg=f"Playing YouTube video for {query}.")

    @llm.function_tool(description="Switch to a browser tab matching a keyword")
    async def switch_tab(self, keyword: str) -> str:
        return await self.safe_execute(self.browser_ctrl.switch_tab, keyword, success_msg=f"Switched to tab matching {keyword}.", error_msg=f"No tab found matching {keyword}.")

    @llm.function_tool(description="List all open browser tabs")
    async def list_tabs(self) -> str:
        tabs = await self.safe_execute(self.browser_ctrl.list_tabs)
        if str(tabs).startswith("Error:"): return str(tabs)
        if not tabs: return "No tabs are open or browser is not running."
        formatted = "Open tabs:\n" + "\n".join([f"- {t['title']} ({t['url']})" for t in tabs])
        return formatted

    @llm.function_tool(description="Refresh the current browser tab")
    async def refresh_tab(self) -> str:
        return await self.safe_execute(self.browser_ctrl.refresh_tab, success_msg="Refreshed the current tab.")

    @llm.function_tool(description="Go back to the previous page in the browser")
    async def browser_go_back(self) -> str:
        return await self.safe_execute(self.browser_ctrl.go_back, success_msg="Navigated back.")

    @llm.function_tool(description="Go forward to the next page in the browser")
    async def browser_go_forward(self) -> str:
        return await self.safe_execute(self.browser_ctrl.go_forward, success_msg="Navigated forward.")

    @llm.function_tool(description="Get the title and URL of the current browser page")
    async def get_current_page_info(self) -> str:
        info = await self.safe_execute(self.browser_ctrl.get_current_page_info)
        if str(info).startswith("Error:"): return str(info)
        return f"Currently viewing: {info.get('title')} at {info.get('url')}."

class MediaTools(JarvisToolset):
    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self.volume_ctrl = VolumeController()
        self.brightness_ctrl = BrightnessController()

    @llm.function_tool(description="Set the system volume to a specific percentage (0-100)")
    async def set_volume(self, level: int) -> str:
        return await self.safe_execute(self.volume_ctrl.set_volume, level, success_msg=f"Volume set to {level}%.")

    @llm.function_tool(description="Mute the system audio")
    async def mute_audio(self) -> str:
        return await self.safe_execute(self.volume_ctrl.mute, success_msg="Audio muted.")

    @llm.function_tool(description="Unmute the system audio")
    async def unmute_audio(self) -> str:
        return await self.safe_execute(self.volume_ctrl.unmute, success_msg="Audio unmuted.")

    @llm.function_tool(description="Set the system display brightness to a specific percentage (0-100)")
    async def set_brightness(self, level: int) -> str:
        return await self.safe_execute(self.brightness_ctrl.set_brightness, level, success_msg=f"Brightness set to {level}%.")

class KeyboardTools(JarvisToolset):
    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self.keyboard_ctrl = KeyboardController()

    @llm.function_tool(description="Type a given text string exactly using the keyboard")
    async def type_text(self, text: str, confirmed: bool = False) -> str:
        if len(text) > 500 and not confirmed:
            return "SECURITY WARNING: The text is too long. Please ask the user to confirm they want to type this much text. Call again with confirmed=True."
        return await self.safe_execute(self.keyboard_ctrl.type_text, text, success_msg="Typed the given text.")

    @llm.function_tool(description="Press a specific key or key combination string (e.g., 'enter', 'ctrl+c', 'win+d')")
    async def press_key(self, keys: str) -> str:
        return await self.safe_execute(self.keyboard_ctrl.press_key, keys, success_msg=f"Pressed keys: {keys}.")

    @llm.function_tool(description="Hold down a specific key (e.g., 'shift', 'ctrl', 'a')")
    async def hold_key(self, key: str) -> str:
        return await self.safe_execute(self.keyboard_ctrl.hold_key, key, success_msg=f"Held down key: {key}.")

    @llm.function_tool(description="Release a specific key that was previously held down")
    async def release_key(self, key: str) -> str:
        return await self.safe_execute(self.keyboard_ctrl.release_key, key, success_msg=f"Released key: {key}.")

class MouseTools(JarvisToolset):
    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self.mouse_ctrl = MouseController(observer=_global_screen_observer, ui_mapper=_global_ui_mapper)

    @llm.function_tool(description="Left click the mouse at its current location, or optionally at specified x,y coordinates")
    async def click_mouse(self, x: int = None, y: int = None) -> str:
        return await self.safe_execute(self.mouse_ctrl.click, x, y, success_msg="Mouse left-clicked.")

    @llm.function_tool(description="Double left click the mouse at its current location, or optionally at specified x,y coordinates")
    async def double_click_mouse(self, x: int = None, y: int = None) -> str:
        return await self.safe_execute(self.mouse_ctrl.double_click, x, y, success_msg="Mouse double-clicked.")

    @llm.function_tool(description="Right click the mouse at its current location, or optionally at specified x,y coordinates")
    async def right_click_mouse(self, x: int = None, y: int = None) -> str:
        return await self.safe_execute(self.mouse_ctrl.right_click, x, y, success_msg="Mouse right-clicked.")

    @llm.function_tool(description="Move the mouse cursor to the specified absolute x,y coordinates on the screen")
    async def move_mouse(self, x: int, y: int) -> str:
        return await self.safe_execute(self.mouse_ctrl.move, x, y, success_msg=f"Mouse moved to {x},{y}.")

    @llm.function_tool(description="Scroll the mouse wheel. Positive amount scrolls up, negative amount scrolls down")
    async def scroll_mouse(self, amount: int) -> str:
        return await self.safe_execute(self.mouse_ctrl.scroll, amount, success_msg=f"Mouse scrolled by {amount}.")

    @llm.function_tool(description="Get the current x,y coordinates of the mouse cursor")
    async def get_mouse_position(self) -> str:
        res = await self.safe_execute(self.mouse_ctrl.get_position)
        if isinstance(res, tuple):
            x, y = res
            return f"Mouse is currently at {x},{y}."
        return str(res)

    @llm.function_tool(description="Uses AI Vision to find and click an interactive UI element (button, link, text box) by its description.")
    async def click_element_vision(self, description: str, window_title: str = None) -> str:
        return await self.safe_execute(self.mouse_ctrl.click_element_vision, description, window_title, success_msg=f"Successfully clicked '{description}'.", error_msg=f"Failed to find or click '{description}'.")

    @llm.function_tool(description="Uses AI Vision to find the exact x,y coordinates of an interactive element by its description.")
    async def find_element_vision(self, description: str, window_title: str = None) -> str:
        coords = await self.safe_execute(self.mouse_ctrl.find_element_vision, description, window_title)
        if isinstance(coords, tuple):
            return f"Element '{description}' found at coordinates {coords[0]}, {coords[1]}."
        return str(coords) if str(coords).startswith("Error:") else f"Could not locate '{description}'."

class FileTools(JarvisToolset):
    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)
        self.file_mgr = FileManager()
        self.folder_mgr = FolderManager(file_mgr=self.file_mgr)

    @llm.function_tool(description="Resolve a file or folder query like 'my resume' or 'PythonProjects' into an absolute path")
    async def resolve_file_path(self, query: str) -> str:
        path = await self.safe_execute(self.file_mgr.resolve_path, query)
        if str(path).startswith("Error:"): return str(path)
        if isinstance(path, list):
            options = "\n".join([f"- {p}" for p in path])
            return f"AMBIGUOUS_MATCHES: Multiple items found matching '{query}'. Please ask the user to clarify which one they want:\n{options}"
        return f"Resolved to: {path}" if path else f"Could not find any file or folder matching '{query}'."

    @llm.function_tool(description="Search for a file or folder by name starting from a root directory or default user directory")
    async def search_file(self, filename: str, root_dir: str = None) -> str:
        results = await self.safe_execute(self.file_mgr.search_file, filename, root_dir)
        if str(results).startswith("Error:"): return str(results)
        if not results: return f"No file or folder results found for {filename}."
        return f"Found {len(results)} results: {', '.join(results[:5])}" + ("..." if len(results) > 5 else "")

    @llm.function_tool(description="Create a new folder at the specified path")
    async def create_folder(self, path: str) -> str:
        return await self.safe_execute(self.folder_mgr.create_folder, path, success_msg=f"Folder {path} created.")

    @llm.function_tool(description="Create a new file with optional content at the specified path")
    async def create_file(self, path: str, content: str = "") -> str:
        return await self.safe_execute(self.file_mgr.create_file, path, content, success_msg=f"File {path} created.", error_msg=f"Failed to create file {path}.")

    @llm.function_tool(description="Read the contents of a text file")
    async def read_file(self, path: str) -> str:
        content = await self.safe_execute(self.file_mgr.read_file, path)
        if str(content).startswith("Error:"): return str(content)
        if content is None: return f"Failed to read file {path}."
        return f"File contents:\n{content[:2000]}" + ("...\n[Content Truncated]" if len(content) > 2000 else "")

    @llm.function_tool(description="Delete a file or folder at the specified path. Requires confirmation.")
    async def delete_item(self, path: str, confirmed: bool = False) -> str:
        if os.path.isdir(path):
            return await self.safe_execute(self.folder_mgr.delete_folder, path, confirmation_category="delete", confirmation_action=path, confirmed=confirmed, success_msg=f"Folder {path} deleted (moved to recycle bin).")
        else:
            return await self.safe_execute(self.file_mgr.delete_item, path, confirmation_category="delete", confirmation_action=path, confirmed=confirmed, success_msg=f"File {path} deleted (moved to recycle bin).")

    @llm.function_tool(description="Move a file or folder from src to dest path")
    async def move_item(self, src: str, dest: str) -> str:
        try:
            src_abs = os.path.normpath(os.path.abspath(src))
            dest_abs = os.path.normpath(os.path.abspath(dest))
            
            if not is_safe_path(src_abs) or not is_safe_path(dest_abs):
                return "Error: Security Policy blocks moving system folder/file."
                
            is_dir = os.path.isdir(src_abs)
            src_drive = os.path.splitdrive(src_abs)[0].lower()
            dest_drive = os.path.splitdrive(dest_abs)[0].lower()
            is_cross_drive = src_drive != dest_drive
            
            if is_dir:
                if is_cross_drive:
                    # Queue in background task manager
                    task_id = task_manager.add_task("move_folder", args=(src_abs, dest_abs))
                    return f"The transfer of folder '{src}' to '{dest}' has started in the background (Task ID: {task_id}). You can check its status using get_background_task_status."
                else:
                    # Synchronous immediate move
                    result = await self.safe_execute(self.folder_mgr.move_folder, src_abs, dest_abs)
                    if result is True:
                        return f"Successfully moved folder {src} to {dest}."
                    return str(result)
            else:
                large_file = False
                if is_cross_drive:
                    try:
                        large_file = os.path.getsize(src_abs) > 50 * 1024 * 1024
                    except Exception:
                        pass
                
                if is_cross_drive and large_file:
                    task_id = task_manager.add_task("move_file", args=(src_abs, dest_abs))
                    return f"The transfer of file '{src}' to '{dest}' has started in the background (Task ID: {task_id}). You can check its status using get_background_task_status."
                else:
                    result = await self.safe_execute(self.file_mgr.move_item, src_abs, dest_abs)
                    if result is True:
                        return f"Successfully moved file {src} to {dest}."
                    return str(result)
        except Exception as e:
            return f"Error: {e}"

    @llm.function_tool(description="Copy a file or folder from src to dest path")
    async def copy_item(self, src: str, dest: str) -> str:
        try:
            src_abs = os.path.normpath(os.path.abspath(src))
            dest_abs = os.path.normpath(os.path.abspath(dest))
            
            if not is_safe_path(src_abs) or not is_safe_path(dest_abs):
                return "Error: Security Policy blocks copying to/from system directories."
                
            is_dir = os.path.isdir(src_abs)
            src_drive = os.path.splitdrive(src_abs)[0].lower()
            dest_drive = os.path.splitdrive(dest_abs)[0].lower()
            is_cross_drive = src_drive != dest_drive
            
            if is_dir:
                if is_cross_drive:
                    task_id = task_manager.add_task("copy_folder", args=(src_abs, dest_abs))
                    return f"Copying folder '{src}' to '{dest}' has started in the background (Task ID: {task_id}). You can check its status using get_background_task_status."
                else:
                    return await self.safe_execute(self.folder_mgr.copy_folder, src_abs, dest_abs, success_msg=f"Folder copied from {src} to {dest}.")
            else:
                large_file = False
                if is_cross_drive:
                    try:
                        large_file = os.path.getsize(src_abs) > 50 * 1024 * 1024
                    except Exception:
                        pass
                
                if is_cross_drive and large_file:
                    task_id = task_manager.add_task("copy_file", args=(src_abs, dest_abs))
                    return f"Copying file '{src}' to '{dest}' has started in the background (Task ID: {task_id}). You can check its status using get_background_task_status."
                else:
                    return await self.safe_execute(self.file_mgr.copy_item, src_abs, dest_abs, success_msg=f"File copied from {src} to {dest}.")
        except Exception as e:
            return f"Error: {e}"

    @llm.function_tool(description="Rename a file or folder")
    async def rename_item(self, src: str, new_name: str) -> str:
        if os.path.isdir(src):
            return await self.safe_execute(self.folder_mgr.rename_folder, src, new_name, success_msg=f"Folder renamed from {src} to {new_name}.")
        else:
            return await self.safe_execute(self.file_mgr.rename_item, src, new_name, success_msg=f"File renamed from {src} to {new_name}.")

    @llm.function_tool(description="Open a file or folder natively in the OS")
    async def open_item(self, path: str) -> str:
        return await self.safe_execute(self.file_mgr.open_item, path, success_msg=f"Opened {path}.")

    @llm.function_tool(description="Get size, creation date, and metadata about a file")
    async def get_file_info(self, path: str) -> str:
        info = await self.safe_execute(self.file_mgr.get_file_info, path)
        if str(info).startswith("Error:"): return str(info)
        return f"File Info: {info}" if info else f"Failed to get info for {path}."

    @llm.function_tool(description="List the contents of a directory")
    async def list_directory(self, path: str) -> str:
        items = await self.safe_execute(self.folder_mgr.list_directory, path)
        if str(items).startswith("Error:"): return str(items)
        return f"Directory contains {len(items)} items: {', '.join(items[:20])}" + ("..." if len(items) > 20 else "")

    @llm.function_tool(description="Close an open folder window or file window")
    async def close_item(self, path: str) -> str:
        if os.path.isdir(path):
            return await self.safe_execute(self.folder_mgr.close_folder, path, success_msg=f"Attempted to close folder window {path}.")
        else:
            return await self.safe_execute(self.file_mgr.close_item, path, success_msg=f"Attempted to close file window {path}.")

class TaskTools(JarvisToolset):
    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)

    @llm.function_tool(description="List all recent background tasks and their statuses")
    async def list_background_tasks(self, limit: int = 10) -> str:
        try:
            tasks = await asyncio.to_thread(task_manager.get_all_tasks, limit)
            if not tasks:
                return "No background tasks have been registered yet."
            
            lines = []
            for t in tasks:
                status = t.get("status", "unknown")
                prog = t.get("progress", 0)
                err = f", Error: {t['error']}" if t.get("error") else ""
                lines.append(f"- Task ID: {t['task_id']}, Type: {t['task_type']}, Status: {status}, Progress: {prog}%{err}")
            return "Recent background tasks:\n" + "\n".join(lines)
        except Exception as e:
            return f"Error retrieving tasks: {e}"

    @llm.function_tool(description="Get the detailed status of a specific background task by its ID")
    async def get_background_task_status(self, task_id: str) -> str:
        try:
            task = await asyncio.to_thread(task_manager.get_task, task_id)
            if not task:
                # If not in active memory, check all tasks via get_all_tasks
                all_tasks = await asyncio.to_thread(task_manager.get_all_tasks, 100)
                for t in all_tasks:
                    if t["task_id"] == task_id:
                        status = t.get("status", "unknown")
                        prog = t.get("progress", 0)
                        err = f"\nError: {t['error']}" if t.get("error") else ""
                        res = f"\nResult: {t['result']}" if t.get("result") else ""
                        return f"Task ID: {task_id}\nType: {t['task_type']}\nStatus: {status}\nProgress: {prog}%{res}{err}"
                return f"Task '{task_id}' not found."
            
            info = task.to_dict()
            err = f"\nError: {info['error']}" if info.get("error") else ""
            res = f"\nResult: {info['result']}" if info.get("result") else ""
            return f"Task ID: {task_id}\nType: {info['task_type']}\nStatus: {info['status']}\nProgress: {info['progress']}%{res}{err}"
        except Exception as e:
            return f"Error: {e}"

    @llm.function_tool(description="Cancel a running or queued background task by its ID")
    async def cancel_background_task(self, task_id: str) -> str:
        try:
            cancelled = await asyncio.to_thread(task_manager.cancel_task, task_id)
            if cancelled:
                return f"Task '{task_id}' was successfully cancelled."
            else:
                return f"Could not cancel task '{task_id}'. It may not exist, or it has already completed, failed, or been cancelled."
        except Exception as e:
            return f"Error: {e}"

class MemoryTools(JarvisToolset):
    def __init__(self, memory: MemoryManager, security: SecurityManager, room=None):
        super().__init__(security, room)
        self.memory = memory
        # Instantiate ExecutiveController here
        self.coordinator = None
        if hasattr(self.memory, 'lifecycle'):
            from modules.core.cognitive_coordinator import CognitiveCoordinator
            self.coordinator = CognitiveCoordinator(self.memory)
        self.executive_controller = ExecutiveController(self.memory, self.coordinator)

    @llm.function_tool(description="Remember a preference or fact about the user for long-term storage")
    async def remember_preference(self, key: str, value: str) -> str:
        return await self.safe_execute(self.memory.set_preference, key, value, success_msg=f"Remembered that {key} is {value}.")

    @llm.function_tool(description="Retrieve a preference or fact about the user from long-term storage")
    async def get_preference(self, key: str) -> str:
        val = await self.safe_execute(self.memory.get_preference, key)
        if str(val).startswith("Error:"): return str(val)
        if val is None: return f"No preference found for {key}."
        return f"Preference for {key} is {val}."

    @llm.function_tool(description="Delete a preference or fact from long-term storage")
    async def delete_preference(self, key: str) -> str:
        deleted = await self.safe_execute(self.memory.delete_preference, key)
        if str(deleted).startswith("Error:"): return str(deleted)
        if deleted: return f"Deleted preference for {key}."
        return f"No preference found to delete for {key}."

    @llm.function_tool(description="Search conversation history semantically for specific keywords or topics")
    async def search_memory(self, query: str) -> str:
        results = await self.safe_execute(self.memory.search_history, query)
        if str(results).startswith("Error:"): return str(results)
        if not results: return f"No memories found matching '{query}'."
        formatted = f"Found {len(results)} matching memories:\n"
        for r in results:
            formatted += f"- [{r.get('timestamp','?')}] {r.get('role','?')}: {r.get('content','')[:120]}...\n"
        return formatted

    @llm.function_tool(description="Clear all conversation history. Requires user confirmation.")
    async def clear_history(self, confirmed: bool = False) -> str:
        return await self.safe_execute(self.memory.clear_history, confirmation_category="delete", confirmation_action="memory_history", confirmed=confirmed, success_msg="Conversation history cleared.")

    # ── New memory tools ──────────────────────────────────────────────── #

    @llm.function_tool(
        description="Explicitly store an important fact, experience, or skill into JARVIS long-term memory. "
                    "Use memory_type='semantic' for facts, 'episodic' for past events, 'procedural' for how-to knowledge. "
                    "Optionally specify the project (e.g., 'JARVIS', 'nova', 'react') to namespace the memory."
    )
    async def store_memory(
        self, content: str, memory_type: str = "semantic", project: str = "general", importance: int = 7
    ) -> str:
        row_id = await asyncio.to_thread(
            self.memory.store_memory, content, memory_type, project, importance, None
        )
        return (
            f"Memory stored (ID: {row_id}, type: {memory_type}, project: {project}, importance: {importance}/10)."
        )

    @llm.function_tool(
        description="Search typed long-term memory for a query. "
                    "Optionally filter by memory_type ('semantic', 'episodic', 'procedural') "
                    "and/or project name (e.g., 'JARVIS', 'nova', 'react')."
    )
    async def search_typed_memory(
        self, query: str, memory_type: str = None, project: str = None
    ) -> str:
        results = await asyncio.to_thread(
            self.memory.search_memories, query, memory_type, project, 5
        )
        if not results:
            return f"No typed memories found matching '{query}'."
        lines = [f"Found {len(results)} memories:"]
        for r in results:
            lines.append(
                f"- [{r['memory_type']}][{r['project']}] (imp:{r['importance']}) "
                f"{r['content'][:150]}..."
            )
        return "\n".join(lines)

    @llm.function_tool(
        description="Get all memories JARVIS has about a specific project (e.g., 'JARVIS', 'nova', 'react'). "
                    "Use this to recall everything known about a project before starting work on it."
    )
    async def get_project_context(self, project_name: str) -> str:
        return await asyncio.to_thread(self.memory.get_project_context, project_name)

    @llm.function_tool(
        description="Store a fact about how two things are related in JARVIS knowledge graph. "
                    "Example: entity_a='Akshay', relation='builds', entity_b='JARVIS'. "
                    "Or: entity_a='JARVIS', relation='uses', entity_b='Selenium'."
    )
    async def add_knowledge(
        self, entity_a: str, relation: str, entity_b: str
    ) -> str:
        await asyncio.to_thread(self.memory.add_entity, entity_a, "concept", "")
        await asyncio.to_thread(self.memory.add_entity, entity_b, "concept", "")
        await asyncio.to_thread(self.memory.add_relationship, entity_a, relation, entity_b, 1.0)
        return f"Knowledge stored: {entity_a} → {relation} → {entity_b}."

    @llm.function_tool(
        description="Get recent JARVIS self-reflections — insights about user habits, workflow patterns, "
                    "and lessons learned. Specify days (default 7) to look back."
    )
    async def get_agent_reflections(self, days: int = 7) -> str:
        reflections = await asyncio.to_thread(self.memory.get_agent_reflections, days)
        if not reflections:
            return f"No reflections found in the past {days} days."
        lines = [f"JARVIS reflections (last {days} days):"]
        for r in reflections[:5]:
            lines.append(f"\n[{r['created_at'][:10]}]\n{r['reflection'][:400]}")
        return "\n".join(lines)

    @llm.function_tool(
        description="Restore the last saved agent state after a restart or crash. "
                    "Returns the previous goal and plan so JARVIS can resume where it left off."
    )
    async def restore_agent_state(self) -> str:
        saved = await asyncio.to_thread(self.memory.restore_agent_state)
        if not saved:
            return "No saved agent state found. Starting fresh."
        goal = saved.get("current_goal", "Unknown")
        plan = saved.get("active_plan")
        saved_at = saved.get("saved_at", "unknown time")
        if plan:
            tasks = plan.get("subtasks", [])
            pending = [t["description"] for t in tasks if t.get("status") == "pending"]
            return (
                f"Restored state from {saved_at}.\n"
                f"Previous goal: {goal}\n"
                f"Pending tasks: {pending}"
            )
        return f"Restored state from {saved_at}. Previous goal: {goal}. No active plan."

    # ── Phase 5 cognitive tools ───────────────────────────────────────── #

    @llm.function_tool(
        description="Query the Executive Controller for the current state, top priorities, and immediate directives. "
                    "Use this when you are unsure what to do next or if the system seems stuck."
    )
    async def get_executive_summary(self) -> str:
        return self.executive_controller.get_executive_summary()

    @llm.function_tool(
        description="Set or update an active ROOT goal for JARVIS. "
                    "Goals influence which memories are retrieved (goal-relevance scoring). "
                    "Priority 1-10 (10=highest). Optionally specify project name. "
                    "Goal type defaults to 'strategic' or 'project'."
    )
    async def set_active_goal(
        self, goal: str, goal_type: str = "strategic", priority: int = 7, project: str = "general"
    ) -> str:
        goal_id = await asyncio.to_thread(
            self.memory.lifecycle.goal_memory.set_goal, goal, goal_type, None, priority, project
        )
        return f"Root Goal set (ID: {goal_id}): '{goal}' [{goal_type}, priority {priority}/10, project: {project}]."

    @llm.function_tool(
        description="Add a nested sub-goal to an existing goal. "
                    "Use this to break down strategic goals into project/task/action goals. "
                    "goal_type can be 'project', 'task', or 'action'."
    )
    async def add_sub_goal(self, parent_id: int, goal: str, goal_type: str = "task", priority: int = 5) -> str:
        goal_id = await asyncio.to_thread(
            self.memory.lifecycle.goal_memory.add_sub_goal, parent_id, goal, goal_type, priority
        )
        return f"Sub-goal set (ID: {goal_id}) under Parent {parent_id}: '{goal}' [{goal_type}]."

    @llm.function_tool(
        description="List all active goals JARVIS is currently tracking. "
                    "Displays the full goal hierarchy (Strategic -> Project -> Task -> Action)."
    )
    async def list_active_goals(self) -> str:
        context_str = await asyncio.to_thread(
            self.memory.lifecycle.goal_memory.goal_context_string
        )
        if not context_str:
            return "No active goals set. Use set_active_goal to add one."
        return context_str

    @llm.function_tool(
        description="Mark an active goal as completed or failed. "
                    "This archives the goal to episodic memory for reflection. "
                    "Use list_active_goals first to get the goal_id."
    )
    async def complete_goal(self, goal_id: int, outcome: str = "completed") -> str:
        success = await asyncio.to_thread(
            self.memory.lifecycle.goal_memory.complete_goal, goal_id, outcome
        )
        if success:
            return f"Goal {goal_id} marked as '{outcome}' and archived to episodic memory."
        return f"Goal {goal_id} not found."

    @llm.function_tool(
        description="Get a performance report for all tools JARVIS has used. "
                    "Shows success rates, average execution times, and reliability scores. "
                    "Use this to identify unreliable tools before executing risky tasks."
    )
    async def get_tool_performance(self) -> str:
        return await asyncio.to_thread(
            self.memory.lifecycle.tool_memory.get_all_tool_report
        )

    @llm.function_tool(
        description="Retrieve lessons JARVIS has learned from past failures and experience replay. "
                    "Optionally filter by topic (e.g., 'selenium', 'google', 'download'). "
                    "Use this before attempting a task that has previously failed."
    )
    async def get_lessons_learned(self, topic: str = "") -> str:
        try:
            if topic:
                with self.memory._lock:
                    rows = self.memory.dbs["conversations"].execute(
                        """SELECT lesson, occurrence_count, last_triggered
                           FROM lessons_learned
                           WHERE lesson LIKE ? OR source_pattern LIKE ?
                           ORDER BY importance DESC, last_triggered DESC
                           LIMIT 5""",
                        (f"%{topic}%", f"%{topic}%"),
                    ).fetchall()
            else:
                with self.memory._lock:
                    rows = self.memory.dbs["conversations"].execute(
                        """SELECT lesson, occurrence_count, last_triggered
                           FROM lessons_learned
                           ORDER BY importance DESC, last_triggered DESC
                           LIMIT 8""",
                    ).fetchall()

            if not rows:
                return f"No lessons found{f' for topic: {topic}' if topic else ''}."
            lines = ["Lessons Learned:"]
            for lesson, count, last in rows:
                lines.append(f"\n[seen {count}x, last: {last[:10]}]\n  {lesson[:300]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error retrieving lessons: {e}"

    @llm.function_tool(
        description="Get a summary of JARVIS's known capabilities, limitations, and confidence levels. "
                    "Use this to understand what JARVIS can and cannot do before planning complex tasks."
    )
    async def get_agent_self_model(self) -> str:
        ctx = await asyncio.to_thread(self.memory.lifecycle.get_self_model_context)
        if not ctx:
            return "Agent self-model not yet initialized."
        return ctx


class Assistant(Agent):
    def __init__(self, memory: MemoryManager) -> None:
        base_prompt = JarvisBehavior.get_full_system_prompt()
        
        context = memory.get_full_context()
        if context:
            base_prompt += "\n\n" + context
            
        super().__init__(instructions=base_prompt)

server = AgentServer()

@server.rtc_session(agent_name=os.environ.get("AGENT_NAME", "jarvis"))
async def my_agent(ctx: agents.JobContext):
    # Initialize long-lived components
    memory = MemoryManager()
    security = SecurityManager()
    world_state = WorldStateManager()
    verification = VerificationEngine(world_state)

    tools = [
        SystemTools(security=security, room=ctx.room),
        WindowTools(security=security, room=ctx.room),
        AppTools(security=security, room=ctx.room),
        BrowserTools(security=security, room=ctx.room),
        MediaTools(security=security, room=ctx.room),
        KeyboardTools(security=security, room=ctx.room),
        MouseTools(security=security, room=ctx.room),
        FileTools(security=security, room=ctx.room),
        TaskTools(security=security, room=ctx.room),
        MemoryTools(memory=memory, security=security, room=ctx.room),
        TaskPlannerTools(memory=memory),
        VerificationTools(verification=verification, security=security, room=ctx.room)
    ]

    session = AgentSession(
        llm=google.beta.realtime.RealtimeModel(
            model="models/gemini-2.5-flash-native-audio-preview-12-2025",
            voice="Charon",
            temperature=0.3
        ),
        tools=tools
    )

    await session.start(
        room=ctx.room,
        agent=Assistant(memory=memory),
    )

    # Start WebRTC stats stream to frontend
    async def stats_publisher():
        import json
        import psutil
        import logging
        logger = logging.getLogger("JARVIS.Agent")
        while ctx.room.isconnected():
            try:
                cpu_percent = await asyncio.to_thread(psutil.cpu_percent, 0)
                simulated_temp = 42.0 + (cpu_percent * 0.43)
                payload = json.dumps({
                    "type": "stats",
                    "cpu": cpu_percent,
                    "temp": round(simulated_temp, 1)
                })
                await ctx.room.local_participant.publish_data(payload.encode('utf-8'), reliable=False)
            except Exception as e:
                logger.warning(f"Failed to publish WebRTC stats: {e}")
            await asyncio.sleep(3)

    asyncio.create_task(stats_publisher())

    # Force JARVIS to speak his intro immediately without waiting for the user
    try:
        intro_instruction = """System connection established. Please greet the user proactively using exactly this message:
Welcome back, Sir.
J.A.R.V.I.S. successfully online ho gaya hai.
Saare required systems connect aur ready hain.
Main aapke instructions ke liye taiyar hoon.
Batayein Sir, kya karna hai?"""
        session.history.add_message(role="user", content=intro_instruction)
        reply_coro = session.generate_reply()
        if asyncio.iscoroutine(reply_coro):
            asyncio.create_task(reply_coro)
    except Exception as e:
        import logging
        logging.getLogger("JARVIS.Agent").error(f"Failed to force intro: {e}")

if __name__ == "__main__":
    agents.cli.run_app(server)