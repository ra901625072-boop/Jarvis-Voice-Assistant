"""
tests/conftest.py — Global hermetic pytest fixtures for JARVIS test suite.
"""
import os
import sys
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

def pytest_pyfunc_call(pyfuncitem):
    """Executes coroutine test functions synchronously using asyncio.run."""
    testfunction = pyfuncitem.obj
    if asyncio.iscoroutinefunction(testfunction):
        args = {arg: pyfuncitem.funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames if arg in pyfuncitem.funcargs}
        asyncio.run(testfunction(**args))
        return True

# Ensure backend root is on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Deterministic testing environment variables
os.environ["TESTING"] = "true"
os.environ["JARVIS_AUTO_CONFIRM"] = "false"
os.environ["JARVIS_API_KEY"] = "test_super_secret_api_key_for_testing_purposes"
os.environ["JARVIS_JWT_SECRET"] = "testing_environment_super_secret_jwt_key_32_bytes_long"
os.environ["JARVIS_ENABLE_TERMINAL"] = "false"


@pytest.fixture(autouse=True)
def reset_env_defaults(monkeypatch):
    """Ensure baseline environment configuration across all tests."""
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("JARVIS_AUTO_CONFIRM", "false")
    monkeypatch.setenv("JARVIS_API_KEY", "test_super_secret_api_key_for_testing_purposes")
    monkeypatch.setenv("JARVIS_JWT_SECRET", "testing_environment_super_secret_jwt_key_32_bytes_long")


@pytest.fixture
def workspace_dir(tmp_path):
    """Isolated temporary workspace root for filesystem sandboxing."""
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


@pytest.fixture
def security_manager(workspace_dir):
    """Hermetic SecurityManager bound strictly to an isolated temporary workspace."""
    from modules.security.manager import SecurityManager
    sec = SecurityManager(settings={"auto_confirm": False})
    sec.workspace_root = workspace_dir.resolve()
    return sec


@pytest.fixture
def memory_manager(tmp_path):
    """
    Hermetic MemoryManager backed by isolated SQLite database.
    ChromaDB disabled during tests to avoid external vector service dependency.
    """
    with patch.dict(os.environ, {"CHROMA_DISABLED": "true"}):
        with patch("modules.memory.manager._CHROMA_AVAILABLE", False):
            from modules.memory.manager import MemoryManager
            mm = MemoryManager(base_dir=str(tmp_path / "memory_db"))
            mm.initialize_minimal()
            yield mm


@pytest.fixture
def task_registry(tmp_path):
    """Isolated UnifiedTaskRegistry backed by a temporary SQLite file."""
    from modules.execution.unified_task_registry import UnifiedTaskRegistry
    db_path = str(tmp_path / "tasks.db")
    registry = UnifiedTaskRegistry(db_path=db_path)
    yield registry
    try:
        registry.shutdown()
    except Exception:
        pass


@pytest.fixture
def mock_room():
    """Mock LiveKit RTC room for toolset execution."""
    room = MagicMock()
    room.local_participant.publish_data = MagicMock(return_value=None)
    room.isconnected.return_value = True
    return room


@pytest.fixture
def api_client(security_manager, task_registry, workspace_dir):
    """FastAPI TestClient with initialized test dependencies."""
    from fastapi.testclient import TestClient
    from api.app import create_fastapi_app, token_rate_cache, token_rate_cache_lock
    
    try:
        with token_rate_cache_lock:
            token_rate_cache.clear()
    except Exception:
        pass
    
    app = create_fastapi_app()
    client = TestClient(app)
    yield client

    # Clean up test upload files generated during API tests
    uploads_dir = Path("apps/backend/uploads") if Path("apps/backend/uploads").exists() else Path("uploads")
    if uploads_dir.exists():
        for f in uploads_dir.iterdir():
            if f.is_file() and not f.name.endswith(".gitkeep"):
                try:
                    f.unlink()
                except Exception:
                    pass


@pytest.fixture
def auth_headers(security_manager):
    """Pre-generated valid JWT authorization headers for API testing."""
    token = security_manager.create_jwt(user_id="test_admin", role="admin")
    return {"Authorization": f"Bearer {token}"}
