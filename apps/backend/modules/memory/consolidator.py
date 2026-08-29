"""
memory_consolidator.py
----------------------
Nightly memory consolidation and decay engine for JARVIS.

Responsibilities
----------------
1. Pull yesterday's raw conversation entries from `conversations`.
2. Group them into topic clusters using keyword similarity.
3. Generate an extractive summary for each cluster.
4. Store summaries in `conversation_summaries`.
5. Mark consolidated rows with `consolidated=1`.
6. Apply memory decay to `semantic_memories`:
       decay_score = importance × exp(-λ × age_days)
   Memories below the threshold with importance < 7 are pruned.
7. Deduplicate near-identical semantic memories.
"""

import math
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from modules.shared.utils import _jaccard_sim

logger = logging.getLogger("JARVIS.MemoryConsolidator")

# Decay constant: λ = 0.05 → half-life ≈ 14 days for low-importance content
_DECAY_LAMBDA = 0.05
# Memories below this decay score AND importance < 7 are deleted
_DECAY_THRESHOLD = 0.15
# Immune threshold — memories with importance >= this are never decayed
_IMMUNE_IMPORTANCE = 7


class MemoryConsolidator:
    """
    MemoryConsolidator manages daily memory tasks including conversation clustering, extractive summaries, and memory decay updates.

    SYSTEM PROMPT:
    Trigger MemoryConsolidator to run nightly compression runs to summarize yesterday's exchanges, delete obsolete facts, and decay low-value memories.

    SHORT DESCRIPTION:
    Orchestrates nightly consolidation of chat logs and applies exponential decay rules to long-term semantic records.

    PROCESS:
    1. Collects unconsolidated conversations from the database.
    2. Clusters entries into semantic topic groupings.
    3. Builds extractive summaries for each topic grouping and marks consolidated exchanges.
    4. Computes exponential decay calculations on semantic records (using age and base importance weights) and deletes records failing threshold limits.
    5. Deduplicates near-identical semantic statements.

    FLOW:
    Scheduler/Caller -> run() -> _consolidate_conversations() -> _apply_memory_decay() -> _deduplicate_semantic() -> Caller
    """

    def __init__(self, memory_manager):
        self.mm   = memory_manager
        self._dbs = memory_manager.dbs
        self._lock = memory_manager._lock

    # ------------------------------------------------------------------ #
    # Main entry                                                           #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        logger.info("MemoryConsolidator: starting daily run...")
        self._consolidate_conversations()
        self._backfill_missing_session_summaries()
        self._prune_expired_sessions()
        self._apply_memory_decay()
        self._deduplicate_semantic()
        logger.info("MemoryConsolidator: daily run complete.")

    # ------------------------------------------------------------------ #
    # Step 1: Conversation consolidation                                   #
    # ------------------------------------------------------------------ #

    def _consolidate_conversations(self) -> None:
        """Summarise yesterday's conversations and store in conversation_summaries."""
        yesterday_start = (datetime.now() - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        yesterday_end = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT id, role, content, COALESCE(importance, 3)
                   FROM conversations
                   WHERE timestamp >= ? AND timestamp < ?
                     AND consolidated = 0
                   ORDER BY id ASC""",
                (yesterday_start, yesterday_end),
            ).fetchall()

        if not rows:
            logger.info("No unconsolidated conversations to process.")
            return

        logger.info(f"Consolidating {len(rows)} conversation entries...")

        # Cluster entries by topic
        clusters = self._cluster_by_topic(rows)

        ts = datetime.now().isoformat()
        consolidated_ids = []

        for topic, entries in clusters.items():
            if not entries:
                continue
            summary = self._extractive_summary(topic, entries)
            if summary:
                with self._lock:
                    self._dbs["conversations"].execute(
                        """INSERT INTO conversation_summaries
                           (summary, period, topic, created_at)
                           VALUES (?, 'daily', ?, ?)""",
                        (summary, topic, ts),
                    )
                consolidated_ids.extend([e[0] for e in entries])

        # Mark all consolidated rows
        if consolidated_ids:
            placeholders = ",".join("?" * len(consolidated_ids))
            with self._lock:
                self._dbs["conversations"].execute(
                    f"UPDATE conversations SET consolidated=1 WHERE id IN ({placeholders})",
                    consolidated_ids,
                )
                self._dbs["conversations"].commit()
            logger.info(f"Marked {len(consolidated_ids)} entries as consolidated.")

    def _cluster_by_topic(
        self, rows: List[Tuple]
    ) -> Dict[str, List[Tuple]]:
        """
        Simple keyword-based topic clustering.
        Returns {topic_label: [(id, role, content, importance), ...]}
        """
        # Topic seed keywords
        topic_keywords: List[Tuple[str, List[str]]] = [
            ("Browser Automation",  ["selenium", "webdriver", "browser", "playwright", "chrome", "firefox"]),
            ("React Development",   ["react", "jsx", "hooks", "component", "redux", "next.js", "vite"]),
            ("Python Development",  ["python", "pip", "django", "flask", "fastapi", "asyncio", "script"]),
            ("JARVIS Development",  ["jarvis", "agent", "livekit", "voice", "assistant", "memory"]),
            ("Nova Project",        ["nova", "nova.ai"]),
            ("File & System",       ["file", "folder", "directory", "move", "copy", "delete", "rename"]),
            ("System Control",      ["volume", "brightness", "shutdown", "restart", "sleep", "lock"]),
            ("Web Search",          ["search", "google", "wikipedia", "browser", "url", "website"]),
            ("Git & Version Control",["git", "commit", "push", "pull", "branch", "merge", "github"]),
            ("Database",            ["sqlite", "database", "query", "sql", "chromadb", "table"]),
            ("General",             []),  # catch-all
        ]

        clusters: Dict[str, List] = {t: [] for t, _ in topic_keywords}

        for row in rows:
            row_id, role, content, importance = row
            text = content.lower()
            assigned = False
            for topic, keywords in topic_keywords[:-1]:  # skip General
                for kw in keywords:
                    if kw in text:
                        clusters[topic].append(row)
                        assigned = True
                        break
                if assigned:
                    break
            if not assigned:
                clusters["General"].append(row)

        # Remove empty clusters
        return {t: entries for t, entries in clusters.items() if entries}

    def _extractive_summary(
        self, topic: str, entries: List[Tuple]
    ) -> str:
        """
        Extractive summarisation: pick the highest-importance unique sentences.
        Returns a concise plaintext summary.
        """
        if not entries:
            return ""

        # Weight by importance, then pick top-N unique content snippets
        weighted = sorted(entries, key=lambda r: r[3], reverse=True)  # sort by importance desc

        lines = []
        seen: set = set()
        for _, role, content, importance in weighted[:8]:
            # Take first sentence or first 150 chars
            snippet = content.strip().split(".")[0][:150].strip()
            if snippet:
                is_dup = False
                snippet_lower = snippet.lower()
                for seen_item in seen:
                    if _jaccard_sim(snippet_lower, seen_item.lower()) > 0.75:
                        is_dup = True
                        break
                if not is_dup:
                    seen.add(snippet)
                    prefix = "User" if role == "user" else "JARVIS"
                    lines.append(f"  - [{prefix}] {snippet}")

        if not lines:
            return ""

        date_str = datetime.now().strftime("%Y-%m-%d")
        return (
            f"[{date_str}] Topic: {topic} ({len(entries)} exchanges)\n"
            + "\n".join(lines)
        )

    # ------------------------------------------------------------------ #
    # Step 2: Memory decay                                                 #
    # ------------------------------------------------------------------ #

    def _apply_memory_decay(self) -> None:
        """
        Apply exponential decay to semantic_memories.
        Formula: decay_score = importance × exp(-λ × age_days)
        Entries below threshold with importance < IMMUNE are deleted.
        """
        with self._lock:
            rows = self._dbs["conversations"].execute(
                "SELECT id, importance, created_at FROM semantic_memories WHERE importance < ?",
                (_IMMUNE_IMPORTANCE,),
            ).fetchall()

        to_delete = []
        to_update = []

        for row_id, importance, created_at in rows:
            try:
                age_days = self.mm._age_days(created_at)
            except Exception:
                age_days = 0.0
            decay = importance * math.exp(-_DECAY_LAMBDA * age_days)
            if decay < _DECAY_THRESHOLD * 10:   # scale: importance max=10, threshold=0.15*10=1.5
                to_delete.append(row_id)
            else:
                to_update.append((round(decay / 10.0, 4), row_id))

        if to_delete:
            placeholders = ",".join("?" * len(to_delete))
            with self._lock:
                self._dbs["conversations"].execute(
                    f"DELETE FROM semantic_memories WHERE id IN ({placeholders})",
                    to_delete,
                )
            logger.info(f"Decayed and pruned {len(to_delete)} low-value memories.")

        if to_update:
            with self._lock:
                self._dbs["conversations"].executemany(
                    "UPDATE semantic_memories SET decay_score=? WHERE id=?",
                    to_update,
                )

        with self._lock:
            self._dbs["conversations"].commit()

    # ------------------------------------------------------------------ #
    # Step 3: Deduplication                                                #
    # ------------------------------------------------------------------ #

    def _deduplicate_semantic(self) -> None:
        """
        Remove near-duplicate semantic memories (same content within 90% similarity).
        Uses simple character-level Jaccard similarity.
        """
        with self._lock:
            rows = self._dbs["conversations"].execute(
                "SELECT id, content, importance FROM semantic_memories ORDER BY importance DESC"
            ).fetchall()

        seen_contents: List[Tuple[int, str]] = []
        to_delete = []

        for row_id, content, importance in rows:
            is_dup = False
            for seen_id, seen_content in seen_contents:
                if _jaccard_sim(content, seen_content) > 0.88:
                    is_dup = True
                    break
            if is_dup:
                to_delete.append(row_id)
            else:
                seen_contents.append((row_id, content))

        if to_delete:
            placeholders = ",".join("?" * len(to_delete))
            with self._lock:
                self._dbs["conversations"].execute(
                    f"DELETE FROM semantic_memories WHERE id IN ({placeholders})",
                    to_delete,
                )
                self._dbs["conversations"].commit()
            logger.info(f"Removed {len(to_delete)} near-duplicate semantic memories.")

    def _backfill_missing_session_summaries(self) -> None:
        """Find sessions that ended but don't have a summary, and generate summaries for them."""
        logger.info("MemoryConsolidator: starting pass to backfill missing session summaries...")
        
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT session_id, project FROM sessions
                   WHERE ended_at IS NOT NULL AND summary IS NULL"""
            ).fetchall()
            
        if not rows:
            logger.info("MemoryConsolidator: no missing session summaries to backfill.")
            return
            
        logger.info(f"MemoryConsolidator: found {len(rows)} sessions missing summaries. Backfilling...")
        
        for session_id, project in rows:
            try:
                with self._lock:
                    turns = self._dbs["conversations"].execute(
                        "SELECT role, content, COALESCE(importance, 3) FROM conversations WHERE session_id = ? ORDER BY id ASC",
                        (session_id,),
                    ).fetchall()
                    
                if not turns or len(turns) < 4:
                    logger.debug(f"MemoryConsolidator: session {session_id} has too few turns ({len(turns)}), skipping summarization.")
                    with self._lock:
                        self._dbs["conversations"].execute(
                            "UPDATE sessions SET summary = '', topics = 'None' WHERE session_id = ?",
                            (session_id,),
                        )
                        self._dbs["conversations"].commit()
                    continue
                    
                formatted_turns = []
                for i, (role, content, importance) in enumerate(turns):
                    formatted_turns.append((i, role, content, importance))
                    
                clusters = self._cluster_by_topic(formatted_turns)
                
                cluster_summaries = []
                topics_found = []
                for topic, entries in clusters.items():
                    if not entries:
                        continue
                    summary = self._extractive_summary(topic, entries)
                    if summary:
                        cluster_summaries.append(summary)
                        if topic != "General":
                            topics_found.append(topic)
                            
                if not cluster_summaries:
                    continue
                    
                final_summary = "\n\n".join(cluster_summaries)
                topics_str = ", ".join(topics_found) if topics_found else "General"
                
                with self._lock:
                    self._dbs["conversations"].execute(
                        "UPDATE sessions SET summary = ?, topics = ? WHERE session_id = ?",
                        (final_summary, topics_str, session_id),
                    )
                    self._dbs["conversations"].commit()
                logger.info(f"MemoryConsolidator: backfilled summary for session {session_id}.")
                
            except Exception as e:
                logger.error(f"MemoryConsolidator: failed to backfill summary for session {session_id}: {e}", exc_info=True)

    def _prune_expired_sessions(self) -> None:
        """Prune raw conversation turns older than a retention window, preserving immune turns."""
        import os
        retention_days = int(os.getenv("JARVIS_CONVO_RETENTION_DAYS", "30"))
        logger.info(f"MemoryConsolidator: starting conversation pruning pass (Retention: {retention_days} days)...")
        
        cutoff_date = (datetime.now() - timedelta(days=retention_days)).isoformat()
        
        try:
            with self._lock:
                count_row = self._dbs["conversations"].execute(
                    """SELECT COUNT(*) FROM conversations c
                       JOIN sessions s ON c.session_id = s.session_id
                       WHERE c.timestamp < ? AND s.summary IS NOT NULL AND c.importance < ?""",
                    (cutoff_date, _IMMUNE_IMPORTANCE),
                ).fetchone()
                
                eligible_count = count_row[0] if count_row else 0
                if eligible_count == 0:
                    logger.info("MemoryConsolidator: no conversation turns eligible for pruning.")
                    return
                    
                cursor = self._dbs["conversations"].execute(
                    """DELETE FROM conversations
                       WHERE timestamp < ? 
                         AND session_id IN (SELECT session_id FROM sessions WHERE summary IS NOT NULL)
                         AND importance < ?""",
                    (cutoff_date, _IMMUNE_IMPORTANCE),
                )
                deleted = cursor.rowcount
                self._dbs["conversations"].commit()
                
            logger.info(f"MemoryConsolidator: pruned {deleted} conversation turns older than {cutoff_date}.")
        except Exception as e:
            logger.error(f"MemoryConsolidator: failed to prune expired conversations: {e}", exc_info=True)


