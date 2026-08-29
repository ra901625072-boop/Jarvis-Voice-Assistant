"""
agent_capability_tracker.py
---------------------------
Updates agent capability scores based on their historical success rates.
"""

import logging
from datetime import datetime

logger = logging.getLogger("JARVIS.AgentCapabilityTracker")

class AgentCapabilityTracker:
    def __init__(self, memory_manager):
        self.mm = memory_manager
        self._dbs = memory_manager.dbs
        self._lock = memory_manager._lock

    def run_nightly(self) -> None:
        """Calculate and update rolling capability scores for all agents."""
        logger.info("AgentCapabilityTracker: calculating agent capabilities...")
        try:
            with self._lock:
                agent_tasks = self._dbs["conversations"].execute(
                    """SELECT DISTINCT agent_id, task_type FROM agent_task_outcomes
                       WHERE (goal_hint IS NULL OR (goal_hint NOT LIKE 'seed_%' AND goal_hint NOT LIKE 'e2e_sim_%'))"""
                ).fetchall()

            for agent_id, task_type in agent_tasks:
                self._update_capability(agent_id, task_type)

        except Exception as e:
            logger.error(f"AgentCapabilityTracker failed: {e}", exc_info=True)

    def _update_capability(self, agent_id: str, task_type: str) -> None:
        """Update capability score for a specific agent and task_type based on last 50 runs."""
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT success FROM agent_task_outcomes
                   WHERE agent_id = ? AND task_type = ?
                     AND (goal_hint IS NULL OR (goal_hint NOT LIKE 'seed_%' AND goal_hint NOT LIKE 'e2e_sim_%'))
                   ORDER BY created_at DESC LIMIT 50""",
                (agent_id, task_type)
            ).fetchall()

        if not rows:
            return

        total_runs = len(rows)
        successes = sum(r[0] for r in rows)
        success_rate = successes / total_runs
        
        # Calculate a weighted score. E.g. EMA could be used, or just success_rate if > 5 runs.
        # Let's use basic success rate for now.
        confidence = max(0.60, round(success_rate, 2))
        
        ts = datetime.now().isoformat()
        with self._lock:
            existing = self._dbs["conversations"].execute(
                "SELECT id FROM agent_capability_scores WHERE agent_id = ? AND task_type = ?",
                (agent_id, task_type)
            ).fetchone()
            
            if existing:
                self._dbs["conversations"].execute(
                    """UPDATE agent_capability_scores
                       SET success_rate = ?, total_runs = ?, confidence = ?, last_updated = ?
                       WHERE id = ?""",
                    (max(0.60, success_rate), total_runs, confidence, ts, existing[0])
                )
            else:
                self._dbs["conversations"].execute(
                    """INSERT INTO agent_capability_scores
                       (agent_id, task_type, success_rate, total_runs, confidence, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (agent_id, task_type, max(0.60, success_rate), total_runs, confidence, ts)
                )
            self._dbs["conversations"].commit()

            # Phase 5: Agent Self-Model update on threshold crossing
            if confidence >= 0.90:
                self._dbs["conversations"].execute(
                    """INSERT INTO agent_self_model (capability, category, confidence, notes, created_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(capability) DO UPDATE SET confidence=excluded.confidence, notes=excluded.notes, created_at=excluded.created_at""",
                    (f"{agent_id}:{task_type}", agent_id, confidence, "High historical success rate (>90%)", ts)
                )
                self._dbs["conversations"].commit()
            elif confidence <= 0.60:
                self._dbs["conversations"].execute(
                    """INSERT INTO agent_self_model (capability, category, confidence, notes, created_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(capability) DO UPDATE SET confidence=excluded.confidence, notes=excluded.notes, created_at=excluded.created_at""",
                    (f"{agent_id}:{task_type}", agent_id, confidence, "Clamped to minimum confidence (60%)", ts)
                )
                self._dbs["conversations"].commit()
