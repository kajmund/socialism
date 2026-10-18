"""Validate tag excerpts against stored TextUnits. Position is not legal proof."""

from __future__ import annotations

from dataclasses import dataclass

from overgraph_ingest.retrieval.index import StoredUnit


@dataclass(frozen=True)
class TagSource:
    unit_id: str
    excerpt: str
    start: int | None
    end: int | None
    validated: bool
    document_id: str = ""


def validate_source(
    excerpt: str,
    *,
    unit: StoredUnit | None,
    document_id: str,
) -> TagSource:
    text = excerpt.strip()
    if not text or unit is None:
        return TagSource("", text, None, None, False, document_id)
    if unit.document_id != document_id:
        return TagSource(unit.key, text, None, None, False, document_id)
    index = unit.text.find(text)
    if index < 0:
        return TagSource(unit.key, text, None, None, False, document_id)
    start = (unit.char_start or 0) + index
    return TagSource(unit.key, text, start, start + len(text), True, document_id)


def units_for_document(units: list[StoredUnit], relative_path: str) -> list[StoredUnit]:
    return [unit for unit in units if unit.relative_path == relative_path]
