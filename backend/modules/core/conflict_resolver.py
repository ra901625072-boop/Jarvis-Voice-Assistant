"""
conflict_resolver.py
--------------------
Detects and resolves contradictory facts in JARVIS semantic memory.

Problem
-------
Without conflict resolution, the memory store accumulates:
  "User's favorite language is Python"   (2024-01-01)
  "User's favorite language is Rust"     (2024-06-01)
  "User's favorite language is Go"       (2024-12-01)

All three coexist and confuse retrieval.

Solution
--------
Before storing a new semantic memory, scan existing memories for
the same subject + contradicting predicate.  If found:
  - Mark old entry as superseded (superseded=1, superseded_by=new_id)
  - Give new entry a recency importance bonus (+1)
  - Store new entry normally

Detection Strategy
------------------
1. Extract subject noun phrase from new content (first 4 content words)
2. FTS search existing semantic_memories for that subject
3. For each candidate, check predicate contradiction via keyword overlap
4. High-confidence contradiction → mark superseded
"""

import re
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger("JARVIS.ConflictResolver")

# Contradiction pairs: if old memory has word A and new has word B → conflict
_CONTRADICTION_PAIRS: List[Tuple[str, str]] = [
    ("python",   "rust"), ("python",  "go"),   ("python", "javascript"),
    ("rust",     "python"), ("rust",   "go"),
    ("react",    "vue"),  ("react",  "angular"), ("vue", "react"),
    ("windows",  "linux"), ("windows", "mac"),
    ("vscode",   "pycharm"), ("vscode", "vim"), ("vim", "vscode"),
    ("postgres", "mysql"), ("postgres", "sqlite"), ("mysql", "postgres"),
    ("monday",   "tuesday"), ("monday", "wednesday"),  # day preferences
    ("morning",  "evening"), ("morning", "night"),
    ("senior",   "junior"), ("junior", "senior"),
]

# Preference-signal phrases that precede a value
_PREFERENCE_ANCHORS = [
    r"(?:my |i )(?:favorite|preferred?|use|like|love|hate|prefer|always use)\s+(?:\w+\s+)?(?:is|are|=)\s+",
    r"(?:user(?:'s)? )(?:favorite|preferred?|language|framework|editor|tool|os)\s*(?:is|=)\s+",
    r"(?:i am|i'm)\s+(?:using|working with)\s+",
    r"(?:project|stack|setup)\s*(?:is|=)\s+",
]


