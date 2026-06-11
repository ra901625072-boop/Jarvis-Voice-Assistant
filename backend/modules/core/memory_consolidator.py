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

import re
import math
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Any

logger = logging.getLogger("JARVIS.MemoryConsolidator")

# Decay constant: λ = 0.05 → half-life ≈ 14 days for low-importance content
_DECAY_LAMBDA = 0.05
# Memories below this decay score AND importance < 7 are deleted
_DECAY_THRESHOLD = 0.15
# Immune threshold — memories with importance >= this are never decayed
_IMMUNE_IMPORTANCE = 7


class MemoryConsolidator:
    """
    Consolidates and decays memory entries.
    Receives a reference to the live MemoryManager to share its DB connection.
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
            if snippet and snippet not in seen:
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


# ------------------------------------------------------------------ #
# Utility                                                              #
# ------------------------------------------------------------------ #

def _jaccard_sim(a: str, b: str, ngram: int = 3) -> float:
    """Character n-gram Jaccard similarity between two strings."""
    if not a or not b:
        return 0.0
    a_lower = a.lower()
    b_lower = b.lower()
    set_a = {a_lower[i:i+ngram] for i in range(len(a_lower) - ngram + 1)}
    set_b = {b_lower[i:i+ngram] for i in range(len(b_lower) - ngram + 1)}
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0
