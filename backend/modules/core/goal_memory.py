"""
goal_memory.py
--------------
Active goal tracking and goal-relevance scoring for JARVIS.

Purpose
-------
Without goal awareness, JARVIS retrieves memories based purely on
semantic similarity to the query.  But the most relevant memories
are those related to what JARVIS is *currently trying to achieve*.

Example
-------
Active goal: "Build an autonomous JARVIS desktop agent"
Query:       "open chrome"

Without goal memory: retrieves generic browser-related memories.
With goal memory:    retrieves JARVIS-automation + Selenium memories first.

Goal-relevance adds +0.15 to the hybrid retrieval score.

Auto-detection
--------------
GoalMemory also auto-detects implicit goals from recent high-importance
semantic memories, so the user doesn't always need to set goals explicitly.
"""

import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

logger = logging.getLogger("JARVIS.GoalMemory")


class GoalMemory:
    """
    Manages active goals and provides goal-relevance scoring
    for the hybrid retrieval pipeline.
    """

    def __init__(self, memory_manager):
        self.mm    = memory_manager
        self._dbs  = memory_manager.dbs
        self._lock = memory_manager._lock
        # In-memory cache of active goals (refreshed on demand)
        self._goal_cache: List[Dict[str, Any]] = []
        self._cache_ts: str = ""
        self._goal_context_str_cache: str = ""
        self._goal_context_str_ts: float = 0.0

    # ------------------------------------------------------------------ #
    # Public API — Goal Management                                         #
    # ------------------------------------------------------------------ #

    def set_goal(
        self,
        goal: str,
        goal_type: str = "task",
        parent_id: Optional[int] = None,
        priority: int = 5,
        project: str = "general",
    ) -> int:
        """
        Add or update an active goal.  Returns the goal row id.
        """
        ts = datetime.now().isoformat()
        with self._lock:
            # Check if same goal already active
            existing = self._dbs["conversations"].execute(
                "SELECT id FROM active_goals WHERE goal=? AND status='active'",
                (goal,),
            ).fetchone()

            if existing:
                self._dbs["conversations"].execute(
                    "UPDATE active_goals SET priority=?, updated_at=? WHERE id=?",
                    (priority, ts, existing[0]),
                )
                self._dbs["conversations"].commit()
                self._invalidate_cache()
                return existing[0]

            cursor = self._dbs["conversations"].execute(
                """INSERT INTO active_goals
                   (goal, goal_type, parent_id, priority, project, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
                (goal, goal_type, parent_id, priority, project, ts, ts),
            )
            goal_id = cursor.lastrowid
            self._dbs["conversations"].commit()

        self._invalidate_cache()
        logger.info(f"Goal set: '{goal}' (id={goal_id}, priority={priority})")
        return goal_id

    def complete_goal(self, goal_id: int, outcome: str = "completed") -> bool:
        """Archive a goal as completed. Stores in episodic memory."""
        ts = datetime.now().isoformat()
        with self._lock:
            row = self._dbs["conversations"].execute(
                "SELECT goal, project FROM active_goals WHERE id=?", (goal_id,)
            ).fetchone()
            if not row:
                return False

            goal_text, project = row
            self._dbs["conversations"].execute(
                "UPDATE active_goals SET status=?, updated_at=? WHERE id=?",
                (outcome, ts, goal_id),
            )
            # Store completion as high-importance episodic memory
            self._dbs["conversations"].execute(
                """INSERT INTO episodic_memories
                   (content, importance, project, event_date, created_at)
                   VALUES (?, 7, ?, ?, ?)""",
                (f"Completed goal: {goal_text}", project, ts, ts),
            )
            self._dbs["conversations"].commit()

        self._invalidate_cache()
        logger.info(f"Goal id={goal_id} marked as {outcome}.")
        return True

    def get_active_goals(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """Return list of active goals, using cache when available."""
        if self._goal_cache and not refresh:
            return self._goal_cache

        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT id, goal, goal_type, parent_id, priority, project, created_at
                   FROM active_goals
                   WHERE status='active'
                   ORDER BY priority DESC, created_at ASC""",
            ).fetchall()

        goals = [
            {"id": r[0], "goal": r[1], "goal_type": r[2], "parent_id": r[3], "priority": r[4], "project": r[5], "created_at": r[6]}
            for r in rows
        ]
        self._goal_cache = goals
        self._cache_ts   = datetime.now().isoformat()
        return goals

    def add_sub_goal(self, parent_id: int, goal: str, goal_type: str = "action", priority: int = 5) -> int:
        """Helper to explicitly add a sub-goal attached to a parent goal."""
        # Find parent project to inherit
        goals = self.get_active_goals()
        parent = next((g for g in goals if g["id"] == parent_id), None)
        project = parent["project"] if parent else "general"
        
        return self.set_goal(
            goal=goal,
            goal_type=goal_type,
            parent_id=parent_id,
            priority=priority,
            project=project
        )

    def add_milestone(self, goal_id: int, milestone: str) -> None:
        """Add a progress milestone to an existing goal."""
        ts = datetime.now().isoformat()
        with self._lock:
            self._dbs["conversations"].execute(
                """INSERT INTO goal_progress (goal_id, milestone, status, created_at)
                   VALUES (?, ?, 'pending', ?)""",
                (goal_id, milestone, ts),
            )
            self._dbs["conversations"].commit()

    def get_goal_progress(self, goal_id: int) -> List[Dict]:
        """Return milestones for a goal."""
        with self._lock:
            rows = self._dbs["conversations"].execute(
                "SELECT milestone, status, created_at FROM goal_progress WHERE goal_id=? ORDER BY id",
                (goal_id,),
            ).fetchall()
        return [{"milestone": r[0], "status": r[1], "created_at": r[2]} for r in rows]

    # ------------------------------------------------------------------ #
    # Retrieval Scoring                                                    #
    # ------------------------------------------------------------------ #

    def goal_relevance_score(self, content: str) -> float:
        """
        Compute a goal-relevance score (0.0–1.0) for a memory content string.
        Higher = more relevant to current active goals.
        """
        goals = self.get_active_goals()
        if not goals:
            return 0.0

        content_lower = content.lower()
        max_score     = 0.0

        for goal in goals:
            goal_text = goal["goal"].lower()
            priority  = goal["priority"] / 10.0  # normalize 0–1

            # Keyword overlap
            goal_words = set(re.findall(r"\b\w{4,}\b", goal_text))
            content_words = set(re.findall(r"\b\w{4,}\b", content_lower))
            if not goal_words:
                continue

            overlap  = len(goal_words & content_words)
            overlap_ratio = overlap / len(goal_words)
            score    = overlap_ratio * priority

            if score > max_score:
                max_score = score

        return min(max_score, 1.0)

    def goal_context_string(self) -> str:
        """Return a formatted string of active goals for LLM context injection."""
        import time
        now = time.time()
        if self._goal_context_str_cache and (now - self._goal_context_str_ts < 30):
            return self._goal_context_str_cache

        goals = self.get_active_goals()
        if not goals:
            self._goal_context_str_cache = ""
            self._goal_context_str_ts = now
            return ""

        lines = ["--- ACTIVE GOALS ---"]
        
        # Build hierarchy
        goal_map = {g['id']: g for g in goals}
        root_goals = [g for g in goals if g['parent_id'] is None]
        
        def print_goal(g, indent=""):
            lines.append(f"{indent}- [{g['goal_type'].upper()}] {g['goal']} (ID: {g['id']}, Pri: {g['priority']})")
            children = [child for child in goals if child['parent_id'] == g['id']]
            for child in children:
                print_goal(child, indent + "  ")

        for g in root_goals[:5]: # Top 5 roots
            print_goal(g)
            
        result = "\n".join(lines)
        self._goal_context_str_cache = result
        self._goal_context_str_ts = now
        return result

    # ------------------------------------------------------------------ #
    # Auto-detection                                                       #
    # ------------------------------------------------------------------ #

    def auto_detect_goals(self) -> int:
        """
        Scan recent high-importance semantic memories for implicit goals.
        Looks for "build X", "create X", "develop X", "finish X" patterns.
        Returns number of goals auto-detected.
        """
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT content, project FROM semantic_memories
                   WHERE importance >= 7 AND created_at >= ? AND superseded=0
                   ORDER BY importance DESC
                   LIMIT 50""",
                (cutoff,),
            ).fetchall()

        goal_patterns = [
            r"(?:i want to|i need to|goal is to|trying to|working on|building|creating|developing|finishing)\s+(.{10,80}?)(?:\.|$)",
            r"(?:my goal|main goal|current goal)\s*(?:is|:)\s+(.{10,80}?)(?:\.|$)",
            r"(?:build|create|develop|finish|implement|deploy)\s+(?:a |an |the )?(.{5,60}?)(?:\s+(?:for|with|using)|[.,]|$)",
        ]

        detected = 0
        existing_goals = {g["goal"].lower() for g in self.get_active_goals()}

        for content, project in rows:
            for pattern in goal_patterns:
                match = re.search(pattern, content.lower())
                if match:
                    goal_candidate = match.group(1).strip().rstrip(".,;:")
                    if len(goal_candidate) < 10:
                        continue
                    if goal_candidate in existing_goals:
                        continue
                    self.set_goal(goal_candidate, priority=6, project=project or "general")
                    existing_goals.add(goal_candidate)
                    detected += 1
                    break  # one goal per memory entry

        if detected:
            logger.info(f"GoalMemory: auto-detected {detected} goal(s) from recent memories.")
        return detected

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _invalidate_cache(self) -> None:
        self._goal_cache = []
        self._cache_ts   = ""
        self._goal_context_str_cache = ""
        self._goal_context_str_ts = 0.0
