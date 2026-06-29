"""
toolsets/file_tools.py — FileTools toolset.

Phase 5.6: _transfer_item() helper de-duplicates move/copy logic.
Phase 2.1: All path-safety checks route through SecurityManager.is_safe_path().
"""
import asyncio
import os
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.core.security_manager import SecurityManager


# ── Module-level singletons (lazy-init on first access) ─────────────────────
_global_file_mgr = None
_global_folder_mgr = None


def _get_file_mgr():
    global _global_file_mgr
    if _global_file_mgr is None:
        from modules.filesystem.file_manager import FileManager
        _global_file_mgr = FileManager()
    return _global_file_mgr


def _get_folder_mgr():
    global _global_folder_mgr
    if _global_folder_mgr is None:
        from modules.filesystem.folder_manager import FolderManager
        _global_folder_mgr = FolderManager(file_mgr=_get_file_mgr())
    return _global_folder_mgr


class FileTools(JarvisToolset):
    """
    FileTools manages filesystem operations including directory lookups, file
    creation/deletion, renaming, and reading files.

    SYSTEM PROMPT:
    Use FileTools to browse paths and edit files. Always verify folders exist,
    resolve path aliases, and require explicit confirmation for destructive
    actions like delete_item().

    SHORT DESCRIPTION:
    Provides programmatic commands to manipulate files, directories, names, and
    listings on local disk storage.

    PROCESS:
    1. Resolves relative path search keywords.
    2. Performs directory lookup, creation, and item metadata queries.
    3. Handles reading text documents, moving/copying items synchronously, or
       transferring via background task manager for cross-drive operations.

    FLOW:
    Agent -> Tool call -> FileManager / FolderManager
          -> Python standard library (os/shutil) -> Agent
    """

    def __init__(self, security: SecurityManager, room=None):
        super().__init__(security, room)

    def _enforce_mcp_root(self, *paths) -> str:
        fs_root = os.environ.get("JARVIS_MCP_FS_ROOT")
        if not fs_root:
            return ""
        fs_root = os.path.normpath(os.path.abspath(fs_root))
        for p in paths:
            if p:
                abs_p = os.path.normpath(os.path.abspath(p))
                if not abs_p.startswith(fs_root):
                    return f"Error: Path '{p}' is outside the allowed JARVIS_MCP_FS_ROOT."
        return ""

    @property
    def file_mgr(self):
        return _get_file_mgr()

    @property
    def folder_mgr(self):
        return _get_folder_mgr()

    # ── Internal helper ──────────────────────────────────────────────────────

    async def _transfer_item(
        self,
        src: str,
        dest: str,
        operation: str,  # "move" or "copy"
        confirmed: bool = False,
    ) -> str:
        """
        Shared logic for move_item and copy_item.

        - Validates paths via SecurityManager.is_safe_path().
        - Routes cross-drive large transfers to BackgroundTaskManager.
        - Sync transfers for same-drive or small files.
        """
        try:
            src_abs = os.path.normpath(os.path.abspath(src))
            dest_abs = os.path.normpath(os.path.abspath(dest))

            # Security path check
            root_err = self._enforce_mcp_root(src_abs, dest_abs)
            if root_err:
                return root_err
                
            if self.security:
                if not self.security.is_safe_path(src_abs) or not self.security.is_safe_path(dest_abs):
                    return "Error: Security Policy blocks operating on system folder/file."

            # Confirmation gate (only for move)
            if operation == "move":
                confirm_res = await self.safe_execute(
                    asyncio.sleep, 0,
                    confirmation_category="move",
                    confirmation_action=f"move '{src}' to '{dest}'",
                    confirmed=confirmed,
                )
                if isinstance(confirm_res, str) and "SECURITY WARNING" in confirm_res:
                    return confirm_res

            is_dir = os.path.isdir(src_abs)
            src_drive = os.path.splitdrive(src_abs)[0].lower()
            dest_drive = os.path.splitdrive(dest_abs)[0].lower()
            is_cross_drive = src_drive != dest_drive

            # Check if large file
            large_file = False
            if is_cross_drive and not is_dir:
                try:
                    large_file = os.path.getsize(src_abs) > 50 * 1024 * 1024
                except Exception:
                    pass

            use_background = is_cross_drive and (is_dir or large_file)

            if use_background:
                from modules.planning.task_manager import BackgroundTaskManager
                from modules.filesystem.file_manager import FileManager
                from modules.filesystem.folder_manager import FolderManager

                bg_mgr = BackgroundTaskManager()

                def _handle_op(context, s, d):
                    context.update_progress(10)
                    if is_dir:
                        mgr = FolderManager(file_mgr=FileManager())
                        res = (mgr.move_folder(s, d) if operation == "move" else mgr.copy_folder(s, d))
                    else:
                        fmgr = FileManager()
                        res = (fmgr.move_item(s, d, force_sync=True) if operation == "move" else fmgr.copy_item(s, d))
                    if isinstance(res, str) and res.startswith("Error:"):
                        raise RuntimeError(res)
                    context.update_progress(100)
                    return res

                task_type = f"{operation}_{'folder' if is_dir else 'file'}"
                try:
                    bg_mgr.register_handler(task_type, _handle_op)
                except Exception:
                    pass
                bg_mgr.start()
                task_id = bg_mgr.add_task(task_type, args=(src_abs, dest_abs))
                return (
                    f"The {operation} of '{'folder' if is_dir else 'file'}' '{src}' to '{dest}' "
                    f"has started in the background (Task ID: {task_id}). "
                    "You can check its status using get_background_task_status."
                )
            else:
                if is_dir:
                    if operation == "move":
                        result = await self.safe_execute(self.folder_mgr.move_folder, src_abs, dest_abs)
                    else:
                        return await self.safe_execute(
                            self.folder_mgr.copy_folder,
                            src_abs,
                            dest_abs,
                            success_msg=f"Folder {'moved' if operation == 'move' else 'copied'} from {src} to {dest}.",
                        )
                else:
                    if operation == "move":
                        result = await self.safe_execute(self.file_mgr.move_item, src_abs, dest_abs)
                    else:
                        return await self.safe_execute(
                            self.file_mgr.copy_item,
                            src_abs,
                            dest_abs,
                            success_msg=f"File copied from {src} to {dest}.",
                        )

                if result is True:
                    return f"Successfully {operation}d {'folder' if is_dir else 'file'} {src} to {dest}."
                return str(result)
        except Exception as e:
            return f"Error: {e}"

    # ── Public tools ─────────────────────────────────────────────────────────

    @llm.function_tool(
        description="Resolve a file or folder query like 'my resume' or 'PythonProjects' into an absolute path"
    )
    async def resolve_file_path(self, query: str) -> str:
        path = await self.safe_execute(self.file_mgr.resolve_path, query)
        if str(path).startswith("Error:"):
            return str(path)
        if isinstance(path, list):
            options = "\n".join([f"- {p}" for p in path])
            return (
                f"AMBIGUOUS_MATCHES: Multiple items found matching '{query}'. "
                f"Please ask the user to clarify which one they want:\n{options}"
            )
        return f"Resolved to: {path}" if path else f"Could not find any file or folder matching '{query}'."

    @llm.function_tool(
        description="Search for a file or folder by name starting from a root directory or default user directory"
    )
    async def search_file(self, filename: str, root_dir: str = None) -> str:
        results = await self.safe_execute(self.file_mgr.search_file, filename, root_dir)
        if str(results).startswith("Error:"):
            return str(results)
        if not results:
            return f"No file or folder results found for {filename}."
        return f"Found {len(results)} results: {', '.join(results[:5])}" + (
            "..." if len(results) > 5 else ""
        )

    @llm.function_tool(description="Create a new folder at the specified path")
    async def create_folder(self, path: str) -> str:
        root_err = self._enforce_mcp_root(path)
        if root_err: return root_err
        return await self.safe_execute(
            self.folder_mgr.create_folder, path, success_msg=f"Folder {path} created."
        )

    @llm.function_tool(description="Create a new file with optional content at the specified path")
    async def create_file(self, path: str, content: str = "") -> str:
        root_err = self._enforce_mcp_root(path)
        if root_err: return root_err
        return await self.safe_execute(
            self.file_mgr.create_file,
            path,
            content,
            success_msg=f"File {path} created.",
            error_msg=f"Failed to create file {path}.",
        )

    @llm.function_tool(description="Read the contents of a text file")
    async def read_file(self, path: str) -> str:
        content = await self.safe_execute(self.file_mgr.read_file, path)
        if str(content).startswith("Error:"):
            return str(content)
        if content is None:
            return f"Failed to read file {path}."
        return f"File contents:\n{content[:2000]}" + (
            "...\n[Content Truncated]" if len(content) > 2000 else ""
        )

    @llm.function_tool(description="Delete a file or folder at the specified path. Requires confirmation.")
    async def delete_item(self, path: str, confirmed: bool = False) -> str:
        root_err = self._enforce_mcp_root(path)
        if root_err: return root_err
        if os.path.isdir(path):
            return await self.safe_execute(
                self.folder_mgr.delete_folder,
                path,
                confirmation_category="delete",
                confirmation_action=path,
                confirmed=confirmed,
                success_msg=f"Folder {path} deleted (moved to recycle bin).",
            )
        else:
            return await self.safe_execute(
                self.file_mgr.delete_item,
                path,
                confirmation_category="delete",
                confirmation_action=path,
                confirmed=confirmed,
                success_msg=f"File {path} deleted (moved to recycle bin).",
            )

    @llm.function_tool(
        description="Move a file or folder from src to dest path. Requires user confirmation."
    )
    async def move_item(self, src: str, dest: str, confirmed: bool = False) -> str:
        return await self._transfer_item(src, dest, "move", confirmed=confirmed)

    @llm.function_tool(description="Copy a file or folder from src to dest path")
    async def copy_item(self, src: str, dest: str) -> str:
        return await self._transfer_item(src, dest, "copy")

    @llm.function_tool(description="Rename a file or folder. Requires user confirmation.")
    async def rename_item(self, src: str, new_name: str, confirmed: bool = False) -> str:
        root_err = self._enforce_mcp_root(src)
        if root_err: return root_err
        
        confirm_res = await self.safe_execute(
            asyncio.sleep,
            0,
            confirmation_category="rename",
            confirmation_action=f"rename '{src}' to '{new_name}'",
            confirmed=confirmed,
        )
        if isinstance(confirm_res, str) and "SECURITY WARNING" in confirm_res:
            return confirm_res

        if os.path.isdir(src):
            return await self.safe_execute(
                self.folder_mgr.rename_folder,
                src,
                new_name,
                success_msg=f"Folder renamed from {src} to {new_name}.",
            )
        else:
            return await self.safe_execute(
                self.file_mgr.rename_item,
                src,
                new_name,
                success_msg=f"File renamed from {src} to {new_name}.",
            )

    @llm.function_tool(description="Open a file or folder natively in the OS")
    async def open_item(self, path: str) -> str:
        return await self.safe_execute(self.file_mgr.open_item, path, success_msg=f"Opened {path}.")

    @llm.function_tool(description="Get size, creation date, and metadata about a file")
    async def get_file_info(self, path: str) -> str:
        info = await self.safe_execute(self.file_mgr.get_file_info, path)
        if str(info).startswith("Error:"):
            return str(info)
        return f"File Info: {info}" if info else f"Failed to get info for {path}."

    @llm.function_tool(description="List the contents of a directory")
    async def list_directory(self, path: str) -> str:
        items = await self.safe_execute(self.folder_mgr.list_directory, path)
        if str(items).startswith("Error:"):
            return str(items)
        return f"Directory contains {len(items)} items: {', '.join(items[:20])}" + (
            "..." if len(items) > 20 else ""
        )

    @llm.function_tool(description="Close an open folder window or file window")
    async def close_item(self, path: str) -> str:
        if os.path.isdir(path):
            return await self.safe_execute(
                self.folder_mgr.close_folder,
                path,
                success_msg=f"Attempted to close folder window {path}.",
            )
        else:
            return await self.safe_execute(
                self.file_mgr.close_item,
                path,
                success_msg=f"Attempted to close file window {path}.",
            )
