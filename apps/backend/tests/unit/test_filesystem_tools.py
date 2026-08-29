import os
import pytest
from tools.builtin.filesystem.tool import FileTools


class TestFilesystemToolsUnit:
    @pytest.mark.asyncio
    async def test_read_and_search_file_inside_workspace(self, security_manager, workspace_dir):
        """Reading and searching files within workspace root succeeds."""
        tool = FileTools(security=security_manager)
        test_file = workspace_dir / "document.txt"
        test_file.write_text("Hello, Jarvis!")
        
        # Read
        read_res = await tool.read_local_file(str(test_file))
        assert "Hello, Jarvis!" in read_res

    @pytest.mark.asyncio
    async def test_read_file_outside_workspace_blocked(self, security_manager):
        """Reading files outside workspace root must be blocked by security policy."""
        tool = FileTools(security=security_manager)
        res = await tool.read_local_file("C:\\Windows\\System32\\drivers\\etc\\hosts")
        assert "Error" in res or "Security" in res or "blocked" in res.lower()

    @pytest.mark.asyncio
    async def test_list_directory_outside_workspace_blocked(self, security_manager):
        """Listing directories outside workspace root must be blocked."""
        tool = FileTools(security=security_manager)
        res = await tool.list_local_directory("C:\\Windows")
        assert "Error" in res or "Security" in res or "blocked" in res.lower()

    @pytest.mark.asyncio
    async def test_delete_file_inside_workspace(self, security_manager, workspace_dir):
        """Deleting a file inside workspace with confirmation succeeds."""
        tool = FileTools(security=security_manager)
        test_file = workspace_dir / "to_delete.txt"
        test_file.write_text("delete me")
        
        del_res = await tool.delete_item(str(test_file), confirmed=True)
        assert not test_file.exists()
