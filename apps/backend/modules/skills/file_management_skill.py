import os
import shutil
import hashlib
from collections import defaultdict
from livekit.agents import llm
from modules.skills.base_skill import BaseSkill

class FileManagementSkill(BaseSkill):
    """
    Skill for high-level file operations beyond the basic FileTools.
    """
    def __init__(self, memory=None, security=None, room=None, verification=None, **kwargs):
        super().__init__(memory=memory, security=security, room=room, verification=verification)

    @llm.function_tool(description="Organize files in a folder into subfolders by their file extension")
    async def organize_folder_by_type(self, folder_path: str, confirmed: bool = False) -> str:
        """Organize a folder by moving files into extension-based subfolders."""
        from modules.security.manager import SecurityManager
        sec = self.security if self.security else SecurityManager()
        if not sec.is_safe_path(folder_path):
            return "Error: Security Policy blocks modification of protected system path."
            
        async def _do_organize():
            if not os.path.exists(folder_path):
                return f"Error: Folder {folder_path} does not exist."
            
            moved_count = 0
            for item in os.listdir(folder_path):
                item_path = os.path.join(folder_path, item)
                if os.path.isfile(item_path):
                    _, ext = os.path.splitext(item)
                    ext = ext.lstrip('.').lower() or 'no_extension'
                    dest_dir = os.path.join(folder_path, ext)
                    os.makedirs(dest_dir, exist_ok=True)
                    
                    dest_path = os.path.join(dest_dir, item)
                    # Don't overwrite existing files with the same name
                    if not os.path.exists(dest_path):
                        shutil.move(item_path, dest_path)
                        moved_count += 1

            return f"Successfully organized {moved_count} files into type-based subfolders."

        return await self.safe_execute(
            _do_organize,
            confirmation_category="move",
            confirmation_action=f"organize folder {folder_path} by type",
            confirmed=confirmed,
            success_msg="Organized folder successfully",
            error_msg="Failed to organize folder"
        )

    @llm.function_tool(description="Batch rename files in a folder based on a pattern (e.g., 'photo_{i}.jpg')")
    async def batch_rename(self, folder_path: str, pattern: str, confirmed: bool = False) -> str:
        """Rename all files in a folder according to a pattern containing '{i}'."""
        from modules.security.manager import SecurityManager
        sec = self.security if self.security else SecurityManager()
        if not sec.is_safe_path(folder_path):
            return "Error: Security Policy blocks modification of protected system path."
            
        async def _do_rename():
            if not os.path.exists(folder_path):
                return f"Error: Folder {folder_path} does not exist."
            if "{i}" not in pattern:
                return "Error: Pattern must contain '{i}' for the index."
            
            files = sorted([f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))])
            renamed_count = 0
            
            for i, filename in enumerate(files, start=1):
                old_path = os.path.join(folder_path, filename)
                new_filename = pattern.replace("{i}", str(i))
                
                # Keep original extension if the pattern doesn't specify one
                if "." not in new_filename and "." in filename:
                    _, ext = os.path.splitext(filename)
                    new_filename += ext
                    
                new_path = os.path.join(folder_path, new_filename)
                
                if not os.path.exists(new_path):
                    os.rename(old_path, new_path)
                    renamed_count += 1
            
            return f"Successfully renamed {renamed_count} files."

        return await self.safe_execute(
            _do_rename,
            confirmation_category="rename",
            confirmation_action=f"batch rename files in {folder_path} to {pattern}",
            confirmed=confirmed,
            success_msg="Batch renamed files successfully",
            error_msg="Failed to batch rename files"
        )

    @llm.function_tool(description="Find duplicate files in a folder based on content hashes")
    async def find_duplicates(self, folder_path: str) -> str:
        """Find duplicate files in a folder."""
        from modules.security.manager import SecurityManager
        sec = self.security if self.security else SecurityManager()
        if not sec.is_safe_path(folder_path):
            return "Error: Security Policy blocks modification of protected system path."
            
        async def _do_find():
            if not os.path.exists(folder_path):
                return f"Error: Folder {folder_path} does not exist."
            
            hashes = defaultdict(list)
            
            for root, _, files in os.walk(folder_path):
                for filename in files:
                    filepath = os.path.join(root, filename)
                    try:
                        with open(filepath, "rb") as f:
                            file_hash = hashlib.md5(f.read()).hexdigest()
                            hashes[file_hash].append(filepath)
                    except Exception as e:
                        self.logger.warning(f"Could not hash {filepath}: {e}")
                        
            duplicates = {h: paths for h, paths in hashes.items() if len(paths) > 1}
            
            if not duplicates:
                return "No duplicate files found."
                
            report = "Found the following duplicate files:\n"
            for h, paths in duplicates.items():
                report += f"\nHash {h}:\n"
                for path in paths:
                    report += f"  - {path}\n"
                    
            return report

        return await self.safe_execute(
            _do_find,
            confirmation_category="read",
            confirmation_action=f"find duplicates in {folder_path}",
            confirmed=True,
            success_msg="Found duplicates successfully",
            error_msg="Failed to find duplicates"
        )


