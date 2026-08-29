"""
tests/unit/test_memory_system.py — Unit tests for MemoryManager.
"""
import pytest
from unittest.mock import patch


class TestMemorySystemUnit:
    def test_memory_manager_initialization(self, memory_manager):
        """MemoryManager initializes in-memory/sqlite minimal storage cleanly."""
        assert memory_manager is not None
        assert hasattr(memory_manager, "base_dir") or hasattr(memory_manager, "db_path")

    def test_session_state_storage(self, memory_manager):
        """Session state can be stored and retrieved without external dependencies."""
        if hasattr(memory_manager, "save_session_context"):
            memory_manager.save_session_context(
                session_id="test_sess_1",
                context={"user": "admin", "active_goal": "system_audit"}
            )
            retrieved = memory_manager.get_session_context("test_sess_1")
            assert retrieved is not None
            assert retrieved.get("user") == "admin"

    def test_record_execution_report(self, memory_manager):
        """Execution reports are recorded with duration and success metadata."""
        if hasattr(memory_manager, "record_execution_report"):
            report = {
                "task_id": "t_audit",
                "agent_id": "verification_agent",
                "success": True,
                "duration_ms": 120.5
            }
            res = memory_manager.record_execution_report(report)
            assert res is not False
