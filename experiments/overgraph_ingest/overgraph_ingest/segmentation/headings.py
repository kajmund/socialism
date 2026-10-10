"""Heading and clause cues from document formatting plus a small label family."""

from __future__ import annotations

import re
from collections.abc import Iterable

from overgraph_ingest.extraction.model import ExtractedBlock

SECTION_WORDS = ("Del", "Bilaga", "Appendix", "Avsnitt", "Kapitel")
SECTION_RE = re.compile(
    rf"^({'|'.join(SECTION_WORDS)})\s+",
    re.IGNORECASE,
)
# One outline family: 1, 1.1, A1, B10, A.1, Del A. Not a) / b) list markers.
OUTLINE_RE = re.compile(
    r"^(?:[A-Za-zÅÄÖåäö]{1,4}\d{0,4}|\d{1,4})"
    r"(?:[.\-](?:[A-Za-zÅÄÖåäö]{1,4}\d{0,4}|\d{1,4})){0,6}"
)
CLAUSE_RE = re.compile(r"^(\d+(?:\.\d+){0,6})\.?\s+\S.{0,200}$")
ALL_CAPS_RE = re.compile(r"^[A-ZÅÄÖ0-9][A-ZÅÄÖ0-9 \-/]{1,60}$")
_LETTER_RE = re.compile(r"[A-Za-zÅÄÖåäö]")
_TITLE_SEPARATORS = frozenset(" \t–—-")


def parse_clause_label(text: str) -> str | None:
    """Return an outline label when the first line starts with one and has a title."""
    first = text.strip().splitlines()[0] if text.strip() else ""
    if not first:
        return None
    rest = first
    section_match = SECTION_RE.match(rest)
    section = section_match.group(1) if section_match else None
    if section_match:
        rest = rest[section_match.end() :]
    outline_match = OUTLINE_RE.match(rest)
    if outline_match is None:
        return None
    outline = outline_match.group(0)
    if not _has_title_after_label(rest[outline_match.end() :]):
        return None
    if section:
        return f"{section} {outline}"
    if not any(char.isdigit() for char in outline):
        return None
    return outline


def clause_level(number: str) -> int:
    lowered = number.casefold()
    for word in SECTION_WORDS:
        prefix = f"{word.casefold()} "
        if lowered.startswith(prefix):
            rest = number[len(prefix) :].strip()
            return 1 + rest.count(".") + rest.count("-")
    if re.match(r"^[A-Za-zÅÄÖåäö]+\d", number):
        rest = re.sub(r"^[A-Za-zÅÄÖåäö]+", "", number)
        return 2 + rest.count(".") + rest.count("-")
    return number.count(".") + number.count("-") + 1


def apply_heading_cues(
    blocks: Iterable[ExtractedBlock],
    *,
    body_font_size: float | None,
) -> None:
    for block in blocks:
        first = block.text.strip().splitlines()[0] if block.text.strip() else ""
        label = parse_clause_label(first)
        if block.heading_level is not None:
            if label:
                block.clause_number = label
            continue
        if block.kind == "table_cell":
            continue
        if label:
            block.clause_number = label
            block.heading_level = clause_level(label)
            if block.kind == "paragraph":
                block.kind = "heading"
            continue
        if body_font_size and block.font_size and block.font_size >= body_font_size * 1.25:
            if len(first) <= 80:
                block.heading_level = 1
                block.kind = "heading"
                continue
        if _is_all_caps_heading(first, block.kind):
            block.heading_level = 1
            block.kind = "heading"


def _has_title_after_label(after: str) -> bool:
    stripped = after.lstrip(".)")
    if not stripped or stripped[0] not in _TITLE_SEPARATORS:
        return False
    return bool(stripped.strip(" \t–—-"))


def _is_all_caps_heading(text: str, kind: str) -> bool:
    if kind == "table_cell" or not _LETTER_RE.search(text):
        return False
    return bool(ALL_CAPS_RE.match(text)) and len(text) <= 60
