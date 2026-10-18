"""Label examined units with stored structure. Evidence text stays original."""

from __future__ import annotations

from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.enrich import heading_titles

SOURCE_PREVIEW_CHARS = 240


def unit_heading(structure: dict[str, object]) -> str:
    titles = heading_titles(structure)
    leaf = titles[-1] if titles else str(structure.get("title") or "").strip()
    clause = str(structure.get("clause_number") or "").strip()
    if clause and leaf and clause not in leaf:
        return f"{clause} – {leaf}"
    return clause or leaf


def source_preview(unit: StoredUnit, structure: dict[str, object] | None = None) -> str:
    preview = unit.text[:SOURCE_PREVIEW_CHARS]
    heading = unit_heading(structure or {})
    if not heading:
        return preview
    return f"{heading}\n{preview}"


def state_unit(unit: StoredUnit, structure: dict[str, object] | None = None) -> dict[str, str]:
    payload = {"id": unit.key, "text": unit.text}
    heading = unit_heading(structure or {})
    if heading:
        payload["heading"] = heading
    return payload
