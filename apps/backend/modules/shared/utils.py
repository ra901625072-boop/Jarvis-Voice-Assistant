"""
modules/core/utils.py
---------------------
Shared utility functions used across the JARVIS core memory modules.

Centralizes common algorithms to eliminate code duplication.
"""

import re
from typing import Set


def jaccard_similarity(text_a: str, text_b: str, ngram: int = 3, stop_words: Set[str] = None) -> float:
    """
    Compute Jaccard similarity between two text strings.
    If stop_words is provided, removes those words first.
    If ngram is specified (default 3), uses character n-grams.
    If ngram is None or 0, uses word sets.
    """
    if not text_a or not text_b:
        return 0.0

    a_raw, b_raw = text_a.lower(), text_b.lower()
    if stop_words:
        a_words = [w for w in a_raw.split() if w not in stop_words]
        b_words = [w for w in b_raw.split() if w not in stop_words]
        a_clean = " ".join(a_words)
        b_clean = " ".join(b_words)
    else:
        a_clean, b_clean = a_raw, b_raw

    if not a_clean or not b_clean:
        return 0.0

    if ngram and ngram > 0:
        set_a = {a_clean[i:i+ngram] for i in range(len(a_clean) - ngram + 1)}
        set_b = {b_clean[i:i+ngram] for i in range(len(b_clean) - ngram + 1)}
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)
    else:
        words_a: Set[str] = set(re.findall(r'\w+', a_clean))
        words_b: Set[str] = set(re.findall(r'\w+', b_clean))
        if not words_a and not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union) if union else 0.0


# Backwards-compatible alias used across memory and knowledge modules
_jaccard_sim = jaccard_similarity
