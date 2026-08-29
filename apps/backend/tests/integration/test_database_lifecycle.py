"""
tests/integration/test_database_lifecycle.py — Integration tests for SQLite task persistence across instances.
"""
import pytest
from modules.execution.unified_task_registry import UnifiedTaskRegistry, TaskStatus


class TestDatabaseLifecycleIntegration:
    def test_task_state_persists_across_registry_restarts(self, tmp_path):
        """Tasks created in one registry instance are readable and updatable in a new instance."""
        db_file = str(tmp_path / "lifecycle_tasks.db")
        
        # Instance 1: Create and start task
        reg1 = UnifiedTaskRegistry(db_path=db_file)
        task_id = reg1.create_task(task_type="build_project", description="Compiling release build")
        reg1.update_status(task_id, status=TaskStatus.RUNNING, progress=40)
        reg1.shutdown()

        # Instance 2: Connect to existing database and verify state
        reg2 = UnifiedTaskRegistry(db_path=db_file)
        rec = reg2.get_task(task_id)
        assert rec is not None
        assert rec.task_id == task_id
        assert rec.status == TaskStatus.RUNNING
        assert rec.progress == 40

        # Complete task in Instance 2
        reg2.update_status(task_id, status=TaskStatus.COMPLETED, progress=100, result="Build succeeded")
        reg2.shutdown()

        # Instance 3: Verify completion state
        reg3 = UnifiedTaskRegistry(db_path=db_file)
        final_rec = reg3.get_task(task_id)
        assert final_rec.status == TaskStatus.COMPLETED
        assert final_rec.result == "Build succeeded"
        reg3.shutdown()
