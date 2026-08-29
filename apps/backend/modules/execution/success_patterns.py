import logging
import json
from datetime import datetime
from typing import List, Any, Optional

logger = logging.getLogger("JARVIS.SuccessLearning")

class SuccessLearner:
    """
    SuccessLearner tracks successfully executed plans to promote high-performing workflows.

    SYSTEM PROMPT:
    Query SuccessLearner to fetch previously proven, high-scoring step sequences for similar user goals.

    SHORT DESCRIPTION:
    Analyzes and saves successful task sequences as reusable workflow pattern templates.

    PROCESS:
    1. Filter out plans with fewer than 2 subtasks to avoid registering trivial steps.
    2. Serializes successfully executed task descriptions into JSON formatting.
    3. Commits to the local database, incrementing usage counters and confidence scores for duplicate goals.
    4. Searches matching templates using partial text matches and returns sorted, high-score workflows.

    FLOW:
    Caller -> learn_from_success()/get_preferred_workflow() -> MemoryManager DB connections -> success_patterns SQLite table -> Caller
    """
    def __init__(self, memory_manager):
        self.mm = memory_manager
        self._dbs = getattr(memory_manager, 'dbs', {})
        self._lock = getattr(memory_manager, '_lock', None)

    def learn_from_success(self, goal: str, plan_subtasks: List[Any]):
        """
        Record a successful plan for a goal.
        """
        import os
        if os.environ.get("JARVIS_E2E_SIM") == "1":
            return
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
                        # Clamp score to max 5.0 to prevent unbounded growth
                        "UPDATE success_patterns SET use_count=?, score=MIN(score+0.1, 5.0) WHERE id=?",
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
                # Escape LIKE wildcards to prevent unintended SQL pattern matches
                safe_goal = goal.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                row = self._dbs["conversations"].execute(
                    """SELECT plan_json, score FROM success_patterns 
                       WHERE goal LIKE ? ESCAPE '\\'
                       ORDER BY score DESC LIMIT 1""",
                    (f"%{safe_goal}%",)
                ).fetchone()
                
            if row:
                plan_json, score = row
                tasks = json.loads(plan_json)
                workflow = "\n".join([f"  {i+1}. {t}" for i, t in enumerate(tasks)])
                return f"--- PREFERRED SUCCESSFUL WORKFLOW (Score: {score:.1f}) ---\n{workflow}"
        except Exception as e:
            logger.debug(f"Failed to get preferred workflow: {e}")
        return None

    def record_failure(self, goal: str):
        """Record a failure for a goal pattern, decrementing its score."""
        import os
        if os.environ.get("JARVIS_E2E_SIM") == "1":
            return
        if not self._lock or "conversations" not in self._dbs:
            return
        try:
            with self._lock:
                self._dbs["conversations"].execute(
                    "UPDATE success_patterns SET score=MAX(score-0.2, 0.0) WHERE goal=?",
                    (goal,)
                )
                self._dbs["conversations"].commit()
        except Exception as e:
            logger.debug(f"Failed to record failure pattern: {e}")

    def decay_old_patterns(self):
        """Decay scores of old patterns periodically."""
        if not self._lock or "conversations" not in self._dbs:
            return
        try:
            with self._lock:
                # Decay patterns that haven't been used recently or have very low score
                self._dbs["conversations"].execute(
                    "UPDATE success_patterns SET score=MAX(score-0.05, 0.0)"
                )
                self._dbs["conversations"].execute(
                    "DELETE FROM success_patterns WHERE score=0.0 AND use_count < 2"
                )
                self._dbs["conversations"].commit()
            logger.info("Decayed old success patterns.")
        except Exception as e:
            logger.debug(f"Failed to decay success patterns: {e}")
