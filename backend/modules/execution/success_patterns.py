import logging
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger("JARVIS.SuccessLearning")

class SuccessLearner:
    """
    Extracts successful plans and promotes them as preferred workflows.
    """
    def __init__(self, memory_manager):
        self.mm = memory_manager
        self._dbs = getattr(memory_manager, 'dbs', {})
        self._lock = getattr(memory_manager, '_lock', None)

    def learn_from_success(self, goal: str, plan_subtasks: List[Any]):
        """
        Record a successful plan for a goal.
        """
        if not self._lock or "conversations" not in self._dbs:
            return

        if len(plan_subtasks) < 2:
            return  # Too simple to be a reusable pattern

        # Handle SubTask objects or dicts
        try:
            tasks_str = [t.description if hasattr(t, 'description') else t.get('description', '') for t in plan_subtasks]
            plan_json = json.dumps(tasks_str)
        except Exception:
            return

        ts = datetime.now().isoformat()
        
        try:
            with self._lock:
                existing = self._dbs["conversations"].execute(
                    "SELECT id, use_count FROM success_patterns WHERE goal=?",
                    (goal,)
                ).fetchone()

                if existing:
                    row_id, count = existing
                    self._dbs["conversations"].execute(
                        "UPDATE success_patterns SET use_count=?, score=score+0.1 WHERE id=?",
                        (count + 1, row_id)
                    )
                else:
                    self._dbs["conversations"].execute(
                        """INSERT INTO success_patterns (goal, plan_json, score, use_count, created_at)
                           VALUES (?, ?, 1.0, 1, ?)""",
                        (goal, plan_json, ts)
                    )
                self._dbs["conversations"].commit()
            logger.info(f"Learned success pattern for goal: '{goal}'")
        except Exception as e:
            logger.debug(f"Failed to learn success pattern: {e}")

    def get_preferred_workflow(self, goal: str) -> Optional[str]:
        """
        Returns a formatted string of the preferred workflow for a goal, if any exists.
        """
        if not self._lock or "conversations" not in self._dbs:
            return None

        try:
            with self._lock:
                # Simple exact or LIKE match
                row = self._dbs["conversations"].execute(
                    """SELECT plan_json, score FROM success_patterns 
                       WHERE goal LIKE ? 
                       ORDER BY score DESC LIMIT 1""",
                    (f"%{goal}%",)
                ).fetchone()
                
            if row:
                plan_json, score = row
                tasks = json.loads(plan_json)
                workflow = "\n".join([f"  {i+1}. {t}" for i, t in enumerate(tasks)])
                return f"--- PREFERRED SUCCESSFUL WORKFLOW (Score: {score:.1f}) ---\n{workflow}"
        except Exception as e:
            logger.debug(f"Failed to get preferred workflow: {e}")
        return None
