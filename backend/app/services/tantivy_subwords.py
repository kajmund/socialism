"""Deterministic sub-word parts so Swedish compounds stay findable.

BM25 tokenises ``avtalsvillkor`` as one token, so a query for ``villkor`` would miss it.
Every token of at least ``MIN_COMPOUND`` characters is split at each position where both
halves are at least ``MIN_PART`` long, and the parts are indexed in a separate field.
Query terms shorter than ``MIN_QUERY_PART`` are never searched, so short strings cannot
match freely. Generic by construction: no dictionary and no per-word exceptions.
"""

from __future__ import annotations

import tantivy

SUBWORD_ANALYZER = "sub_v1"
SUBWORD_FIELD = "subwords"
MIN_COMPOUND = 8
MIN_PART = 3
MIN_QUERY_PART = 4


def _subword_analyzer() -> tantivy.TextAnalyzer:
    """Plain lowercase tokens: sub-word parts must match exactly, never stemmed."""
    return (
        tantivy.TextAnalyzerBuilder(tantivy.Tokenizer.simple())
        .filter(tantivy.Filter.lowercase())
        .build()
    )


def subword_parts(text: str) -> tuple[str, ...]:
    """Deterministic compound parts for a token, e.g. ``avtalsvillkor`` → ``avtal(s)``, ``villkor``.

    Only tokens of at least ``MIN_COMPOUND`` characters are decomposed, and every part must
    be at least ``MIN_PART`` long, so short words never match freely.
    """
    parts: list[str] = []
    for token in _subword_analyzer().analyze(text):
        token = token.strip()
        if len(token) < MIN_COMPOUND:
            continue
        parts.append(token)
        for cut in range(MIN_PART, len(token) - MIN_PART + 1):
            head, tail = token[:cut], token[cut:]
            if len(head) >= MIN_PART and len(tail) >= MIN_PART:
                parts.append(head)
                parts.append(tail)
    return tuple(dict.fromkeys(parts))


