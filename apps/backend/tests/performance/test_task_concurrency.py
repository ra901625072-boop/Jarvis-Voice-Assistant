"""
tests/performance/test_task_concurrency.py — Performance & concurrency tests for UnifiedTaskRegistry.
"""
import time
import pytest
from modules.execution.unified_task_registry import UnifiedTaskRegistry, TaskStatus


class TestTaskConcurrencyPerformance:
    def test_concurrent_task_creation_and_updates(self, tmp_path):
        """Registry handles rapid batch creation and status updates without SQLite lock errors."""
        db_path = str(tmp_path / "perf_tasks.db")
        UnifiedTaskRegistry._instance = None
        registry = UnifiedTaskRegistry(db_path=db_path)

        num_tasks = 40
        start = time.perf_counter()
        
        task_ids = []
        for i in range(num_tasks):
            t_id = registry.create_task(task_type="batch_job", description=f"Batch item #{i}")
            task_ids.append(t_id)

        for t_id in task_ids:
            registry.update_status(t_id, status=TaskStatus.RUNNING, progress=50)

        for t_id in task_ids:
            registry.update_status(t_id, status=TaskStatus.COMPLETED, progress=100, result="Done")

        total_time = time.perf_counter() - start
        
        all_records = registry.list_tasks(limit=100)
        batch_records = [r for r in all_records if r.task_id in task_ids]
        assert len(batch_records) == num_tasks
        assert all(r.status == TaskStatus.COMPLETED for r in batch_records)
        assert total_time < 30.0  # 40 tasks created and twice updated without locking failures

        registry.shutdown()
