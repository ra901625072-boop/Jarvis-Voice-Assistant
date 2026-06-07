import os
from dotenv import load_dotenv
from typing import Annotated
import asyncio

from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent, room_io, llm
from livekit.plugins import (
    google,
)

# Import all controllers from our modules
from modules.app_controller import AppController
from modules.browser_controller import BrowserController
from modules.volume_controller import VolumeController
from modules.brightness_controller import BrightnessController
from modules.keyboard_controller import KeyboardController
from modules.mouse_controller import MouseController
from modules.file_manager import FileManager
from modules.window_controller import WindowController
from modules.system_controller import SystemController

# Import memory, security, and behavior modules
from modules.memory_manager import MemoryManager
from modules.security_manager import SecurityManager
from modules.behavior import JarvisBehavior

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path)

class AssistantTools(llm.Toolset):
    def __init__(self, memory: MemoryManager, security: SecurityManager):
        super().__init__(id="assistant_tools")
        self.app_ctrl = AppController()
        self.browser_ctrl = BrowserController()
        self.volume_ctrl = VolumeController()
        self.brightness_ctrl = BrightnessController()
        self.keyboard_ctrl = KeyboardController()
        self.mouse_ctrl = MouseController()
        self.file_mgr = FileManager()
        self.window_ctrl = WindowController()
        self.system_ctrl = SystemController()
        self.memory = memory
        self.security = security

    # --- SystemController ---
    @llm.function_tool(description="Shutdown the computer system. Requires user confirmation.")
    async def shutdown_system(self, confirmed: bool = False) -> str:
        if self.security.requires_confirmation("power", "shutdown") and not confirmed:
            return "SECURITY WARNING: This action requires user confirmation. Please ask the user to confirm they want to shutdown the computer. Once they agree, call this tool again with confirmed=True."
        success = await asyncio.to_thread(self.system_ctrl.shutdown)
        return "Shutting down the system..." if success else "Failed to shutdown the system."

    @llm.function_tool(description="Restart the computer system. Requires user confirmation.")
    async def restart_system(self, confirmed: bool = False) -> str:
        if self.security.requires_confirmation("power", "restart") and not confirmed:
            return "SECURITY WARNING: This action requires user confirmation. Please ask the user to confirm they want to restart the computer. Once they agree, call this tool again with confirmed=True."
        success = await asyncio.to_thread(self.system_ctrl.restart)
        return "Restarting the system..." if success else "Failed to restart the system."

    @llm.function_tool(description="Put the computer to sleep.")
    async def sleep_system(self) -> str:
        success = await asyncio.to_thread(self.system_ctrl.sleep)
        return "System entering sleep mode." if success else "Failed to put system to sleep."

    @llm.function_tool(description="Lock the computer workstation.")
    async def lock_pc(self) -> str:
        success = await asyncio.to_thread(self.system_ctrl.lock_pc)
        return "Workstation locked." if success else "Failed to lock workstation."

    @llm.function_tool(description="Log out the current user.")
    async def logout_user(self, confirmed: bool = False) -> str:
        if self.security.requires_confirmation("power", "logout") and not confirmed:
            return "SECURITY WARNING: This action requires user confirmation. Please ask the user to confirm they want to log out. Once they agree, call this tool again with confirmed=True."
        success = await asyncio.to_thread(self.system_ctrl.logout)
        return "Logging out..." if success else "Failed to log out."

    @llm.function_tool(description="Copy text to the system clipboard.")
    async def copy_to_clipboard(self, text: str) -> str:
        await asyncio.to_thread(self.system_ctrl.copy_text, text)
        return "Text copied to clipboard."

    @llm.function_tool(description="Get the current text from the system clipboard.")
    async def get_from_clipboard(self) -> str:
        content = await asyncio.to_thread(self.system_ctrl.get_clipboard)
        return f"Clipboard content: {content}" if content else "Clipboard is empty."

    @llm.function_tool(description="Clear the system clipboard.")
    async def clear_clipboard(self) -> str:
        await asyncio.to_thread(self.system_ctrl.clear_clipboard)
        return "Clipboard cleared."

    @llm.function_tool(description="Take a screenshot of the computer screen.")
    async def take_screenshot(self) -> str:
        success = await asyncio.to_thread(self.system_ctrl.take_screenshot)
        return "Screenshot saved to screenshot.png." if success else "Failed to take screenshot."

    @llm.function_tool(description="Open the Windows system settings app.")
    async def open_settings(self) -> str:
        await asyncio.to_thread(self.system_ctrl.open_settings)
        return "Settings opened."

    @llm.function_tool(description="Open the Windows WiFi settings.")
    async def open_wifi_settings(self) -> str:
        await asyncio.to_thread(self.system_ctrl.open_wifi_settings)
        return "WiFi settings opened."

    @llm.function_tool(description="Open the Windows Bluetooth settings.")
    async def open_bluetooth_settings(self) -> str:
        await asyncio.to_thread(self.system_ctrl.open_bluetooth_settings)
        return "Bluetooth settings opened."

    @llm.function_tool(description="Open the Windows Display settings.")
    async def open_display_settings(self) -> str:
        await asyncio.to_thread(self.system_ctrl.open_display_settings)
        return "Display settings opened."

    # --- WindowController ---
    @llm.function_tool(description="Minimize a window by its title keyword, or the active window if none provided.")
    async def minimize_window(self, title_keyword: str = None) -> str:
        success = await asyncio.to_thread(self.window_ctrl.minimize_window, title_keyword)
        return "Window minimized." if success else "Failed to find or minimize window."

    @llm.function_tool(description="Maximize a window by its title keyword, or the active window if none provided.")
    async def maximize_window(self, title_keyword: str = None) -> str:
        success = await asyncio.to_thread(self.window_ctrl.maximize_window, title_keyword)
        return "Window maximized." if success else "Failed to find or maximize window."

    @llm.function_tool(description="Restore a window to its normal size by its title keyword, or the active window if none provided.")
    async def restore_window(self, title_keyword: str = None) -> str:
        success = await asyncio.to_thread(self.window_ctrl.restore_window, title_keyword)
        return "Window restored." if success else "Failed to find or restore window."

    @llm.function_tool(description="Close a window by its title keyword, or the active window if none provided.")
    async def close_window(self, title_keyword: str = None) -> str:
        success = await asyncio.to_thread(self.window_ctrl.close_window, title_keyword)
        return "Window closed." if success else "Failed to find or close window."

    @llm.function_tool(description="Bring a window to the foreground and focus it by its title keyword.")
    async def focus_window(self, title_keyword: str = None) -> str:
        success = await asyncio.to_thread(self.window_ctrl.focus_window, title_keyword)
        return "Window focused." if success else "Failed to find or focus window."

    @llm.function_tool(description="Switch to the next window (simulates Alt+Tab).")
    async def switch_window(self) -> str:
        await asyncio.to_thread(self.window_ctrl.switch_window)
        return "Switched window."

    @llm.function_tool(description="Show the desktop (minimizes all windows).")
    async def show_desktop(self) -> str:
        await asyncio.to_thread(self.window_ctrl.show_desktop)
        return "Showing desktop."

    # --- AppController ---
    @llm.function_tool(description="Open an application by its name (e.g., notepad, calculator, chrome)")
    async def open_application(self, app_name: str) -> str:
        success = await asyncio.to_thread(self.app_ctrl.open_app, app_name)
        return f"Successfully opened {app_name}." if success else f"Failed to open {app_name}."

    @llm.function_tool(description="Close a running application by its name")
    async def close_application(self, app_name: str) -> str:
        await asyncio.to_thread(self.app_ctrl.close_app, app_name)
        return f"Attempted to close {app_name}."

    # --- BrowserController ---
    @llm.function_tool(description="Open a specific URL in the browser")
    async def open_url(self, url: str) -> str:
        await asyncio.to_thread(self.browser_ctrl.open_url, url)
        return f"Opened {url} in the browser."

    @llm.function_tool(description="Close a specific website tab by domain or title")
    async def close_website(self, domain_or_title: str) -> str:
        success = await asyncio.to_thread(self.browser_ctrl.close_website, domain_or_title)
        if success:
            return f"Closed website tab matching '{domain_or_title}'."
        return f"Could not find or close website tab matching '{domain_or_title}'."

    @llm.function_tool(description="Search Google for a specific query")
    async def search_google(self, query: str) -> str:
        await asyncio.to_thread(self.browser_ctrl.search, query)
        return f"Performed Google search for {query}."

    @llm.function_tool(description="Search YouTube for a specific query")
    async def search_youtube(self, query: str) -> str:
        await asyncio.to_thread(self.browser_ctrl.search_youtube, query)
        return f"Performed YouTube search for {query}."

    @llm.function_tool(description="Search YouTube and automatically play the first video result")
    async def play_youtube(self, query: str) -> str:
        await asyncio.to_thread(self.browser_ctrl.play_youtube, query)
        return f"Playing YouTube video for {query}."

    @llm.function_tool(description="Switch to a browser tab matching a keyword")
    async def switch_tab(self, keyword: str) -> str:
        success = await asyncio.to_thread(self.browser_ctrl.switch_tab, keyword)
        return f"Switched to tab matching {keyword}." if success else f"No tab found matching {keyword}."

    @llm.function_tool(description="List all open browser tabs")
    async def list_tabs(self) -> str:
        tabs = await asyncio.to_thread(self.browser_ctrl.list_tabs)
        if not tabs:
            return "No tabs are open or browser is not running."
        formatted = "Open tabs:\n" + "\n".join([f"- {t['title']} ({t['url']})" for t in tabs])
        return formatted

    @llm.function_tool(description="Refresh the current browser tab")
    async def refresh_tab(self) -> str:
        await asyncio.to_thread(self.browser_ctrl.refresh_tab)
        return "Refreshed the current tab."

    @llm.function_tool(description="Go back to the previous page in the browser")
    async def browser_go_back(self) -> str:
        await asyncio.to_thread(self.browser_ctrl.go_back)
        return "Navigated back."

    @llm.function_tool(description="Go forward to the next page in the browser")
    async def browser_go_forward(self) -> str:
        await asyncio.to_thread(self.browser_ctrl.go_forward)
        return "Navigated forward."

    @llm.function_tool(description="Get the title and URL of the current browser page")
    async def get_current_page_info(self) -> str:
        info = await asyncio.to_thread(self.browser_ctrl.get_current_page_info)
        return f"Currently viewing: {info.get('title')} at {info.get('url')}."

    # --- VolumeController ---
    @llm.function_tool(description="Set the system volume to a specific percentage (0-100)")
    async def set_volume(self, level: int) -> str:
        await asyncio.to_thread(self.volume_ctrl.set_volume, level)
        return f"Volume set to {level}%."

    @llm.function_tool(description="Mute the system audio")
    async def mute_audio(self) -> str:
        await asyncio.to_thread(self.volume_ctrl.mute)
        return "Audio muted."

    @llm.function_tool(description="Unmute the system audio")
    async def unmute_audio(self) -> str:
        await asyncio.to_thread(self.volume_ctrl.unmute)
        return "Audio unmuted."

    # --- BrightnessController ---
    @llm.function_tool(description="Set the system display brightness to a specific percentage (0-100)")
    async def set_brightness(self, level: int) -> str:
        await asyncio.to_thread(self.brightness_ctrl.set_brightness, level)
        return f"Brightness set to {level}%."

    # --- KeyboardController ---
    @llm.function_tool(description="Type a given text string exactly using the keyboard")
    async def type_text(self, text: str) -> str:
        await asyncio.to_thread(self.keyboard_ctrl.type_text, text)
        return f"Typed the given text."

    @llm.function_tool(description="Press a specific key or key combination string (e.g., 'enter', 'ctrl+c', 'win+d')")
    async def press_key(self, keys: str) -> str:
        await asyncio.to_thread(self.keyboard_ctrl.press_key, keys)
        return f"Pressed keys: {keys}."

    @llm.function_tool(description="Hold down a specific key (e.g., 'shift', 'ctrl', 'a')")
    async def hold_key(self, key: str) -> str:
        await asyncio.to_thread(self.keyboard_ctrl.hold_key, key)
        return f"Held down key: {key}."

    @llm.function_tool(description="Release a specific key that was previously held down")
    async def release_key(self, key: str) -> str:
        await asyncio.to_thread(self.keyboard_ctrl.release_key, key)
        return f"Released key: {key}."

    # --- MouseController ---
    @llm.function_tool(description="Left click the mouse at its current location, or optionally at specified x,y coordinates")
    async def click_mouse(self, x: int = None, y: int = None) -> str:
        await asyncio.to_thread(self.mouse_ctrl.click, x, y)
        return "Mouse left-clicked."

    @llm.function_tool(description="Double left click the mouse at its current location, or optionally at specified x,y coordinates")
    async def double_click_mouse(self, x: int = None, y: int = None) -> str:
        await asyncio.to_thread(self.mouse_ctrl.double_click, x, y)
        return "Mouse double-clicked."

    @llm.function_tool(description="Right click the mouse at its current location, or optionally at specified x,y coordinates")
    async def right_click_mouse(self, x: int = None, y: int = None) -> str:
        await asyncio.to_thread(self.mouse_ctrl.right_click, x, y)
        return "Mouse right-clicked."

    @llm.function_tool(description="Move the mouse cursor to the specified absolute x,y coordinates on the screen")
    async def move_mouse(self, x: int, y: int) -> str:
        await asyncio.to_thread(self.mouse_ctrl.move, x, y)
        return f"Mouse moved to {x},{y}."

    @llm.function_tool(description="Scroll the mouse wheel. Positive amount scrolls up, negative amount scrolls down")
    async def scroll_mouse(self, amount: int) -> str:
        await asyncio.to_thread(self.mouse_ctrl.scroll, amount)
        return f"Mouse scrolled by {amount}."

    @llm.function_tool(description="Get the current x,y coordinates of the mouse cursor")
    async def get_mouse_position(self) -> str:
        x, y = await asyncio.to_thread(self.mouse_ctrl.get_position)
        return f"Mouse is currently at {x},{y}."

    # --- FileManager ---
    @llm.function_tool(description="Resolve a file query like 'my resume' into an absolute path")
    async def resolve_file_path(self, query: str) -> str:
        path = await asyncio.to_thread(self.file_mgr.resolve_path, query)
        return f"Resolved to: {path}" if path else f"Could not find any file matching '{query}'."

    @llm.function_tool(description="Search for a file by name starting from a root directory or default user directory")
    async def search_file(self, filename: str, root_dir: str = None) -> str:
        results = await asyncio.to_thread(self.file_mgr.search_file, filename, root_dir)
        if not results:
            return f"No results found for {filename}."
        return f"Found {len(results)} results: {', '.join(results[:5])}" + ("..." if len(results) > 5 else "")

    @llm.function_tool(description="Create a new folder at the specified path")
    async def create_folder(self, path: str) -> str:
        await asyncio.to_thread(self.file_mgr.create_folder, path)
        return f"Folder {path} created."

    @llm.function_tool(description="Create a new file with optional content at the specified path")
    async def create_file(self, path: str, content: str = "") -> str:
        success = await asyncio.to_thread(self.file_mgr.create_file, path, content)
        return f"File {path} created." if success else f"Failed to create file {path}."

    @llm.function_tool(description="Read the contents of a text file")
    async def read_file(self, path: str) -> str:
        content = await asyncio.to_thread(self.file_mgr.read_file, path)
        if content is None:
            return f"Failed to read file {path}."
        # Limit content length to avoid massive context injections
        return f"File contents:\n{content[:2000]}" + ("...\n[Content Truncated]" if len(content) > 2000 else "")

    @llm.function_tool(description="Delete a file or folder at the specified path. Set confirmed to True if the user has explicitly agreed to delete it.")
    async def delete_item(self, path: str, confirmed: bool = False) -> str:
        if self.security.requires_confirmation("delete", path) and not confirmed:
            return "SECURITY WARNING: This action requires user confirmation. Please ask the user to confirm they want to delete this item. Once they agree, call this tool again with confirmed=True."
        
        await asyncio.to_thread(self.file_mgr.delete_item, path)
        return f"Item {path} deleted (moved to recycle bin)."

    @llm.function_tool(description="Move a file or folder from src to dest path")
    async def move_item(self, src: str, dest: str) -> str:
        await asyncio.to_thread(self.file_mgr.move_item, src, dest)
        return f"Item moved from {src} to {dest}."

    @llm.function_tool(description="Copy a file or folder from src to dest path")
    async def copy_item(self, src: str, dest: str) -> str:
        await asyncio.to_thread(self.file_mgr.copy_item, src, dest)
        return f"Item copied from {src} to {dest}."

    @llm.function_tool(description="Rename a file or folder")
    async def rename_item(self, src: str, new_name: str) -> str:
        await asyncio.to_thread(self.file_mgr.rename_item, src, new_name)
        return f"Item renamed from {src} to {new_name}."

    @llm.function_tool(description="Open a file or folder natively in the OS")
    async def open_item(self, path: str) -> str:
        await asyncio.to_thread(self.file_mgr.open_item, path)
        return f"Opened {path}."

    @llm.function_tool(description="Get size, creation date, and metadata about a file")
    async def get_file_info(self, path: str) -> str:
        info = await asyncio.to_thread(self.file_mgr.get_file_info, path)
        return f"File Info: {info}" if info else f"Failed to get info for {path}."

    @llm.function_tool(description="List the contents of a directory")
    async def list_directory(self, path: str) -> str:
        items = await asyncio.to_thread(self.file_mgr.list_directory, path)
        return f"Directory contains {len(items)} items: {', '.join(items[:20])}" + ("..." if len(items) > 20 else "")

    @llm.function_tool(description="Close an open folder window or file window")
    async def close_item(self, path: str) -> str:
        await asyncio.to_thread(self.file_mgr.close_item, path)
        return f"Attempted to close {path}."

    # --- MemoryManager ---
    @llm.function_tool(description="Remember a preference or fact about the user for long-term storage")
    async def remember_preference(self, key: str, value: str) -> str:
        await asyncio.to_thread(self.memory.set_preference, key, value)
        return f"Remembered that {key} is {value}."

    @llm.function_tool(description="Retrieve a preference or fact about the user from long-term storage")
    async def get_preference(self, key: str) -> str:
        val = await asyncio.to_thread(self.memory.get_preference, key)
        if val is None:
            return f"No preference found for {key}."
        return f"Preference for {key} is {val}."

    @llm.function_tool(description="Delete a preference or fact from long-term storage")
    async def delete_preference(self, key: str) -> str:
        deleted = await asyncio.to_thread(self.memory.delete_preference, key)
        if deleted:
            return f"Deleted preference for {key}."
        return f"No preference found to delete for {key}."

    @llm.function_tool(description="Search conversation history semantically for specific keywords or topics")
    async def search_memory(self, query: str) -> str:
        results = await asyncio.to_thread(self.memory.search_history, query)
        if not results:
            return f"No memories found matching '{query}'."
        
        formatted = f"Found {len(results)} matching memories:\n"
        for r in results:
            formatted += f"- [{r['timestamp']}] {r['role']}: {r['content'][:100]}...\n"
        return formatted

    @llm.function_tool(description="Clear all conversation history. Requires user confirmation.")
    async def clear_history(self, confirmed: bool = False) -> str:
        if self.security.requires_confirmation("delete", "memory_history") and not confirmed:
            return "SECURITY WARNING: This action requires user confirmation. Please ask the user to confirm they want to clear their memory history. Once they agree, call this tool again with confirmed=True."
        
        await asyncio.to_thread(self.memory.clear_history)
        return "Conversation history cleared."

class Assistant(Agent):
    def __init__(self, memory: MemoryManager) -> None:
        base_prompt = JarvisBehavior.get_full_system_prompt()
        
        context = memory.get_full_context()
        if context:
            base_prompt += "\n\n" + context
            
        super().__init__(instructions=base_prompt)

server = AgentServer()

@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: agents.JobContext):
    # Initialize long-lived components
    memory = MemoryManager()
    security = SecurityManager()
    
    session = AgentSession(
        llm=google.beta.realtime.RealtimeModel(
            model="gemini-2.5-flash-native-audio-latest",
            voice="Charon"
        ),
        tools=[AssistantTools(memory=memory, security=security)]
    )

    await session.start(
        room=ctx.room,
        agent=Assistant(memory=memory),
    )

    await session.generate_reply(
        instructions="Greet the user warmly as JARVIS and announce that your systems are fully online."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)