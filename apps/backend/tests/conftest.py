"""
tests/conftest.py — Shared pytest fixtures for all JARVIS test modules.

All fixtures that need the live database or real OS services should be
implemented here so individual test files stay focused on assertions.
"""
import os
import sys
import tempfile
import threading
from unittest.mock import MagicMock, patch

import pytest

# ── Make sure backend/ is on sys.path so imports work ───────────────────────
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


# ── SecurityManager fixture ───────────────────────────────────────────────────

@pytest.fixture
def security_manager():
    """A real SecurityManager with default policy matrix."""
    from modules.core.security_manager import SecurityManager
    return SecurityManager()


# ── MemoryManager fixture (in-memory SQLite, no ChromaDB) ────────────────────

@pytest.fixture
def memory_db_path(tmp_path):
    """Temporary directory for memory databases."""
    return str(tmp_path)


@pytest.fixture
def memory_manager(memory_db_path):
    """
    A MemoryManager backed by temporary SQLite databases.
    ChromaDB is patched out to avoid requiring the external service.
    """
    with patch.dict(os.environ, {"CHROMA_DISABLED": "true"}):
        with patch("modules.core.memory_manager._CHROMA_AVAILABLE", False):
            from modules.core.memory_manager import MemoryManager
            mm = MemoryManager(db_dir=memory_db_path)
            mm.initialize_minimal()
            yield mm


# ── UnifiedTaskRegistry fixture ───────────────────────────────────────────────

@pytest.fixture
def task_registry(tmp_path):
    """
    A UnifiedTaskRegistry backed by a temporary SQLite database.
    Returned registry has its background workers started.
    """
    from modules.execution.unified_task_registry import UnifiedTaskRegistry
    db_path = str(tmp_path / "tasks.db")
    registry = UnifiedTaskRegistry(db_path=db_path)
    yield registry
    # Cleanup: cancel all pending tasks
    try:
        registry.shutdown()
    except Exception:
        pass


# ── Mock room fixture ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_room():
    """A lightweight mock of a LiveKit room for toolset tests."""
    room = MagicMock()
    room.local_participant.publish_data = MagicMock(return_value=None)
    room.isconnected.return_value = True
    return room


# ── FileManager fixture ───────────────────────────────────────────────────────

@pytest.fixture
def temp_dir(tmp_path):
    """A real temporary directory for filesystem operation tests."""
    return tmp_path
