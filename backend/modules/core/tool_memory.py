"""
tool_memory.py
--------------
Per-tool performance tracking for JARVIS.

Purpose
-------
JARVIS has 40+ tools.  Some are highly reliable (95%+ success).
Others are fragile (Selenium scraping, OCR, screen vision).

Without tool memory, JARVIS has no way to:
1. Know which tool to prefer when multiple options exist
2. Warn the user when a tool is known to be unreliable
3. Recommend alternatives when a primary tool repeatedly fails

Architecture
------------
ToolMemory stores per-tool stats in the `tool_memory` SQLite table.
It is fed by the automatic wrapper in JarvisToolset.safe_execute()
so every tool call is recorded without any manual instrumentation.

Reliability score
-----------------
Rolling exponential moving average:
  new_score = 0.8 * old_score + 0.2 * (1.0 if success else 0.0)

This weights recent calls more heavily than old ones.
A tool that was bad but improved gradually recovers its score.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger("JARVIS.ToolMemory")

# Tunable
_EMA_ALPHA          = 0.20   # exponential moving average weight for new observations
_LOW_RELIABILITY    = 0.60   # tools below this get flagged
_MIN_CALLS_TO_FLAG  = 3      # don't flag until we have this many calls


class ToolMemory:
    """
    Records and retrieves per-tool performance metrics.
    Shared DB connection + lock from MemoryManager.
    """

    def __init__(self, memory_manager):
        self.mm    = memory_manager
        self._dbs  = memory_manager.dbs
        self._lock = memory_manager._lock

    # ------------------------------------------------------------------ #
    # Core recording                                                       #
    # ------------------------------------------------------------------ #

    def record(
        self,
        tool_name: str,
        success: bool,
        exec_time_ms: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """
        Record a tool call outcome.  Called automatically by safe_execute().
        """
        ts = datetime.now().isoformat()
        try:
            with self._lock:
                existing = self._dbs["conversations"].execute(
                    """SELECT id, success_count, fail_count,
                              avg_exec_time_ms, reliability_score
                       FROM tool_memory WHERE tool_name=?""",
                    (tool_name,),
                ).fetchone()

                if existing:
                    row_id, succ, fail, avg_ms, old_score = existing
                    new_succ  = succ + (1 if success else 0)
                    new_fail  = fail + (0 if success else 1)
                    total     = new_succ + new_fail
                    # Rolling average of execution time
                    new_avg   = int((avg_ms * (total - 1) + exec_time_ms) / total) if total else 0
                    # Exponential moving average reliability
                    new_score = _EMA_ALPHA * (1.0 if success else 0.0) + (1 - _EMA_ALPHA) * old_score
                    new_score = round(new_score, 4)

                    self._dbs["conversations"].execute(
                        """UPDATE tool_memory
                           SET success_count=?, fail_count=?, avg_exec_time_ms=?,
                               reliability_score=?, last_failure_reason=?, last_used=?, updated_at=?
                           WHERE id=?""",
                        (
                            new_succ, new_fail, new_avg, new_score,
                            error if not success else None,
                            ts, ts, row_id,
                        ),
                    )
                else:
                    init_score = 1.0 if success else (1 - _EMA_ALPHA)
                    self._dbs["conversations"].execute(
                        """INSERT INTO tool_memory
                           (tool_name, success_count, fail_count, avg_exec_time_ms,
                            last_failure_reason, last_used, reliability_score, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            tool_name,
                            1 if success else 0,
                            0 if success else 1,
                            exec_time_ms,
                            error if not success else None,
                            ts,
                            round(init_score, 4),
                            ts,
                        ),
                    )

                # Lazy commit — no force needed for analytics data
                self._dbs["conversations"].commit()

        except Exception as e:
            # Never let tool tracking break the main execution
            logger.debug(f"ToolMemory.record failed silently: {e}")

    # ------------------------------------------------------------------ #
    # Querying                                                             #
    # ------------------------------------------------------------------ #

    def get_reliability(self, tool_name: str) -> float:
        """Return reliability score (0–1) for a tool, or 1.0 if unknown."""
        with self._lock:
            row = self._dbs["conversations"].execute(
                "SELECT reliability_score, success_count, fail_count FROM tool_memory WHERE tool_name=?",
                (tool_name,),
            ).fetchone()
        if not row:
            return 1.0
        score, succ, fail = row
        total = succ + fail
        if total < _MIN_CALLS_TO_FLAG:
            return 1.0  # not enough data
        return score

    def get_tool_stats(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Return full stats dict for a tool."""
        with self._lock:
            row = self._dbs["conversations"].execute(
                """SELECT success_count, fail_count, avg_exec_time_ms,
                          reliability_score, last_failure_reason, last_used
                   FROM tool_memory WHERE tool_name=?""",
                (tool_name,),
            ).fetchone()
        if not row:
            return None
        succ, fail, avg_ms, score, last_err, last_used = row
        total = succ + fail
        return {
            "tool_name":       tool_name,
            "success_count":   succ,
            "fail_count":      fail,
            "total_calls":     total,
            "success_rate":    round(succ / total * 100, 1) if total else 0.0,
            "reliability":     score,
            "avg_exec_time_ms": avg_ms,
            "last_failure":    last_err,
            "last_used":       last_used,
        }

    def get_all_tool_report(self) -> str:
        """
        Return a formatted tool performance report for all tracked tools.
        Sorted by reliability ascending (worst first).
        """
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT tool_name, success_count, fail_count,
                          reliability_score, avg_exec_time_ms
                   FROM tool_memory
                   WHERE (success_count + fail_count) >= ?
                   ORDER BY reliability_score ASC""",
                (_MIN_CALLS_TO_FLAG,),
            ).fetchall()

        if not rows:
            return "No tool performance data available yet."

        lines = ["Tool Performance Report:"]
        for tool, succ, fail, score, avg_ms in rows:
            total    = succ + fail
            rate     = round(succ / total * 100, 1) if total else 0
            status   = "OK" if score >= _LOW_RELIABILITY else "UNRELIABLE"
            lines.append(
                f"  [{status}] {tool}: {rate}% success "
                f"({succ}/{total} calls, avg {avg_ms}ms, score={score:.2f})"
            )
        return "\n".join(lines)

    def get_unreliable_tools(self) -> List[Dict[str, Any]]:
        """Return tools with reliability below threshold and enough call history."""
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT tool_name, reliability_score, success_count, fail_count
                   FROM tool_memory
                   WHERE reliability_score < ?
                     AND (success_count + fail_count) >= ?
                   ORDER BY reliability_score ASC""",
                (_LOW_RELIABILITY, _MIN_CALLS_TO_FLAG),
            ).fetchall()

        return [
            {
                "tool_name":   r[0],
                "reliability": r[1],
                "success":     r[2],
                "fail":        r[3],
            }
            for r in rows
        ]

    def recommend_caution(self, tool_name: str) -> Optional[str]:
        """
        Return a caution string if a tool is known to be unreliable,
        or None if the tool is reliable or untracked.
        """
        score = self.get_reliability(tool_name)
        if score < _LOW_RELIABILITY:
            pct = round((1 - score) * 100, 1)
            return (
                f"Note: '{tool_name}' has been unreliable recently "
                f"({pct}% failure rate). Proceed with caution or use an alternative."
            )
        return None
