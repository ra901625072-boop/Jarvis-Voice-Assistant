"""
modules/core/utils.py
---------------------
Shared utility functions used across the JARVIS core memory modules.

Centralizes common algorithms to eliminate code duplication.
"""

import re
from typing import Set


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """
    Compute Jaccard similarity between two text strings based on word sets.

    Returns a float in [0.0, 1.0] where 1.0 = identical word sets.
    This function was previously duplicated in:
      - memory_gate.py
      - conflict_resolver.py
      - memory_consolidator.py
    """
    if not text_a or not text_b:
        return 0.0
    words_a: Set[str] = set(re.findall(r'\w+', text_a.lower()))
    words_b: Set[str] = set(re.findall(r'\w+', text_b.lower()))
    if not words_a and not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union) if union else 0.0


# Backwards-compatible alias (some modules use _jaccard_sim directly)
_jaccard_sim = jaccard_similarity
