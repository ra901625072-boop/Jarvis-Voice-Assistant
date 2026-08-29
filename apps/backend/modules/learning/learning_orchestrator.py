import logging
import json
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger("JARVIS.LearningOrchestrator")

class LearningOrchestrator:
    def __init__(self, memory_manager):
        self.mm = memory_manager
        self._dbs = memory_manager.dbs
        self._lock = memory_manager._lock

    def log_event(self, agent_id: str, task_type: str, event_type: str, severity: str, pattern_key: Optional[str], summary: str) -> int:
        ts = datetime.now().isoformat()
        key_str = f"{agent_id}:{task_type}:{event_type}:{pattern_key or ''}:{summary}"
        dedupe_key = hashlib.md5(key_str.encode('utf-8')).hexdigest()
        
        with self._lock:
            cursor = self._dbs["conversations"].execute(
                """INSERT OR IGNORE INTO learning_events (agent_id, task_type, event_type, severity, pattern_key, summary, created_at, dedupe_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (agent_id, task_type, event_type, severity, pattern_key, summary, ts, dedupe_key)
            )
            self._dbs["conversations"].commit()
            return cursor.lastrowid

    def create_recommendation(self, source_event_id: Optional[int], target_agent: str, recommendation_type: str, payload: Dict[str, Any]) -> int:
        ts = datetime.now().isoformat()
        payload_json = json.dumps(payload, sort_keys=True)
        key_str = f"{target_agent}:{recommendation_type}:{payload_json}"
        dedupe_key = hashlib.md5(key_str.encode('utf-8')).hexdigest()
        
        with self._lock:
            # Check if dedupe_key already exists
            existing = self._dbs["conversations"].execute(
                "SELECT id FROM learning_recommendations WHERE dedupe_key = ?",
                (dedupe_key,)
            ).fetchone()
            if existing:
                logger.debug(f"LearningOrchestrator: recommendation with dedupe_key {dedupe_key} already exists.")
                return existing[0]

            cursor = self._dbs["conversations"].execute(
                """INSERT INTO learning_recommendations (source_event_id, target_agent, recommendation_type, payload_json, status, created_at, dedupe_key)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
                (source_event_id, target_agent, recommendation_type, payload_json, ts, dedupe_key)
            )
            self._dbs["conversations"].commit()
            return cursor.lastrowid

    def get_pending_recommendations(self, target_agent: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if target_agent:
                rows = self._dbs["conversations"].execute(
                    """SELECT id, source_event_id, target_agent, recommendation_type, payload_json, status, created_at
                       FROM learning_recommendations WHERE target_agent = ? AND status = 'pending'""",
                    (target_agent,)
                ).fetchall()
            else:
                rows = self._dbs["conversations"].execute(
                    """SELECT id, source_event_id, target_agent, recommendation_type, payload_json, status, created_at
                       FROM learning_recommendations WHERE status = 'pending'"""
                ).fetchall()
            
            results = []
            for r in rows:
                try:
                    payload = json.loads(r[4])
                except Exception:
                    payload = {}
                results.append({
                    "id": r[0],
                    "source_event_id": r[1],
                    "target_agent": r[2],
                    "recommendation_type": r[3],
                    "payload": payload,
                    "status": r[5],
                    "created_at": r[6]
                })
            return results

    def update_recommendation_status(self, recommendation_id: int, status: str) -> None:
        with self._lock:
            self._dbs["conversations"].execute(
                "UPDATE learning_recommendations SET status = ? WHERE id = ?",
                (status, recommendation_id)
            )
            self._dbs["conversations"].commit()

    def get_skill_gaps(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if agent_id:
                rows = self._dbs["conversations"].execute(
                    """SELECT id, agent_id, skill_area, failure_rate, last_updated, notes
                       FROM agent_skill_gaps WHERE agent_id = ?""",
                    (agent_id,)
                ).fetchall()
            else:
                rows = self._dbs["conversations"].execute(
                    """SELECT id, agent_id, skill_area, failure_rate, last_updated, notes
                       FROM agent_skill_gaps"""
                ).fetchall()
            
            return [{
                "id": r[0],
                "agent_id": r[1],
                "skill_area": r[2],
                "failure_rate": r[3],
                "last_updated": r[4],
                "notes": r[5]
            } for r in rows]

    def record_skill_gap(self, agent_id: str, skill_area: str, failure_rate: float, notes: Optional[str] = None) -> None:
        ts = datetime.now().isoformat()
        with self._lock:
            self._dbs["conversations"].execute(
                """INSERT INTO agent_skill_gaps (agent_id, skill_area, failure_rate, last_updated, notes)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id, skill_area) DO UPDATE SET
                   failure_rate=excluded.failure_rate, last_updated=excluded.last_updated, notes=excluded.notes""",
                (agent_id, skill_area, failure_rate, ts, notes)
            )
            self._dbs["conversations"].commit()

    def delete_skill_gap(self, agent_id: str, skill_area: str) -> None:
        with self._lock:
            self._dbs["conversations"].execute(
                "DELETE FROM agent_skill_gaps WHERE agent_id = ? AND skill_area = ?",
                (agent_id, skill_area)
            )
            self._dbs["conversations"].commit()

    def log_audit_trail(self, change_type: str, before_state: Optional[str], after_state: Optional[str], recommendation_id: Optional[int], notes: Optional[str] = None, status: str = 'applied', rollback_pointer: Optional[int] = None) -> int:
        ts = datetime.now().isoformat()
        with self._lock:
            cursor = self._dbs["conversations"].execute(
                """INSERT INTO learning_audit_log (change_type, before_state, after_state, recommendation_id, status, rollback_pointer, created_at, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (change_type, before_state, after_state, recommendation_id, status, rollback_pointer, ts, notes)
            )
            self._dbs["conversations"].commit()
            return cursor.lastrowid

    def get_audit_trail(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT id, change_type, before_state, after_state, recommendation_id, status, rollback_pointer, created_at, notes
                   FROM learning_audit_log ORDER BY id DESC LIMIT ?""",
                (limit,)
            ).fetchall()
            return [{
                "id": r[0],
                "change_type": r[1],
                "before_state": r[2],
                "after_state": r[3],
                "recommendation_id": r[4],
                "status": r[5],
                "rollback_pointer": r[6],
                "created_at": r[7],
                "notes": r[8]
            } for r in rows]

    def prune_stale_records(self, days: int = 30) -> Dict[str, int]:
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            cursor1 = self._dbs["conversations"].execute(
                "DELETE FROM learning_events WHERE created_at < ?",
                (cutoff_date,)
            )
            cursor2 = self._dbs["conversations"].execute(
                "DELETE FROM learning_recommendations WHERE status = 'resolved' AND created_at < ?",
                (cutoff_date,)
            )
            self._dbs["conversations"].commit()
            return {
                "pruned_events": cursor1.rowcount,
                "pruned_recommendations": cursor2.rowcount
            }

    def aggregate_historical_trends(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT agent_id, task_type, success, COUNT(*), AVG(duration_ms)
                   FROM agent_task_outcomes GROUP BY agent_id, task_type, success"""
            ).fetchall()
            trends = []
            for r in rows:
                trends.append({
                    "agent_id": r[0],
                    "task_type": r[1],
                    "success": bool(r[2]),
                    "count": r[3],
                    "avg_duration_ms": r[4]
                })
            return trends
