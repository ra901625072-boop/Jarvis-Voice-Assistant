"""
experience_replay.py
--------------------
Nightly lesson extraction engine for JARVIS.

Purpose
-------
Human experts learn from mistakes.  JARVIS should too.

Pipeline
--------
1. Scan episodic_memories for failure patterns (last 30 days)
2. Scan workflow_stats for consistently failing goals
3. Scan tool_memory for low-reliability tools
4. Cluster related failures by pattern similarity
5. Generate a concrete lesson for each cluster
6. Store in lessons_learned (if not already known)
7. Promote to procedural_memories (importance=8, immune to decay)

This is the mechanism that makes JARVIS truly learn from experience,
not just accumulate history.
"""

import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from collections import Counter

logger = logging.getLogger("JARVIS.ExperienceReplay")

# Minimum occurrences before a pattern generates a lesson
_MIN_PATTERN_OCCURRENCES = 2
# Minimum tool failure rate to trigger an avoidance lesson
_TOOL_FAILURE_THRESHOLD = 0.40


class ExperienceReplay:
    """
    Extracts lessons from repeated failures and stores them as
    permanent procedural memories.
    """

    def __init__(self, memory_manager):
        self.mm    = memory_manager
        self._dbs  = memory_manager.dbs
        self._lock = memory_manager._lock

    # ------------------------------------------------------------------ #
    # Main entry                                                           #
    # ------------------------------------------------------------------ #

    def run(self) -> int:
        """
        Run experience replay.  Returns the number of new lessons stored.
        """
        logger.info("ExperienceReplay: starting lesson extraction...")
        total_lessons = 0

        try:
            total_lessons += self._replay_episodic_failures()
            total_lessons += self._replay_workflow_failures()
            total_lessons += self._replay_tool_failures()

            if total_lessons:
                logger.info(f"ExperienceReplay: stored {total_lessons} new lesson(s).")
            else:
                logger.info("ExperienceReplay: no new lessons extracted.")
        except Exception as e:
            logger.error(f"ExperienceReplay error: {e}", exc_info=True)

        return total_lessons

    # ------------------------------------------------------------------ #
    # 1. Episodic failure replay                                           #
    # ------------------------------------------------------------------ #

    def _replay_episodic_failures(self) -> int:
        """
        Look for episodic memories that describe failures/errors.
        Cluster similar ones and extract a lesson per cluster.
        """
        cutoff = (datetime.now() - timedelta(days=30)).isoformat()
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT id, content, project FROM episodic_memories
                   WHERE created_at >= ?
                     AND (content LIKE '%fail%'
                          OR content LIKE '%error%'
                          OR content LIKE '%captcha%'
                          OR content LIKE '%block%'
                          OR content LIKE '%timeout%'
                          OR content LIKE '%crash%'
                          OR content LIKE '%exception%')
                   ORDER BY created_at DESC
                   LIMIT 100""",
                (cutoff,),
            ).fetchall()

        if not rows:
            return 0

        # Cluster by keyword pattern
        clusters: Dict[str, List[Tuple]] = {}
        for row_id, content, project in rows:
            pattern = self._extract_failure_pattern(content)
            if pattern:
                if pattern not in clusters:
                    clusters[pattern] = []
                clusters[pattern].append((row_id, content, project or "general"))

        count = 0
        for pattern, entries in clusters.items():
            if len(entries) < _MIN_PATTERN_OCCURRENCES:
                continue
            project = entries[0][2]
            lesson  = self._generate_episodic_lesson(pattern, entries)
            if lesson and self._store_lesson(lesson, pattern, len(entries), project):
                count += 1

        return count

    # ------------------------------------------------------------------ #
    # 2. Workflow failure replay                                           #
    # ------------------------------------------------------------------ #

    def _replay_workflow_failures(self) -> int:
        """
        Look at workflow_stats for goals with consistently low success rates.
        """
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT goal_pattern, success_count, fail_count, last_error
                   FROM workflow_stats
                   WHERE fail_count >= ? AND (fail_count * 1.0 / (success_count + fail_count)) >= ?
                   ORDER BY fail_count DESC
                   LIMIT 20""",
                (_MIN_PATTERN_OCCURRENCES, _TOOL_FAILURE_THRESHOLD),
            ).fetchall()

        count = 0
        for goal, succ, fail, last_err in rows:
            total     = succ + fail
            fail_rate = round(fail / total * 100, 1)
            pattern   = f"workflow_fail:{goal[:40]}"
            lesson    = (
                f"Workflow '{goal}' has a {fail_rate}% failure rate "
                f"({fail}/{total} attempts). "
                f"Consider breaking it into smaller steps or using alternative tools. "
                f"Last error: {last_err[:120] if last_err else 'unknown'}."
            )
            if self._store_lesson(lesson, pattern, fail, "general"):
                count += 1

        return count

    # ------------------------------------------------------------------ #
    # 3. Tool failure replay                                               #
    # ------------------------------------------------------------------ #

    def _replay_tool_failures(self) -> int:
        """
        Look at tool_memory for tools with low reliability.
        Generate avoidance or alternative lessons.
        """
        try:
            with self._lock:
                rows = self._dbs["conversations"].execute(
                    """SELECT tool_name, success_count, fail_count,
                              reliability_score, last_failure_reason
                       FROM tool_memory
                       WHERE reliability_score < ?
                         AND (success_count + fail_count) >= ?
                       ORDER BY reliability_score ASC
                       LIMIT 10""",
                    (1.0 - _TOOL_FAILURE_THRESHOLD, _MIN_PATTERN_OCCURRENCES),
                ).fetchall()
        except Exception:
            # tool_memory table may not exist yet
            return 0

        count = 0
        for tool, succ, fail, reliability, last_reason in rows:
            fail_pct = round((1 - reliability) * 100, 1)
            pattern  = f"tool_fail:{tool}"
            lesson   = (
                f"Tool '{tool}' is unreliable ({fail_pct}% failure rate). "
                f"Prefer alternative approaches when possible. "
                + (f"Common failure: {last_reason[:100]}." if last_reason else "")
            )
            if self._store_lesson(lesson, pattern, fail, "general"):
                count += 1

        return count

    # ------------------------------------------------------------------ #
    # Lesson storage                                                       #
    # ------------------------------------------------------------------ #

    def _store_lesson(
        self,
        lesson: str,
        source_pattern: str,
        occurrence_count: int,
        project: str,
    ) -> bool:
        """
        Store a lesson in lessons_learned and promote to procedural_memories.
        Returns True if the lesson was new (not already known).
        """
        ts = datetime.now().isoformat()
        try:
            with self._lock:
                # Check if lesson already exists
                existing = self._dbs["conversations"].execute(
                    "SELECT id, occurrence_count FROM lessons_learned WHERE source_pattern=?",
                    (source_pattern,),
                ).fetchone()

                if existing:
                    # Update occurrence count and refresh timestamp
                    self._dbs["conversations"].execute(
                        """UPDATE lessons_learned
                           SET occurrence_count=?, last_triggered=?
                           WHERE source_pattern=?""",
                        (max(existing[1], occurrence_count), ts, source_pattern),
                    )
                    self._dbs["conversations"].commit()
                    return False  # not a new lesson

                # Insert new lesson
                self._dbs["conversations"].execute(
                    """INSERT INTO lessons_learned
                       (lesson, source_pattern, occurrence_count, importance, created_at, last_triggered)
                       VALUES (?, ?, ?, 8, ?, ?)""",
                    (lesson, source_pattern, occurrence_count, ts, ts),
                )

                # Promote to procedural_memories (importance=8, immune to decay)
                skill_name = f"lesson:{source_pattern[:50]}"
                self._dbs["conversations"].execute(
                    """INSERT OR REPLACE INTO procedural_memories
                       (skill_name, content, importance, created_at, updated_at)
                       VALUES (?, ?, 8, ?, ?)""",
                    (skill_name, f"[Lesson] {lesson}", ts, ts),
                )

                self._dbs["conversations"].commit()
            logger.info(f"New lesson stored: {source_pattern}")
            return True

        except Exception as e:
            logger.error(f"Failed to store lesson: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Pattern extraction helpers                                           #
    # ------------------------------------------------------------------ #

    def _extract_failure_pattern(self, content: str) -> Optional[str]:
        """Extract a short canonical pattern string from failure content."""
        text = content.lower()

        patterns = [
            (r"captcha",              "captcha_triggered"),
            (r"timeout|timed out",    "request_timeout"),
            (r"selenium.*fail|fail.*selenium", "selenium_failure"),
            (r"blocked|rate.?limit",  "rate_limited"),
            (r"not found|404",        "resource_not_found"),
            (r"permission.?denied|access.?denied", "permission_denied"),
            (r"connection.?refused|connect.?error", "connection_error"),
            (r"crash|exception|traceback", "crash_or_exception"),
            (r"google.*fail|fail.*google",  "google_search_failure"),
            (r"download.?fail|failed.?download", "download_failure"),
        ]

        for regex, label in patterns:
            if re.search(regex, text):
                return label

        return None

    def _generate_episodic_lesson(
        self,
        pattern: str,
        entries: List[Tuple],
    ) -> str:
        """Generate a natural-language lesson from a clustered pattern."""
        count   = len(entries)
        project = entries[0][2]
        sample  = entries[0][1][:120]

        lessons_map = {
            "captcha_triggered": (
                f"Google/web search triggered CAPTCHA {count} time(s). "
                "Avoid rapid repeated scraping. Use the search API or add delays. "
                f"Example: {sample}"
            ),
            "request_timeout": (
                f"Request timeouts occurred {count} time(s). "
                "Add retry logic with exponential backoff. Check network stability."
            ),
            "selenium_failure": (
                f"Selenium automation failed {count} time(s). "
                "Ensure ChromeDriver is up-to-date. Add explicit waits. "
                f"Project: {project}."
            ),
            "rate_limited": (
                f"Rate limiting occurred {count} time(s). "
                "Slow down request frequency. Implement request queuing."
            ),
            "resource_not_found": (
                f"Resources not found {count} time(s). "
                "Validate paths/URLs before requesting. Add fallback logic."
            ),
            "permission_denied": (
                f"Permission denied {count} time(s). "
                "Check file/directory permissions. Run with appropriate privileges if needed."
            ),
            "connection_error": (
                f"Connection errors occurred {count} time(s). "
                "Check network availability. Add connection retry logic."
            ),
            "crash_or_exception": (
                f"Crashes/exceptions occurred {count} time(s) in project '{project}'. "
                "Add try/except blocks and improve error handling."
            ),
            "google_search_failure": (
                f"Google search failed {count} time(s). "
                "Use the live search API instead of direct scraping. "
                "Fall back to Wikipedia when Google is blocked."
            ),
            "download_failure": (
                f"Downloads failed {count} time(s). "
                "Check URLs for expiry. Add retry with fallback mirrors."
            ),
        }

        return lessons_map.get(pattern, f"Failure pattern '{pattern}' occurred {count} time(s). Sample: {sample}")
