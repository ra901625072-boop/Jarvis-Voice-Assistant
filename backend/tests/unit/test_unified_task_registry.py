"""
tests/unit/test_unified_task_registry.py — Unit tests for UnifiedTaskRegistry.

Phase 5: Tests for task creation, status tracking, cancellation,
and handler registration.
"""
import sys
import os
import time
import threading
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Reset singleton before each test to avoid cross-test contamination
@pytest.fixture(autouse=True)
def reset_singleton():
    from modules.execution import unified_task_registry
    unified_task_registry.UnifiedTaskRegistry._instance = None
    yield
    unified_task_registry.UnifiedTaskRegistry._instance = None


@pytest.fixture
def registry(tmp_path):
    from modules.execution.unified_task_registry import UnifiedTaskRegistry
    return UnifiedTaskRegistry(db_path=str(tmp_path / "test_tasks.db"), num_workers=2)


class TestUnifiedTaskRegistry:
    def test_creates_task_with_id(self, registry):
        task_id = registry.create_task("test_type", description="test task")
        assert task_id.startswith("task_")

    def test_get_task_returns_record(self, registry):
        task_id = registry.create_task("test_type", description="test task")
        rec = registry.get_task(task_id)
        assert rec is not None
        assert rec.task_id == task_id
        assert rec.task_type == "test_type"

    def test_thread_task_completes(self, registry):
        completed = threading.Event()

        def handler(task_id, rec):
            time.sleep(0.05)
            completed.set()
            return "done"

        task_id = registry.create_task("complete_test", handler=handler)
        assert completed.wait(timeout=3.0), "Task did not complete in time"

        rec = registry.get_task(task_id)
        assert rec.status.value == "completed"
        assert rec.result == "done"

    def test_thread_task_failure_recorded(self, registry):
        def bad_handler(task_id, rec):
            raise ValueError("Intentional error")

        task_id = registry.create_task("fail_test", handler=bad_handler)
        time.sleep(0.5)  # let worker process it

        rec = registry.get_task(task_id)
        assert rec.status.value == "failed"
        assert "Intentional error" in (rec.error or "")

    def test_cancel_queued_task(self, registry):
        # Block workers so task stays queued
        blocker = threading.Event()

        def slow_handler(task_id, rec):
            blocker.wait(timeout=5.0)

        # Fill worker queues
        registry.create_task("slow_task", handler=slow_handler)
        registry.create_task("slow_task", handler=slow_handler)

        # Third task should be cancellable
        task_id = registry.create_task("slow_task", handler=slow_handler)
        cancelled = registry.cancel_task(task_id)
        blocker.set()  # unblock workers

        assert cancelled is True
        rec = registry.get_task(task_id)
        assert rec.status.value == "cancelled"

    def test_list_tasks_returns_recent(self, registry):
        for i in range(5):
            registry.create_task("list_test", description=f"task {i}")

        time.sleep(0.2)
        tasks = registry.list_tasks(limit=3)
        assert len(tasks) <= 3

    def test_update_status(self, registry):
        from modules.execution.unified_task_registry import TaskStatus

        task_id = registry.create_task("update_test")
        registry.update_status(task_id, progress=42, result="partial")

        rec = registry.get_task(task_id)
        assert rec.progress == 42
        assert rec.result == "partial"

    def test_shutdown_stops_workers(self, registry):
        registry.shutdown()
        # After shutdown, _running should be False
        assert registry._running is False
