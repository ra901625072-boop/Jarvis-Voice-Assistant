"""
memory_gate.py
--------------
The Memory Write Gate for JARVIS.

Purpose
-------
Controls what actually becomes long-term memory.
Without a gate, every "hi" or "ok" pollutes the memory store,
degrading retrieval quality as the database grows.

Decision pipeline
-----------------
Input content + role + importance
    ↓
1. Hard reject  (noise, assistant acks, very short)
    ↓
2. Duplicate check (Jaccard vs recent memories)
    ↓
3. Frequency promotion (DEFER → PASS after N occurrences)
    ↓
PASS / REJECT / DEFER

Only ~15–25% of raw conversation turns should pass to typed tables.
"""

import hashlib
import logging
import threading
from collections import defaultdict, deque
from typing import Optional, Tuple

logger = logging.getLogger("JARVIS.MemoryGate")

# Tunable thresholds
_MIN_IMPORTANCE_PASS  = 5     # importance >= this → always PASS
_MIN_IMPORTANCE_DEFER = 3     # importance in [3,4] → DEFER (frequency check)
_DEFER_PROMOTE_COUNT  = 3     # DEFER topic seen this many times → PASS
_DUP_JACCARD_THRESH   = 0.82  # similarity above this → REJECT as duplicate
_MIN_CONTENT_LEN      = 8     # fewer chars than this → always REJECT
_RECENT_WINDOW        = 200   # how many recent hashes to remember for dup-check


class GateDecision:
    PASS   = "pass"
    REJECT = "reject"
    DEFER  = "defer"


class MemoryGate:
    """
    Stateful memory write gate.  One instance per MemoryManager.

    Thread-safe via internal lock.
    Maintains a rolling window of recent content fingerprints
    and a frequency counter for deferred topics.
    """

    def __init__(self):
        self._lock          = threading.Lock()
        self._recent_hashes = deque(maxlen=_RECENT_WINDOW)
        # topic fingerprint → count of occurrences in this session
        self._defer_counts: defaultdict = defaultdict(int)
        # topic fingerprint → content of first occurrence (for promotion)
        self._defer_content: dict       = {}

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def evaluate(
        self,
        content: str,
        role: str,
        importance: int,
        recent_semantic_contents: Optional[list] = None,
    ) -> Tuple[str, str]:
        """
        Evaluate whether content should be stored in long-term memory.

        Returns
        -------
        (decision, reason)
            decision : GateDecision.PASS | REJECT | DEFER
            reason   : human-readable explanation
        """
        # 1. Hard rejects
        if len(content.strip()) < _MIN_CONTENT_LEN:
            return GateDecision.REJECT, "too_short"

        if role == "assistant" and importance < 7:
            # Only store high-importance assistant content
            if not any(kw in content.lower() for kw in [
                "remember", "noted", "important", "critical", "goal", "lesson"
            ]):
                return GateDecision.REJECT, "assistant_noise"

        if importance <= 2:
            return GateDecision.REJECT, "importance_too_low"

        # 2. Duplicate detection (fast hash first)
        content_hash = self._fingerprint(content)
        with self._lock:
            if content_hash in self._recent_hashes:
                return GateDecision.REJECT, "exact_duplicate"

        # 3. Jaccard duplicate check against provided recent memories
        if recent_semantic_contents:
            for recent in recent_semantic_contents[-30:]:
                if _jaccard_sim(content, recent) > _DUP_JACCARD_THRESH:
                    return GateDecision.REJECT, "near_duplicate"

        # 4. High importance → always PASS
        if importance >= _MIN_IMPORTANCE_PASS:
            with self._lock:
                self._recent_hashes.append(content_hash)
            return GateDecision.PASS, "high_importance"

        # 5. Medium importance → DEFER (frequency promotion)
        if importance >= _MIN_IMPORTANCE_DEFER:
            topic_key = self._topic_key(content)
            with self._lock:
                self._defer_counts[topic_key] += 1
                count = self._defer_counts[topic_key]
                if topic_key not in self._defer_content:
                    self._defer_content[topic_key] = content

                if count >= _DEFER_PROMOTE_COUNT:
                    # Frequency threshold reached → promote
                    self._recent_hashes.append(content_hash)
                    # Reset so it doesn't keep re-promoting
                    self._defer_counts[topic_key] = 0
                    return GateDecision.PASS, f"frequency_promoted_{count}x"

            return GateDecision.DEFER, f"deferred_{count}x"

        # 6. Default reject (importance 1–2 already caught above)
        return GateDecision.REJECT, "below_threshold"

    def force_pass(self, content: str) -> None:
        """Force a content fingerprint into the recent-hashes window (bypass gate)."""
        with self._lock:
            self._recent_hashes.append(self._fingerprint(content))

    def reset_session(self) -> None:
        """Clear session-level frequency counters (call on new session start)."""
        with self._lock:
            self._defer_counts.clear()
            self._defer_content.clear()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fingerprint(content: str) -> str:
        """Short SHA-256 fingerprint of normalised content."""
        normalised = " ".join(content.lower().split())
        return hashlib.sha256(normalised.encode()).hexdigest()[:16]

    @staticmethod
    def _topic_key(content: str) -> str:
        """
        Coarse topic key: first 6 meaningful words, lowercased.
        Used to bucket similar messages for frequency counting.
        """
        stop = {"the", "a", "an", "is", "are", "was", "were", "i", "to", "of", "in", "on", "and", "or"}
        words = [w for w in content.lower().split() if w not in stop]
        return " ".join(words[:6])


# ------------------------------------------------------------------ #
# Utility                                                              #
# ------------------------------------------------------------------ #

def _jaccard_sim(a: str, b: str, ngram: int = 3) -> float:
    """Character n-gram Jaccard similarity."""
    if not a or not b:
        return 0.0
    a_l = a.lower()
    b_l = b.lower()
    set_a = {a_l[i:i+ngram] for i in range(len(a_l) - ngram + 1)}
    set_b = {b_l[i:i+ngram] for i in range(len(b_l) - ngram + 1)}
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)