class ConflictResolver:
    """
    Checks new semantic memories against existing ones for contradictions.
    Shared the DB connection and lock from MemoryManager.
    """

    def __init__(self, memory_manager):
        self.mm    = memory_manager
        self._dbs  = memory_manager.dbs
        self._lock = memory_manager._lock

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def check_and_resolve(
        self,
        new_content: str,
        importance: int,
        project: str = "general",
    ) -> int:
        """
        Check new_content against existing semantic_memories.

        Returns
        -------
        adjusted_importance : int
            importance unchanged if no conflict, +1 if conflict resolved
            (recency bonus for overriding outdated information)

        Side effects
        ------------
        Marks conflicting old memories as superseded=1.
        """
        # Only run on preference/fact-type content
        if not self._is_preference_statement(new_content):
            return importance

        subject = self._extract_subject(new_content)
        if not subject or len(subject) < 4:
            return importance

        conflicts = self._find_conflicts(subject, new_content, project)
        if not conflicts:
            return importance

        # Mark all conflicting memories as superseded
        for conflict_id in conflicts:
            with self._lock:
                self._dbs["conversations"].execute(
                    "UPDATE semantic_memories SET superseded=1 WHERE id=?",
                    (conflict_id,),
                )
            logger.info(f"Marked memory id={conflict_id} as superseded (conflict with new content).")

        with self._lock:
            self._dbs["conversations"].commit()

        return min(importance + 1, 10)  # recency bonus, capped at 10

    def merge_pass(self) -> int:
        """
        Full deduplication pass: scan all non-superseded semantic_memories,
        mark near-duplicates as superseded, keeping the highest-importance one.
        Returns the number of memories merged.
        """
        with self._lock:
            rows = self._dbs["conversations"].execute(
                """SELECT id, content, importance FROM semantic_memories
                   WHERE superseded=0 ORDER BY importance DESC, updated_at DESC"""
            ).fetchall()

        seen: List[Tuple[int, str]] = []  # (id, content)
        to_supersede: List[int] = []

        for row_id, content, importance in rows:
            is_dup = False
            for _, seen_content in seen:
                if _jaccard_sim(content, seen_content) > 0.85:
                    is_dup = True
                    break
            if is_dup:
                to_supersede.append(row_id)
            else:
                seen.append((row_id, content))

        if to_supersede:
            placeholders = ",".join("?" * len(to_supersede))
            with self._lock:
                self._dbs["conversations"].execute(
                    f"UPDATE semantic_memories SET superseded=1 WHERE id IN ({placeholders})",
                    to_supersede,
                )
                self._dbs["conversations"].commit()
            logger.info(f"Merge pass: superseded {len(to_supersede)} duplicate memories.")

        return len(to_supersede)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _is_preference_statement(self, content: str) -> bool:
        """Quick check: does this content express a preference or fact?"""
        text = content.lower()
        for pattern in _PREFERENCE_ANCHORS:
            if re.search(pattern, text):
                return True
        # Also catch "X is Y" format
        if re.search(r"\b\w+\s+(?:is|are|=)\s+\w+", text):
            return True
        return False

    def _extract_subject(self, content: str) -> str:
        """Extract a 2-4 word subject phrase from content."""
        # Remove leading "my", "i", "user's" etc.
        text = re.sub(r"^(?:my|i|user(?:'s)?|the)\s+", "", content.lower().strip())
        # Take first 4 meaningful words
        stop = {"a", "an", "the", "is", "are", "was", "were", "be", "been"}
        words = [w for w in text.split()[:6] if w not in stop]
        return " ".join(words[:3])

    def _find_conflicts(
        self,
        subject: str,
        new_content: str,
        project: str,
    ) -> List[int]:
        """
        Search existing semantic_memories for entries that:
        1. Have a similar subject (FTS or LIKE match)
        2. Contain a contradicting predicate value
        """
        new_lower = new_content.lower()

        try:
            # Build subject search terms (first 2 words)
            search_words = subject.split()[:2]
            like_clauses = " AND ".join(f"content LIKE ?" for _ in search_words)
            params = [f"%{w}%" for w in search_words]
            params.append(project)

            with self._lock:
                rows = self._dbs["conversations"].execute(
                    f"""SELECT id, content FROM semantic_memories
                        WHERE ({like_clauses})
                          AND project = ?
                          AND superseded = 0
                        LIMIT 20""",
                    params,
                ).fetchall()
        except Exception as e:
            logger.debug(f"Conflict search failed: {e}")
            return []

        conflicts = []
        for row_id, old_content in rows:
            old_lower = old_content.lower()
            if self._is_contradicting(old_lower, new_lower):
                conflicts.append(row_id)

        return conflicts

    def _is_contradicting(self, old_content: str, new_content: str) -> bool:
        """
        Check if old_content contradicts new_content using contradiction pairs.
        """
        for word_a, word_b in _CONTRADICTION_PAIRS:
            if word_a in old_content and word_b in new_content:
                return True
            if word_b in old_content and word_a in new_content:
                return True

        # Also detect same-predicate, different-value pattern
        # e.g., "favorite language is X" vs "favorite language is Y"
        old_match = re.search(r"(?:is|are|=)\s+(\w+)\s*$", old_content.strip())
        new_match = re.search(r"(?:is|are|=)\s+(\w+)\s*$", new_content.strip())
        if old_match and new_match:
            old_val = old_match.group(1)
            new_val = new_match.group(1)
            if old_val != new_val and len(old_val) > 2 and len(new_val) > 2:
                # Check if subjects are similar enough
                old_subj = old_content[:old_content.rfind(old_val)].strip().rstrip("is are =").strip()
                new_subj = new_content[:new_content.rfind(new_val)].strip().rstrip("is are =").strip()
                if _jaccard_sim(old_subj, new_subj) > 0.6:
                    return True

        return False


# ------------------------------------------------------------------ #
# Utility                                                              #
# ------------------------------------------------------------------ #

def _jaccard_sim(a: str, b: str, ngram: int = 3) -> float:
    if not a or not b:
        return 0.0
    a_l, b_l = a.lower(), b.lower()
    set_a = {a_l[i:i+ngram] for i in range(len(a_l) - ngram + 1)}
    set_b = {b_l[i:i+ngram] for i in range(len(b_l) - ngram + 1)}
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)
