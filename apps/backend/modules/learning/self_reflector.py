"""
agent_self_reflector.py
-----------------------
Reads agent_task_outcomes for a specific agent_id, computes task-type success rates,
most frequent failure patterns, and writes trends/lessons.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List

from modules.learning import failure_patterns

logger = logging.getLogger("JARVIS.AgentSelfReflector")

class AgentSelfReflector:
    def __init__(self, memory_manager):
        self.mm = memory_manager
        self._dbs = memory_manager.dbs
        self._lock = memory_manager._lock

    def run_for_agent(self, agent_id: str) -> None:
        """Run the full reflection pipeline for a specific agent."""
        logger.info(f"AgentSelfReflector: running for agent {agent_id}...")
        try:
            success_rates = self._compute_success_rates(agent_id)
            if not success_rates:
                return

            reflections = []
            for task_type, stats in success_rates.items():
                total = stats["total_count"]
                rate = stats["success_rate"]
                trend = self._detect_trend(agent_id, task_type)
                
                ref_text = f"[{agent_id}] '{task_type}' has {rate*100:.1f}% success over {total} runs. Trend: {trend}."
                reflections.append(ref_text)
                
                # If rate is low, extract clusters and potentially write lessons
                if rate < 0.6 and total >= 3:
                    clusters = self._extract_failure_clusters(agent_id, task_type)
                    for cluster_key, count in clusters.items():
                        if count >= 3:
                            lesson_text = f"Agent {agent_id} often fails on '{task_type}' due to: {cluster_key}. Use alternative approaches."
                            pattern_key = f"{agent_id}_{task_type}_{cluster_key[:10]}"
                            self._write_lesson(agent_id, task_type, lesson_text, pattern_key, count)

            if reflections:
                self._write_agent_reflection(agent_id, " | ".join(reflections))
                
        except Exception as e:
            logger.error(f"AgentSelfReflector error for {agent_id}: {e}", exc_info=True)

    def _compute_success_rates(self, agent_id: str) -> Dict[str, Dict[str, Any]]:
        """Compute success rates per task_type for the last 30 days."""
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT task_type, success FROM agent_task_outcomes
                   WHERE agent_id = ? AND created_at >= ?
                     AND (goal_hint IS NULL OR (goal_hint NOT LIKE 'seed_%' AND goal_hint NOT LIKE 'e2e_sim_%'))""",
                (agent_id, cutoff)
            ).fetchall()
            
        stats = {}
        for task_type, success in rows:
            if task_type not in stats:
                stats[task_type] = {"success_count": 0, "total_count": 0}
            stats[task_type]["total_count"] += 1
            if success:
                stats[task_type]["success_count"] += 1
                
        for task_type in stats:
            stats[task_type]["success_rate"] = stats[task_type]["success_count"] / stats[task_type]["total_count"]
            
        return stats

    def _extract_failure_clusters(self, agent_id: str, task_type: str) -> Dict[str, int]:
        """Group error summaries by common keywords.
        Delegates to the shared failure_patterns module (single source of truth).
        """
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT error_summary FROM agent_task_outcomes
                   WHERE agent_id = ? AND task_type = ? AND success = 0 AND created_at >= ?
                     AND error_summary IS NOT NULL
                     AND (goal_hint IS NULL OR (goal_hint NOT LIKE 'seed_%' AND goal_hint NOT LIKE 'e2e_sim_%'))""",
                (agent_id, task_type, cutoff)
            ).fetchall()
            
        clusters = {}
        for (err,) in rows:
            if not err:
                continue
            key = failure_patterns.extract_pattern(err)
            clusters[key] = clusters.get(key, 0) + 1
            
        return clusters

    def _detect_trend(self, agent_id: str, task_type: str) -> str:
        """Compares last-7-day vs previous-7-day success rate."""
        now = datetime.now()
        cutoff_7 = (now - timedelta(days=7)).isoformat()
        cutoff_14 = (now - timedelta(days=14)).isoformat()
        
        with self._lock:
            rows_recent = self._dbs["conversations"].execute(
                """SELECT success FROM agent_task_outcomes
                   WHERE agent_id = ? AND task_type = ? AND created_at >= ?
                     AND (goal_hint IS NULL OR (goal_hint NOT LIKE 'seed_%' AND goal_hint NOT LIKE 'e2e_sim_%'))""",
                (agent_id, task_type, cutoff_7)
            ).fetchall()
            
            rows_past = self._dbs["conversations"].execute(
                """SELECT success FROM agent_task_outcomes
                   WHERE agent_id = ? AND task_type = ? AND created_at >= ? AND created_at < ?
                     AND (goal_hint IS NULL OR (goal_hint NOT LIKE 'seed_%' AND goal_hint NOT LIKE 'e2e_sim_%'))""",
                (agent_id, task_type, cutoff_14, cutoff_7)
            ).fetchall()
            
        def _rate(r):
            if not r: return 0.0
            return sum([x[0] for x in r]) / len(r)
            
        rate_recent = _rate(rows_recent)
        rate_past = _rate(rows_past)
        
        if not rows_past or not rows_recent:
            return "stable"
            
        diff = rate_recent - rate_past
        if diff >= 0.1:
            return "improving"
        elif diff <= -0.1:
            return "degrading"
        return "stable"

    def _write_lesson(self, agent_id: str, task_type: str, lesson_text: str, pattern_key: str, count: int) -> None:
        """Call ExperienceReplay._store_lesson."""
        if hasattr(self.mm, 'lifecycle') and hasattr(self.mm.lifecycle, 'experience_replay'):
            self.mm.lifecycle.experience_replay._store_lesson(
                lesson=lesson_text,
                source_pattern=pattern_key,
                occurrence_count=count,
                project="general"
            )

    def _write_agent_reflection(self, agent_id: str, reflection: str) -> None:
        ts = datetime.now().isoformat()
        with self._lock:
            self._dbs["conversations"].execute(
                """INSERT INTO agent_reflections (reflection, period, created_at)
                   VALUES (?, ?, ?)""",
                (f"[{agent_id}] {reflection}", "agent_daily", ts)
            )
            self._dbs["conversations"].commit()
