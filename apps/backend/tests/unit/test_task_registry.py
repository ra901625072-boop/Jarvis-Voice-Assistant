"""
tests/unit/test_task_registry.py — Unit tests for UnifiedTaskRegistry SQLite state machine.
"""
import pytest
from modules.execution.unified_task_registry import TaskStatus, TaskRecord


class TestTaskRegistryUnit:
    def test_create_and_get_task(self, task_registry):
        """Creating a task stores it in SQLite and assigns queued status."""
        task_id = task_registry.create_task(task_type="file_copy", description="Copying report.pdf")
        assert task_id is not None
        
        record = task_registry.get_task(task_id)
        assert record is not None
        assert record.task_id == task_id
        assert record.task_type == "file_copy"
        assert record.status == TaskStatus.QUEUED
        assert record.description == "Copying report.pdf"

    def test_update_status_lifecycle(self, task_registry):
        """Status updates progress through running to completed with results."""
        task_id = task_registry.create_task(task_type="data_sync", description="Syncing records")
        
        # Move to RUNNING
        task_registry.update_status(task_id, status=TaskStatus.RUNNING, progress=50)
        rec = task_registry.get_task(task_id)
        assert rec.status == TaskStatus.RUNNING
        assert rec.progress == 50

        # Move to COMPLETED
        task_registry.update_status(task_id, status=TaskStatus.COMPLETED, progress=100, result="Sync successful")
        rec = task_registry.get_task(task_id)
        assert rec.status == TaskStatus.COMPLETED
        assert rec.progress == 100
        assert rec.result == "Sync successful"

    def test_list_tasks(self, task_registry):
        """list_tasks retrieves recorded tasks."""
        t1 = task_registry.create_task(task_type="t1", description="First task")
        t2 = task_registry.create_task(task_type="t2", description="Second task")
        
        task_registry.update_status(t1, status=TaskStatus.COMPLETED)
        task_registry.update_status(t2, status=TaskStatus.FAILED, error="Timeout")

        all_tasks = task_registry.list_tasks(limit=10)
        assert len(all_tasks) >= 2
        task_ids = [t.task_id for t in all_tasks]
        assert t1 in task_ids
        assert t2 in task_ids

    def test_cancel_task(self, task_registry):
        """Cancelling a queued task transitions its state to CANCELLED."""
        task_id = task_registry.create_task(task_type="long_job", description="Batch processing")
        cancelled = task_registry.cancel_task(task_id)
        assert cancelled is True
        
        rec = task_registry.get_task(task_id)
        assert rec.status == TaskStatus.CANCELLED
