"""Object-citation labels. artikel and klausul are not aliases of §."""

from __future__ import annotations

import re

from overgraph_ingest.coverage.clause_resolve import Citation

KIND = r"artikel|klausul|avsnitt|punkt|§"
ARABIC = r"\d+(?:\.\d+)*"
ROMAN = r"[IVXLCDM]+(?:\.\d+)*"
NUMBER = rf"(?:{ARABIC}|{ROMAN})"
OBJECT_LABEL_RE = re.compile(
    rf"(?:brott mot|överträdelse(?:r)? av)(?:\s+\w+ i)?\s+({KIND})\s*({NUMBER})",
    re.IGNORECASE,
)
ROMAN_RE = re.compile(rf"^{ROMAN}$", re.IGNORECASE)
NEW_KINDS = frozenset({"artikel", "klausul"})


def parse_object_labels(text: str) -> tuple[Citation, ...]:
    """Only the cited object of a breach, not every clause mention in the sentence."""
    return tuple(
        Citation(match.group(0), match.group(1).casefold(), match.group(2))
        for match in OBJECT_LABEL_RE.finditer(text)
    )


def is_roman(number: str) -> bool:
    return bool(ROMAN_RE.fullmatch(number))


def is_label_form(citation: Citation) -> bool:
    return citation.kind in NEW_KINDS or is_roman(citation.number)
