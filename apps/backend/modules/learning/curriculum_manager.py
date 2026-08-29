import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger("JARVIS.CurriculumManager")

class CurriculumManager:
    def __init__(self, memory_manager):
        self.mm = memory_manager
        self._dbs = memory_manager.dbs
        self._lock = memory_manager._lock

    def add_curriculum_item(self, agent_id: str, curriculum_type: str, prompt: str, expected_behavior: Optional[str] = None, evaluation_rule: Optional[str] = None) -> int:
        ts = datetime.now().isoformat()
        with self._lock:
            cursor = self._dbs["conversations"].execute(
                """INSERT INTO curriculum_items (agent_id, curriculum_type, prompt, expected_behavior, evaluation_rule, active, created_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (agent_id, curriculum_type, prompt, expected_behavior, evaluation_rule, ts)
            )
            self._dbs["conversations"].commit()
            return cursor.lastrowid

    def get_active_curriculum(self, agent_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT id, agent_id, curriculum_type, prompt, expected_behavior, evaluation_rule, active, created_at
                   FROM curriculum_items WHERE agent_id = ? AND active = 1""",
                (agent_id,)
            ).fetchall()
            return [{
                "id": r[0],
                "agent_id": r[1],
                "curriculum_type": r[2],
                "prompt": r[3],
                "expected_behavior": r[4],
                "evaluation_rule": r[5],
                "active": r[6],
                "created_at": r[7]
            } for r in rows]

    def deactivate_curriculum(self, item_id: int) -> None:
        with self._lock:
            self._dbs["conversations"].execute(
                "UPDATE curriculum_items SET active = 0 WHERE id = ?",
                (item_id,)
            )
            self._dbs["conversations"].commit()

    def list_curriculum(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if agent_id:
                rows = self._dbs["conversations"].execute(
                    """SELECT id, agent_id, curriculum_type, prompt, expected_behavior, evaluation_rule, active, created_at
                       FROM curriculum_items WHERE agent_id = ?""",
                    (agent_id,)
                ).fetchall()
            else:
                rows = self._dbs["conversations"].execute(
                    """SELECT id, agent_id, curriculum_type, prompt, expected_behavior, evaluation_rule, active, created_at
                       FROM curriculum_items"""
                ).fetchall()
            return [{
                "id": r[0],
                "agent_id": r[1],
                "curriculum_type": r[2],
                "prompt": r[3],
                "expected_behavior": r[4],
                "evaluation_rule": r[5],
                "active": r[6],
                "created_at": r[7]
            } for r in rows]
