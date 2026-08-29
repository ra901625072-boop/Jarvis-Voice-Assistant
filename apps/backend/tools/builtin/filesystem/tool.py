"""
toolsets/file_tools.py — FileTools toolset.

Phase 5.6: _transfer_item() helper de-duplicates move/copy logic.
Phase 2.1: All path-safety checks route through SecurityManager.is_safe_path().
"""
import asyncio
import os
from livekit.agents import llm
from tools.builtin.base import JarvisToolset
from modules.security.manager import SecurityManager


# ── Module-level singletons (lazy-init on first access) ─────────────────────
_global_file_mgr = None
_global_folder_mgr = None


def _get_file_mgr():
    from container import ServiceContainer
    container = ServiceContainer.instance()
    if container:
        try:
            return container.get("file_manager")
        except KeyError:
            pass
    global _global_file_mgr
    if _global_file_mgr is None:
        from modules.filesystem.file_manager import FileManager
        _global_file_mgr = FileManager()
    return _global_file_mgr


def _get_folder_mgr():
    from container import ServiceContainer
    container = ServiceContainer.instance()
    if container:
        try:
            return container.get("folder_manager")
        except KeyError:
            pass
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
        self._file_mgr = _get_file_mgr()
        self._folder_mgr = _get_folder_mgr()


    def _enforce_mcp_root(self, *paths) -> str:
        if self.security:
            for p in paths:
                if p and not self.security.is_safe_path(p):
                    return f"Error: Security Policy blocks operating on restricted system folder/file: '{p}'"
        if self.security and getattr(self.security, "workspace_root", None):
            fs_root = str(self.security.workspace_root)
        else:
            fs_root = os.environ.get("JARVIS_MCP_FS_ROOT") or os.environ.get("JARVIS_RESTRICT_FS_ROOT")
        if not fs_root:
            return ""
        import sys
        fs_root = os.path.normpath(os.path.abspath(fs_root))
        is_windows = sys.platform.startswith('win')
        if is_windows:
            fs_root_lower = fs_root.lower()
        for p in paths:
            if p:
                abs_p = os.path.normpath(os.path.abspath(p))
                if is_windows:
                    if not abs_p.lower().startswith(fs_root_lower):
                        return f"Error: Path '{p}' is outside the allowed root directory '{fs_root}'."
                else:
                    if not abs_p.startswith(fs_root):
                        return f"Error: Path '{p}' is outside the allowed root directory '{fs_root}'."
        return ""


    @property
    def file_mgr(self):
        return self._file_mgr

    @property
    def folder_mgr(self):
        return self._folder_mgr

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
            # Security path check
            root_err = self._enforce_mcp_root(src, dest)
            if root_err:
                return root_err
                
            if self.security:
                if not self.security.is_safe_path(src) or not self.security.is_safe_path(dest):
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

            is_dir = os.path.isdir(src)
            src_drive = os.path.splitdrive(src)[0].lower()
            dest_drive = os.path.splitdrive(dest)[0].lower()
            is_cross_drive = src_drive != dest_drive

            # Check if large file (> 50MB)
            large_file = False
            try:
                if not is_dir and os.path.exists(src):
                    large_file = os.path.getsize(src) > 50 * 1024 * 1024
            except Exception:
                pass

            # Automatically run in background if copying a folder, a large file, or across drives
            use_background = is_dir or large_file or is_cross_drive

            if use_background:
                from modules.planning.task_manager import BackgroundTaskManager

                bg_mgr = BackgroundTaskManager()

                def _handle_op(context, s, d):
                    context.update_progress(10)
                    if is_dir:
                        res = (self.folder_mgr.move_folder(s, d) if operation == "move" else self.folder_mgr.copy_folder(s, d))
                    else:
                        res = (self.file_mgr.move_item(s, d, force_sync=True) if operation == "move" else self.file_mgr.copy_item(s, d))
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
                task_id = bg_mgr.add_task(
                    task_type,
                    args=(src, dest),
                    label=f"Moving {src} to {dest}" if operation == "move" else f"Copying {src} to {dest}",
                    announce=True,
                    priority="normal"
                )
                return (
                    f"The {operation} of '{'folder' if is_dir else 'file'}' '{src}' to '{dest}' "
                    f"has started in the background (Task ID: {task_id}). "
                    "You can check its status using get_background_task_status."
                )
            else:
                if is_dir:
                    if operation == "move":
                        result = await self.safe_execute(self.folder_mgr.move_folder, src, dest)
                    else:
                        return await self.safe_execute(
                            self.folder_mgr.copy_folder,
                            src,
                            dest,
                            success_msg=f"Folder {'moved' if operation == 'move' else 'copied'} from {src} to {dest}.",
                        )
                else:
                    if operation == "move":
                        result = await self.safe_execute(self.file_mgr.move_item, src, dest)
                    else:
                        return await self.safe_execute(
                            self.file_mgr.copy_item,
                            src,
                            dest,
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
        description="Find and open a file by a natural language description (e.g., 'the marketing presentation from yesterday')."
    )
    async def find_and_open_file(self, query: str, app_name: str = None) -> str:
        from container import ServiceContainer
        container = ServiceContainer.instance()
        if container:
            try:
                agent = container.get("file_discovery_agent")
                return await agent.find_and_open_file(query, app_name)
            except KeyError:
                pass
        from modules.skills.file_discovery_agent import FileDiscoveryAgent
        from modules.filesystem.semantic_engine import SemanticEngine
        import os
        db_dir = os.path.dirname(self.file_mgr.db_path)
        se = SemanticEngine(db_dir)
        agent = FileDiscoveryAgent(self.file_mgr, self.file_mgr.learning_engine, se)
        return await agent.find_and_open_file(query, app_name)


    @llm.function_tool(description="Search for a file or folder recursively. Scans all drives by default if no location is specified.")
    async def search_local_file(self, filename: str, root_dir: str = None) -> str:
        if root_dir:
            root_err = self._enforce_mcp_root(root_dir)
            if root_err:
                return root_err
        results = await self.safe_execute(self.file_mgr.search_file, filename, root_dir)

        if str(results).startswith("Error:"):
            return str(results)
        if not results:
            return f"No file or folder results found for {filename}."
        return f"Found {len(results)} results: {', '.join(results[:5])}" + (
            "..." if len(results) > 5 else ""
        )

    @llm.function_tool(description="Create a new folder at the specified path. If the user does not specify a location, create it inside 'd:/Jarvis/storeroom'.")
    async def create_folder(self, path: str) -> str:
        root_err = self._enforce_mcp_root(path)
        if root_err:
            return root_err
        return await self.safe_execute(
            self.folder_mgr.create_folder, path, success_msg=f"Folder {path} created."
        )

    @llm.function_tool(description="Create a new file with optional content at the specified path. If the user does not specify a location, save it inside 'd:/Jarvis/storeroom'.")
    async def create_file(self, path: str, content: str = "") -> str:
        root_err = self._enforce_mcp_root(path)
        if root_err:
            return root_err
        return await self.safe_execute(
            self.file_mgr.create_file,
            path,
            content,
            success_msg=f"File {path} created.",
            error_msg=f"Failed to create file {path}.",
        )

    @llm.function_tool(description="Read the contents of a text or document file (PDF, DOCX, XLSX, image, or text file)")
    async def read_local_file(self, path: str) -> str:
        root_err = self._enforce_mcp_root(path)
        if root_err:
            return root_err
        ext = os.path.splitext(path)[1].lower()
        if ext in (".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".pptx", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm"):
            async def _do_extract():
                from modules.filesystem.document_extractor import DocumentExtractor
                extractor = DocumentExtractor()
                res = extractor.extract(path)
                if not res.success:
                    return f"Error extracting document contents: {res.error}"
                
                output = f"Document type: {ext.upper()} | Extraction Method: {res.method}\n"
                if res.metadata:
                    meta_str = ", ".join(f"{k}: {v}" for k, v in res.metadata.items() if k not in ("page_texts", "sheet_texts", "pages"))
                    output += f"Metadata: {{{meta_str}}}\n"
                output += f"\n--- Content ---\n{res.text}"
                return output
                
            content = await self.safe_execute(_do_extract)
        else:
            content = await self.safe_execute(self.file_mgr.read_file, path)
            
        if str(content).startswith("Error:"):
            return str(content)
        if content is None:
            return f"Failed to read file {path}."
        return f"File contents:\n{content[:4000]}" + (
            "...\n[Content Truncated]" if len(content) > 4000 else ""
        )

    @llm.function_tool(description="Delete a file or folder at the specified path. Requires confirmation.")
    async def delete_item(self, path: str, confirmed: bool = False) -> str:
        root_err = self._enforce_mcp_root(path)
        if root_err:
            return root_err
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
        if root_err:
            return root_err
        
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

    @llm.function_tool(description="Open a file or folder natively in the OS. Can optionally specify an app_name to open it with a specific application (e.g. 'vlc', 'chrome', 'notepad').")
    async def open_item(self, path: str, app_name: str = None) -> str:
        root_err = self._enforce_mcp_root(path)
        if root_err:
            return root_err
        return await self.safe_execute(self.file_mgr.open_item, path, app_name, success_msg=f"Opened {path}.")

    @llm.function_tool(description="Get metadata info about a file")
    async def get_local_file_info(self, path: str) -> str:
        root_err = self._enforce_mcp_root(path)
        if root_err:
            return root_err
        info = await self.safe_execute(self.file_mgr.get_file_info, path)
        if str(info).startswith("Error:"):
            return str(info)
        return f"File Info: {info}" if info else f"Failed to get info for {path}."

    @llm.function_tool(description="List all files and subdirectories in a specific path")
    async def list_local_directory(self, path: str) -> str:
        root_err = self._enforce_mcp_root(path)
        if root_err:
            return root_err
        items = await self.safe_execute(self.folder_mgr.list_directory, path)
        if str(items).startswith("Error:"):
            return str(items)
        if not items:
            # Check for sister folder matching stem (e.g. 'test folder' vs 'test')
            try:
                norm_p = os.path.normpath(os.path.abspath(path))
                parent = os.path.dirname(norm_p)
                base = os.path.basename(norm_p).lower().replace(" folder", "").replace(" directory", "").strip()
                suggestions = []
                if parent and os.path.isdir(parent) and base:
                    for entry in os.listdir(parent):
                        full_p = os.path.join(parent, entry)
                        if os.path.isdir(full_p) and base in entry.lower() and full_p.lower() != norm_p.lower():
                            sub_items = os.listdir(full_p)
                            if sub_items:
                                suggestions.append(f"{full_p} ({len(sub_items)} items: {', '.join(sub_items[:8])})")
                if suggestions:
                    return f"Directory '{path}' is empty. Found related folder with contents:\n" + "\n".join(suggestions)
            except Exception:
                pass
            return f"Directory '{path}' is empty (contains 0 items)."
        return f"Directory contains {len(items)} items: {', '.join(items[:25])}" + (
            "..." if len(items) > 25 else ""
        )

    @llm.function_tool(description="Close an open folder window or file window")
    async def close_item(self, path: str) -> str:
        root_err = self._enforce_mcp_root(path)
        if root_err:
            return root_err
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
