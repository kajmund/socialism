"""Gold-map v2: locate with space-run collapse, ground in original text.

Does not change default exact contains matching. Does not rewrite history.
"""

from __future__ import annotations

from dataclasses import dataclass

from overgraph_ingest.retrieval.gold import GoldSpan, RetrievalGold, span_matches
from overgraph_ingest.retrieval.index import StoredUnit

SPACE_CHARS = frozenset({" ", "\u00a0"})
EXACT = "exact"
SPACE_COLLAPSED = "space_collapsed"
UNIQUE = "unique"
AMBIGUOUS = "ambiguous"
ABSENT = "absent"
GOLD_MAP_VERSION = "gold-map-v2"


@dataclass(frozen=True)
class GroundedHit:
    relative_path: str
    unit_key: str
    unit_start: int
    unit_end: int
    exact_quote: str
    how: str
    source_char_start: int | None
    source_char_end: int | None


def collapse_space_runs(text: str) -> tuple[str, tuple[int, ...]]:
    """Collapse only regular and non-breaking spaces. Keep ☒, negation, newlines."""
    collapsed: list[str] = []
    origins: list[int] = []
    index = 0
    while index < len(text):
        if text[index] in SPACE_CHARS:
            collapsed.append(" ")
            origins.append(index)
            index += 1
            while index < len(text) and text[index] in SPACE_CHARS:
                index += 1
            continue
        collapsed.append(text[index])
        origins.append(index)
        index += 1
    return "".join(collapsed), tuple(origins)


def locate_contains(source: str, needle: str) -> list[tuple[int, int, str, str]]:
    """Return original offsets and exact original excerpts. Do not pick one hit."""
    if not needle:
        return []
    exact = _find_all(source, needle)
    if exact:
        return [(start, end, source[start:end], EXACT) for start, end in exact]
    collapsed_source, origins = collapse_space_runs(source)
    collapsed_needle, _ = collapse_space_runs(needle)
    if not collapsed_needle:
        return []
    hits = []
    for start, end in _find_all(collapsed_source, collapsed_needle):
        orig_start = origins[start]
        orig_end = origins[end - 1] + 1
        hits.append((orig_start, orig_end, source[orig_start:orig_end], SPACE_COLLAPSED))
    return hits


def ground_span(unit: StoredUnit, span: GoldSpan) -> list[GroundedHit]:
    if unit.relative_path != span.relative_path:
        return []
    hits = locate_contains(unit.text, span.contains)
    rows = []
    for start, end, quote, how in hits:
        source_start = None if unit.char_start is None else unit.char_start + start
        source_end = None if unit.char_start is None else unit.char_start + end
        rows.append(
            GroundedHit(
                relative_path=unit.relative_path,
                unit_key=unit.key,
                unit_start=start,
                unit_end=end,
                exact_quote=quote,
                how=how,
                source_char_start=source_start,
                source_char_end=source_end,
            )
        )
    return rows


def map_span(units: list[StoredUnit], span: GoldSpan) -> dict[str, object]:
    hits = [hit for unit in units for hit in ground_span(unit, span)]
    if not hits:
        status = ABSENT
    elif len(hits) == 1:
        status = UNIQUE
    else:
        status = AMBIGUOUS
    return {
        "relative_path": span.relative_path,
        "gold_contains": span.contains,
        "status": status,
        "v1_exact": any(
            unit.relative_path == span.relative_path and span_matches(unit.text, span)
            for unit in units
        ),
        "hits": [_hit_payload(hit) for hit in hits],
    }


def rematch_gold(units: list[StoredUnit], gold: RetrievalGold) -> dict[str, object]:
    rows = [map_span(units, span) for span in gold.relevant_units]
    return {
        "version": GOLD_MAP_VERSION,
        "does_not_change_default_contains": True,
        "does_not_rewrite_history": True,
        "does_not_alter_source_text": True,
        "normalizes_space_runs_only": True,
        "ambiguous_is_not_an_arbitrary_pick": True,
        "mapped": rows,
        "counts": {
            "relevant_units": len(rows),
            "v1_exact": sum(1 for row in rows if row["v1_exact"]),
            "unique": sum(1 for row in rows if row["status"] == UNIQUE),
            "ambiguous": sum(1 for row in rows if row["status"] == AMBIGUOUS),
            "absent": sum(1 for row in rows if row["status"] == ABSENT),
        },
    }


def _find_all(text: str, needle: str) -> list[tuple[int, int]]:
    hits = []
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return hits
        hits.append((index, index + len(needle)))
        start = index + 1


def _hit_payload(hit: GroundedHit) -> dict[str, object]:
    return {
        "relative_path": hit.relative_path,
        "unit_key": hit.unit_key,
        "unit_start": hit.unit_start,
        "unit_end": hit.unit_end,
        "exact_quote": hit.exact_quote,
        "how": hit.how,
        "source_char_start": hit.source_char_start,
        "source_char_end": hit.source_char_end,
    }
