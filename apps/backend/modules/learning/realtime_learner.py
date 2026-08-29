"""
realtime_learner.py
--------------------
Fast-loop, per-task learning. Runs once immediately after every single agent
task outcome is recorded (success or failure) — for every agent, including
the Supervisor/architect.

This complements, and never replaces, the nightly ground-truth batch run by
AgentSelfReflector / AgentCapabilityTracker / ExperienceReplay. Those still
own the authoritative 30-day / last-50-run numbers; this module only nudges
a live confidence signal and reacts instantly to a repeated, persisted
failure pattern instead of waiting for the next 03:05 run.

Called from BaseAgent.record_outcome() in the same background thread that
already writes agent_task_outcomes — so it costs nothing on the response
critical path.
"""

import logging
from datetime import datetime
from typing import Optional

from modules.learning import failure_patterns

logger = logging.getLogger("JARVIS.RealtimeLearner")

# EMA smoothing factor for the live confidence nudge. Higher = more reactive.
_EMA_ALPHA = 0.2
# Consecutive same-pattern failures (persisted, survives restarts) before
# we immediately promote a lesson instead of waiting for the nightly scan.
_MIN_STREAK_FOR_INSTANT_LESSON = 2
_HIGH_CONFIDENCE_THRESHOLD = 0.90
_LOW_CONFIDENCE_THRESHOLD = 0.60
_MIN_RUNS_FOR_LOW_FLAG = 3


