import os
import tempfile
import shutil
import pytest
from unittest.mock import patch
import sys

# Adjust sys.path to run tests from backend folder root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.filesystem.file_manager import FileManager

def test_file_manager_move_with_recycle_bin_safety():
    # Use temporary folder
    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = os.path.join(tmpdir, "src.txt")
        dest_path = os.path.join(tmpdir, "dest.txt")
        
        # Write initial files
        with open(src_path, "w", encoding="utf-8") as f:
            f.write("source content")
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write("original destination content")
            
        # Instantiate FileManager using a temporary database
        db_path = os.path.join(tmpdir, "test_file_manager.db")
        fm = FileManager(db_path=db_path)
        
        # Patch send2trash to assert it is called on dest_path
        with patch("modules.filesystem.file_manager.send2trash") as mock_send2trash:
            # Execute move synchronous
            res = fm.move_item(src_path, dest_path, force_sync=True)
            
            assert res is True
            # Verify send2trash was called on the destination path before overwrite
            mock_send2trash.assert_called_once_with(os.path.normpath(dest_path))
            
            # Verify file was actually moved
            assert os.path.exists(dest_path)
            assert not os.path.exists(src_path)
            with open(dest_path, "r", encoding="utf-8") as f:
                assert f.read() == "source content"
                
        # Close connection so the temporary DB file isn't locked on exit
        if hasattr(fm._local, "conn"):
            fm._local.conn.close()

def test_file_manager_is_safe_path_blocklist():
    from modules.filesystem.fs_utils import is_safe_path
    
    # Verify standard blocklisted paths return False
    assert is_safe_path("C:\\Windows\\System32\\kernel32.dll") is False
    assert is_safe_path("C:\\Windows\\win.ini") is False
    
    # Verify workspace relative paths or custom drives are safe
    assert is_safe_path("D:\\Jarvis\\backend\\agent.py") is True
