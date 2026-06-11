"""
reflection_engine.py
--------------------
Autonomous daily reflection engine for JARVIS.

Responsibilities
----------------
1. Review all events from the past 24 hours:
   - episodic_memories
   - workflow_stats (success/fail patterns)
   - conversation topics from conversation_summaries
2. Detect recurring patterns and behavioral signals.
3. Extract implied user preferences.
4. Generate a structured daily reflection text.
5. Store in `agent_reflections` table.
6. Promote high-confidence reflections to `semantic_memories`.
"""

import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Any
from collections import Counter

logger = logging.getLogger("JARVIS.ReflectionEngine")


class ReflectionEngine:
    """
    Generates structured daily reflections by analyzing recent memory activity.
    Receives a reference to the live MemoryManager.
    """

    def __init__(self, memory_manager):
        self.mm    = memory_manager
        self._dbs  = memory_manager.dbs
        self._lock = memory_manager._lock

    # ------------------------------------------------------------------ #
    # Main entries                                                         #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """Backward-compatible: calls run_daily()."""
        self.run_daily()

    def run_daily(self) -> None:
        logger.info("ReflectionEngine: starting daily reflection...")
        try:
            reflection_parts = []

            # 1. Topic frequency analysis
            topic_insight = self._analyze_topic_frequency()
            if topic_insight:
                reflection_parts.append(topic_insight)

            # 2. Workflow pattern analysis
            wf_insight = self._analyze_workflow_patterns()
            if wf_insight:
                reflection_parts.append(wf_insight)

            # 3. Preference signal extraction
            pref_insight = self._extract_preference_signals()
            if pref_insight:
                reflection_parts.append(pref_insight)

            # 4. Activity summary
            activity_summary = self._build_activity_summary()
            if activity_summary:
                reflection_parts.append(activity_summary)

            if not reflection_parts:
                logger.info("Not enough activity for a meaningful reflection.")
                return

            full_reflection = "\n".join(reflection_parts)
            ts = datetime.now().isoformat()

            # Store reflection
            with self._lock:
                self._dbs["conversations"].execute(
                    "INSERT INTO agent_reflections (reflection, period, created_at) VALUES (?, 'daily', ?)",
                    (full_reflection, ts),
                )
                self._dbs["conversations"].commit()

            # Promote high-confidence reflections to semantic memory
            self._promote_to_semantic(reflection_parts, ts)

            logger.info("ReflectionEngine: reflection stored successfully.")

        except Exception as e:
            logger.error(f"ReflectionEngine error: {e}", exc_info=True)

    # ------------------------------------------------------------------ #
    # Analysis methods                                                     #
    # ------------------------------------------------------------------ #

    def _analyze_topic_frequency(self) -> str:
        """
        Look at recent episodic memories and conversation summaries
        to identify what topics dominated the day.
        """
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()

        with self._lock:
            ep_rows = self._dbs["conversations"].execute(
                "SELECT content FROM episodic_memories WHERE created_at >= ?",
                (cutoff,),
            ).fetchall()

            conv_rows = self._dbs["conversations"].execute(
                "SELECT content FROM conversations WHERE timestamp >= ? AND role = 'user'",
                (cutoff,),
            ).fetchall()

        all_texts = [r[0] for r in ep_rows] + [r[0] for r in conv_rows]
        if not all_texts:
            return ""

        # Count domain keyword hits
        domain_keywords: List[Tuple[str, List[str]]] = [
            ("browser automation", ["selenium", "webdriver", "browser", "playwright", "automation"]),
            ("React development",  ["react", "jsx", "hooks", "component", "redux", "frontend"]),
            ("Python scripting",   ["python", "pip", "django", "flask", "script", "async"]),
            ("JARVIS development", ["jarvis", "agent", "livekit", "voice", "memory", "tool"]),
            ("file management",    ["file", "folder", "move", "copy", "delete", "directory"]),
            ("web searching",      ["search", "google", "wikipedia", "url", "website"]),
            ("system control",     ["volume", "brightness", "shutdown", "restart", "sleep"]),
            ("database work",      ["sqlite", "database", "query", "sql", "table", "schema"]),
        ]

        counts: Counter = Counter()
        combined = " ".join(all_texts).lower()
        for domain, keywords in domain_keywords:
            for kw in keywords:
                if kw in combined:
                    counts[domain] += combined.count(kw)

        if not counts:
            return ""

        top_domains = counts.most_common(3)
        if top_domains[0][1] < 2:
            return ""

        lines = ["📊 Daily Topic Analysis:"]
        for domain, count in top_domains:
            lines.append(f"  - {domain}: {count} occurrences")

        top_domain = top_domains[0][0]
        lines.append(
            f"\n→ Primary focus today: {top_domain}."
        )

        return "\n".join(lines)

    def _analyze_workflow_patterns(self) -> str:
        """
        Look at workflow_stats for tools/goals with high failure rates.
        Generate warnings or learning notes.
        """
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT goal_pattern, success_count, fail_count, avg_exec_time_ms, last_error
                   FROM workflow_stats
                   ORDER BY (fail_count * 1.0 / MAX(success_count + fail_count, 1)) DESC
                   LIMIT 10"""
            ).fetchall()

        if not rows:
            return ""

        lines = ["🔧 Workflow Learning:"]
        has_content = False

        for goal, succ, fail, avg_ms, last_err in rows:
            total = succ + fail
            if total < 2:
                continue
            rate = round(succ / total * 100, 1)

            if rate >= 90:
                lines.append(f"  ✓ '{goal}': {rate}% success rate — highly reliable.")
            elif rate >= 70:
                lines.append(f"  △ '{goal}': {rate}% success rate — generally reliable.")
            else:
                err_hint = f" Last error: {last_err[:60]}..." if last_err else ""
                lines.append(f"  ✗ '{goal}': {rate}% success rate — needs investigation.{err_hint}")
            has_content = True

        return "\n".join(lines) if has_content else ""

    def _extract_preference_signals(self) -> str:
        """
        Look for implicit preference signals in recent conversation content.
        E.g., repeated use of a tool → user prefers it.
        """
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()

        with self._lock:
            rows = self._dbs["conversations"].execute(
                "SELECT content FROM conversations WHERE timestamp >= ? AND role = 'user'",
                (cutoff,),
            ).fetchall()

        if not rows:
            return ""

        combined = " ".join(r[0] for r in rows).lower()

        # Detect implied preferences
        signals = []
        patterns = [
            (r"\buse\s+(\w+)\b",            "Tool usage"),
            (r"\bopen\s+(\w+)\b",           "Application preference"),
            (r"\bprefer\s+(\w+)\b",         "Explicit preference"),
            (r"\balways\s+(\w[\w\s]{0,20})\b", "Habitual behavior"),
        ]

        found: Counter = Counter()
        for pattern, _ in patterns:
            for match in re.finditer(pattern, combined):
                token = match.group(1).strip()
                if len(token) > 2 and token not in {"the", "a", "an", "to", "of", "in", "on"}:
                    found[token] += 1

        top_tokens = [(t, c) for t, c in found.most_common(5) if c >= 2]
        if not top_tokens:
            return ""

        lines = ["💡 Inferred Preferences (from today's activity):"]
        for token, count in top_tokens:
            lines.append(f"  - '{token}' used/referenced {count}× today.")

        return "\n".join(lines)

    def _build_activity_summary(self) -> str:
        """Build a brief quantitative summary of today's session."""
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()

        with self._lock:
            conv_count = self._dbs["conversations"].execute(
                "SELECT COUNT(*) FROM conversations WHERE timestamp >= ?", (cutoff,)
            ).fetchone()[0]

            mem_count = self._dbs["conversations"].execute(
                "SELECT COUNT(*) FROM semantic_memories WHERE created_at >= ?", (cutoff,)
            ).fetchone()[0]

            ep_count = self._dbs["conversations"].execute(
                "SELECT COUNT(*) FROM episodic_memories WHERE created_at >= ?", (cutoff,)
            ).fetchone()[0]

        if conv_count == 0:
            return ""

        date_str = datetime.now().strftime("%Y-%m-%d")
        return (
            f"📅 Session Summary ({date_str}):\n"
            f"  - Conversation turns: {conv_count}\n"
            f"  - New semantic memories: {mem_count}\n"
            f"  - New episodic memories: {ep_count}"
        )

    # ------------------------------------------------------------------ #
    # Promotion to semantic memory                                         #
    # ------------------------------------------------------------------ #

    def _promote_to_semantic(self, parts: List[str], timestamp: str) -> None:
        """
        High-confidence workflow and preference insights get promoted
        to semantic_memories so the context pipeline can use them.
        """
        for part in parts:
            if "Primary focus today:" in part or "Inferred Preferences" in part:
                # Extract the key insight line
                for line in part.split("\n"):
                    if line.startswith("→") or line.strip().startswith("- '"):
                        content = line.lstrip("→ ").strip()
                        if len(content) > 20:
                            with self._lock:
                                self._dbs["conversations"].execute(
                                    """INSERT INTO semantic_memories
                                       (content, importance, project, tags, decay_score, created_at, updated_at)
                                       VALUES (?, 6, 'general', 'reflection', 1.0, ?, ?)""",
                                    (f"[Reflection] {content}", timestamp, timestamp),
                                )
            elif "Workflow Learning:" in part:
                for line in part.split("\n"):
                    if "highly reliable" in line or "needs investigation" in line:
                        content = line.strip().lstrip("✓△✗ ")
                        if len(content) > 20:
                            importance = 7 if "highly reliable" in line else 6
                            with self._lock:
                                self._dbs["conversations"].execute(
                                    """INSERT INTO semantic_memories
                                       (content, importance, project, tags, decay_score, created_at, updated_at)
                                       VALUES (?, ?, 'general', 'workflow,reflection', 1.0, ?, ?)""",
                                    (f"[Workflow] {content}", importance, timestamp, timestamp),
                                )

        with self._lock:
            self._dbs["conversations"].commit()

    # ------------------------------------------------------------------ #
    # Weekly reflection                                                    #
    # ------------------------------------------------------------------ #

    def run_weekly(self) -> None:
        """
        Weekly reflection: patterns over the last 7 days.
        Stored in agent_reflections with period='weekly'.
        """
        logger.info("ReflectionEngine: starting weekly reflection...")
        try:
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=7)).isoformat()

            with self._lock:
                # Top workflows this week
                wf_rows = self._dbs["conversations"].execute(
                    """SELECT goal_pattern, success_count, fail_count
                       FROM workflow_stats
                       WHERE updated_at >= ?
                       ORDER BY (success_count + fail_count) DESC LIMIT 5""",
                    (cutoff,),
                ).fetchall()

                # New skills learned
                proc_rows = self._dbs["conversations"].execute(
                    "SELECT skill_name FROM procedural_memories WHERE created_at >= ? LIMIT 5",
                    (cutoff,),
                ).fetchall()

                # Goals completed this week
                goal_rows = self._dbs["conversations"].execute(
                    """SELECT goal, status FROM active_goals
                       WHERE updated_at >= ? AND status IN ('completed', 'failed')""",
                    (cutoff,),
                ).fetchall()

            parts = []

            if wf_rows:
                lines = ["📈 Weekly Workflow Summary:"]
                for goal, succ, fail in wf_rows:
                    total = succ + fail
                    rate  = round(succ / total * 100, 1) if total else 0
                    lines.append(f"  - '{goal}': {rate}% success ({total} runs)")
                parts.append("\n".join(lines))

            if proc_rows:
                skills = ", ".join(r[0] for r in proc_rows)
                parts.append(f"🔧 New skills learned this week: {skills}.")

            if goal_rows:
                lines = ["🎯 Goal Progress this week:"]
                for goal, status in goal_rows:
                    lines.append(f"  - '{goal[:60]}' → {status}")
                parts.append("\n".join(lines))

            if not parts:
                logger.info("Not enough data for weekly reflection.")
                return

            ts = datetime.now().isoformat()
            full_text = f"[Weekly Reflection — {datetime.now().strftime('%Y-%m-%d')}]\n" + "\n\n".join(parts)

            with self._lock:
                self._dbs["conversations"].execute(
                    "INSERT INTO agent_reflections (reflection, period, created_at) VALUES (?, 'weekly', ?)",
                    (full_text, ts),
                )
                self._dbs["conversations"].commit()

            logger.info("Weekly reflection stored.")
        except Exception as e:
            logger.error(f"Weekly reflection error: {e}", exc_info=True)

    # ------------------------------------------------------------------ #
    # Monthly reflection                                                   #
    # ------------------------------------------------------------------ #

    def run_monthly(self) -> None:
        """
        Monthly reflection: major behavioral changes over 30 days.
        Identifies top memories, knowledge graph growth, and trend shifts.
        """
        logger.info("ReflectionEngine: starting monthly reflection...")
        try:
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=30)).isoformat()

            with self._lock:
                # Top 5 highest-importance memories created this month
                top_mems = self._dbs["conversations"].execute(
                    """SELECT content, importance FROM semantic_memories
                       WHERE created_at >= ? AND superseded=0
                       ORDER BY importance DESC LIMIT 5""",
                    (cutoff,),
                ).fetchall()

                # How many new knowledge graph edges added
                kg_count = self._dbs["conversations"].execute(
                    "SELECT COUNT(*) FROM relationships WHERE created_at >= ?",
                    (cutoff,),
                ).fetchone()[0]

                # Total lessons learned this month
                lesson_count = self._dbs["conversations"].execute(
                    "SELECT COUNT(*) FROM lessons_learned WHERE created_at >= ?",
                    (cutoff,),
                ).fetchone()[0]

                # Workflow improvement: compare first half vs second half of month
                mid = (datetime.now() - timedelta(days=15)).isoformat()
                early_rate = self._dbs["conversations"].execute(
                    """SELECT AVG(success_count * 1.0 / MAX(success_count + fail_count, 1))
                       FROM workflow_stats WHERE updated_at BETWEEN ? AND ?""",
                    (cutoff, mid),
                ).fetchone()[0] or 0.0
                recent_rate = self._dbs["conversations"].execute(
                    """SELECT AVG(success_count * 1.0 / MAX(success_count + fail_count, 1))
                       FROM workflow_stats WHERE updated_at > ?""",
                    (mid,),
                ).fetchone()[0] or 0.0

            month_str = datetime.now().strftime("%B %Y")
            parts = [f"[Monthly Reflection — {month_str}]"]

            # Top memories
            if top_mems:
                lines = ["🧠 Most Important Memories This Month:"]
                for content, imp in top_mems:
                    lines.append(f"  [{imp}/10] {content[:120]}")
                parts.append("\n".join(lines))

            # Knowledge graph growth
            if kg_count > 0:
                parts.append(f"🕸️ Knowledge graph grew by {kg_count} relationship(s) this month.")

            # Lessons
            if lesson_count > 0:
                parts.append(f"📚 {lesson_count} new lesson(s) extracted from experience replay.")

            # Workflow trend
            if early_rate > 0 and recent_rate > 0:
                trend = "improved" if recent_rate > early_rate else "declined"
                diff  = round(abs(recent_rate - early_rate) * 100, 1)
                parts.append(
                    f"📊 Workflow reliability {trend} by {diff}% over the past month "
                    f"({round(early_rate*100,1)}% → {round(recent_rate*100,1)}%)."
                )

            ts = datetime.now().isoformat()
            full_text = "\n\n".join(parts)

            with self._lock:
                self._dbs["conversations"].execute(
                    "INSERT INTO agent_reflections (reflection, period, created_at) VALUES (?, 'monthly', ?)",
                    (full_text, ts),
                )
                self._dbs["conversations"].commit()

            logger.info("Monthly reflection stored.")
        except Exception as e:
            logger.error(f"Monthly reflection error: {e}", exc_info=True)