class RealtimeLearner:
    def __init__(self, memory_manager):
        self.mm = memory_manager
        self._dbs = memory_manager.dbs
        self._lock = memory_manager._lock

    # ------------------------------------------------------------------ #
    # Entry point                                                          #
    # ------------------------------------------------------------------ #

    def process(
        self,
        agent_id: str,
        task_type: str,
        task_id: str,
        success: bool,
        error_summary: Optional[str],
        goal_hint: str,
        duration_ms: float,
    ) -> None:
        import os
        is_synthetic = (
            os.environ.get("JARVIS_E2E_SIM") == "1" or
            (goal_hint and (goal_hint.startswith("seed_") or goal_hint.startswith("e2e_sim_")))
        )
        if is_synthetic and os.environ.get("JARVIS_ALLOW_SEED_WRITES") != "1":
            return
        try:
            # 1. Update EMA & self-model thresholds
            ema = self._update_ema_capability(agent_id, task_type, task_id, success)
            self._apply_self_model_threshold(agent_id, task_type, ema)

            # 2. Record full episode & evaluate multi-dimensional utility
            from modules.learning.trajectory_collector import TrajectoryCollector
            from modules.learning.evaluator_engine import EvaluatorEngine
            from modules.learning.root_cause_analyzer import RootCauseAnalyzer

            evaluator = EvaluatorEngine()
            collector = TrajectoryCollector(
                agent_id=agent_id,
                task_type=task_type,
                goal=goal_hint,
                episode_id=task_id if task_id and task_id.startswith("ep_") else None
            )
            # Add top-level summary step
            collector.add_step(
                action=f"{agent_id}.{task_type}",
                observation="Completed successfully" if success else error_summary,
                error=error_summary if not success else None,
                duration_ms=duration_ms
            )
            eval_score = evaluator.evaluate_episode({
                "success": success,
                "duration_ms": duration_ms,
                "outcome": {"error": error_summary},
                "trajectory": [s.to_dict() for s in collector.steps]
            })
            if not success:
                root_cause = RootCauseAnalyzer().analyze({
                    "agent_id": agent_id,
                    "task_type": task_type,
                    "goal": goal_hint,
                    "outcome": {"error": error_summary},
                    "trajectory": [s.to_dict() for s in collector.steps]
                })
                eval_score["root_cause"] = root_cause

            collector.finalize(
                success=success,
                error=error_summary,
                duration_ms=duration_ms,
                evaluation=eval_score
            )
            collector.save_to_db(self.mm)

            # 3. Handle streak or reset
            if success:
                self._reset_streak(agent_id, task_type)
            else:
                self._handle_failure(agent_id, task_type, error_summary, goal_hint)

            self._write_micro_reflection(agent_id, task_type, success, ema, goal_hint)
        except Exception as e:
            # Never let learning break the agent pipeline.
            logger.error(f"RealtimeLearner failed for {agent_id}/{task_type}: {e}", exc_info=True)

    # ------------------------------------------------------------------ #
    # 1. Live EMA confidence nudge                                         #
    # ------------------------------------------------------------------ #

    def _update_ema_capability(self, agent_id: str, task_type: str, task_id: str, success: bool) -> float:
        """
        Nudge a live EMA score toward this outcome. Does NOT touch success_rate /
        total_runs — those stay owned by the nightly AgentCapabilityTracker so the
        ground-truth numbers are never skewed by the fast loop.
        """
        outcome = 1.0 if success else 0.0
        ts = datetime.now().isoformat()
        with self._lock:
            row = self._dbs["conversations"].execute(
                "SELECT id, ema_score FROM agent_capability_scores WHERE agent_id = ? AND task_type = ?",
                (agent_id, task_type),
            ).fetchone()

            if row:
                row_id, prev_ema = row
                prev_ema = prev_ema if prev_ema is not None else 0.8
                new_ema = max(0.60, round((1 - _EMA_ALPHA) * prev_ema + _EMA_ALPHA * outcome, 4))
                self._dbs["conversations"].execute(
                    "UPDATE agent_capability_scores SET ema_score = ?, last_task_id = ? WHERE id = ?",
                    (new_ema, task_id, row_id),
                )
            else:
                # No nightly row yet (brand new agent/task_type combo) — seed one.
                new_ema = max(0.60, round(0.8 * 0.8 + _EMA_ALPHA * outcome, 4))
                self._dbs["conversations"].execute(
                    """INSERT INTO agent_capability_scores
                       (agent_id, task_type, success_rate, total_runs, confidence, last_updated, ema_score, last_task_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (agent_id, task_type, max(0.60, outcome), 1, max(0.60, outcome), ts, new_ema, task_id),
                )
            self._dbs["conversations"].commit()
        return new_ema
 
    def _apply_self_model_threshold(self, agent_id: str, task_type: str, ema: float) -> None:
        """Same threshold logic AgentCapabilityTracker uses nightly, applied instantly on the live EMA."""
        ts = datetime.now().isoformat()
        capability = f"{agent_id}:{task_type}"
        if ema >= _HIGH_CONFIDENCE_THRESHOLD:
            note = "High live confidence (>90%, real-time)"
        elif ema <= 0.60:
            note = "Clamped to minimum confidence (60%)"
            ema = 0.60
        else:
            return  # mid-range: let the nightly ground-truth pass own this capability's note
 
        with self._lock:
            self._dbs["conversations"].execute(
                """INSERT INTO agent_self_model (capability, category, confidence, notes, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(capability) DO UPDATE SET confidence=excluded.confidence, notes=excluded.notes, created_at=excluded.created_at""",
                (capability, agent_id, ema, note, ts),
            )
            self._dbs["conversations"].commit()

    # ------------------------------------------------------------------ #
    # 2. Persisted failure streak + instant lesson                        #
    # ------------------------------------------------------------------ #

    def _reset_streak(self, agent_id: str, task_type: str) -> None:
        ts = datetime.now().isoformat()
        with self._lock:
            self._dbs["conversations"].execute(
                """INSERT INTO agent_failure_streaks (agent_id, task_type, streak, last_pattern, updated_at)
                   VALUES (?, ?, 0, NULL, ?)
                   ON CONFLICT(agent_id, task_type) DO UPDATE SET streak=0, last_pattern=NULL, updated_at=excluded.updated_at""",
                (agent_id, task_type, ts),
            )
            self._dbs["conversations"].commit()

    def _handle_failure(self, agent_id: str, task_type: str, error_summary: Optional[str], goal_hint: str) -> None:
        pattern = failure_patterns.extract_pattern(error_summary)
        ts = datetime.now().isoformat()

        with self._lock:
            row = self._dbs["conversations"].execute(
                "SELECT streak, last_pattern FROM agent_failure_streaks WHERE agent_id = ? AND task_type = ?",
                (agent_id, task_type),
            ).fetchone()

            if row and row[1] == pattern:
                streak = row[0] + 1
            else:
                streak = 1  # different pattern than last time — restart the streak

            self._dbs["conversations"].execute(
                """INSERT INTO agent_failure_streaks (agent_id, task_type, streak, last_pattern, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(agent_id, task_type) DO UPDATE SET streak=excluded.streak, last_pattern=excluded.last_pattern, updated_at=excluded.updated_at""",
                (agent_id, task_type, streak, pattern, ts),
            )
            self._dbs["conversations"].commit()

        if streak >= _MIN_STREAK_FOR_INSTANT_LESSON:
            self._promote_instant_lesson(agent_id, task_type, pattern, streak, goal_hint)

    def _promote_instant_lesson(self, agent_id: str, task_type: str, pattern: str, streak: int, goal_hint: str) -> None:
        """
        Fires immediately on the Nth same-pattern failure in a row (persisted — survives
        restarts, unlike the old in-memory ExperienceReplay._agent_failure_counts).
        Reuses ExperienceReplay._store_lesson so it lands in the exact same
        lessons_learned / procedural_memories tables build_context() already reads.
        """
        lesson_text = (
            f"Agent '{agent_id}' failed '{task_type}' {streak} time(s) in a row due to: {pattern}"
            f"{f' (goal: {goal_hint})' if goal_hint else ''}. Try an alternative approach before retrying."
        )
        import os
        is_synthetic = (
            os.environ.get("JARVIS_E2E_SIM") == "1" or
            (goal_hint and (goal_hint.startswith("seed_") or goal_hint.startswith("e2e_sim_")))
        )
        prefix = "seed_rt_" if is_synthetic else "rt_"
        source_pattern = f"{prefix}{agent_id}_{task_type}_{pattern}"[:64]

        if hasattr(self.mm, "lifecycle") and hasattr(self.mm.lifecycle, "replayer"):
            is_new = self.mm.lifecycle.replayer._store_lesson(
                lesson=lesson_text,
                source_pattern=source_pattern,
                occurrence_count=streak,
                project="general",
            )
            if is_new:
                logger.info(f"RealtimeLearner: instant lesson stored for {agent_id}/{task_type} ({pattern})")

    # ------------------------------------------------------------------ #
    # 3. Micro-reflection — keeps agent_reflections fresh between nights   #
    # ------------------------------------------------------------------ #

    def _write_micro_reflection(self, agent_id: str, task_type: str, success: bool, ema: float, goal_hint: str) -> None:
        ts = datetime.now().isoformat()
        status = "succeeded" if success else "failed"
        text = f"[{agent_id}] '{task_type}' just {status} (live confidence: {round(ema * 100)}%)."
        if goal_hint:
            text += f" Goal: {goal_hint}"
        with self._lock:
            self._dbs["conversations"].execute(
                """INSERT INTO agent_reflections (reflection, period, created_at)
                   VALUES (?, ?, ?)""",
                (text, "realtime", ts),
            )
            self._dbs["conversations"].commit()
