"""Document coverage labels. Absence from top-k is never verified absence."""

from __future__ import annotations

from dataclasses import dataclass

from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit

UNEXAMINED = "UNEXAMINED"
NOT_FOUND = "NOT_FOUND"
HAS_EVIDENCE = "HAS_EVIDENCE"
NEEDS_ANALYSIS = "NEEDS_ANALYSIS"
VERIFIED_ABSENT = "VERIFIED_ABSENT"

FOLLOW_UP = frozenset({UNEXAMINED, NOT_FOUND, NEEDS_ANALYSIS})
THRESHOLDS = (0.8, 0.9, 0.95, 1.0)


@dataclass(frozen=True)
class DocumentStatus:
    relative_path: str
    status: str
    examined_units: int
    document_units: int
    has_evidence: bool
    coverage_complete: bool | None
    verified_absent: bool


def assign_statuses(
    selected: list[SearchHit],
    units: list[StoredUnit],
    gold: RetrievalGold,
    relevant_keys: set[str],
) -> dict[str, DocumentStatus]:
    selected_by_doc: dict[str, list[SearchHit]] = {}
    for hit in selected:
        selected_by_doc.setdefault(hit.relative_path, []).append(hit)
    units_by_doc: dict[str, list[StoredUnit]] = {}
    for unit in units:
        units_by_doc.setdefault(unit.relative_path, []).append(unit)
    rows: dict[str, DocumentStatus] = {}
    for path, document_units in units_by_doc.items():
        examined = selected_by_doc.get(path, [])
        has_evidence = any(hit.key in relevant_keys for hit in examined)
        complete = _coverage_complete(path, examined, gold)
        if has_evidence and complete is False:
            status = NEEDS_ANALYSIS
        elif has_evidence:
            status = HAS_EVIDENCE
        elif examined and len(examined) >= len(document_units):
            status = VERIFIED_ABSENT
        elif examined:
            status = NOT_FOUND
        else:
            status = UNEXAMINED
        rows[path] = DocumentStatus(
            relative_path=path,
            status=status,
            examined_units=len(examined),
            document_units=len(document_units),
            has_evidence=has_evidence,
            coverage_complete=complete,
            verified_absent=status == VERIFIED_ABSENT,
        )
    return rows


def _coverage_complete(
    path: str,
    examined: list[SearchHit],
    gold: RetrievalGold,
) -> bool | None:
    group = next((item for item in gold.coverage_groups if item.relative_path == path), None)
    if group is None:
        return None
    joined = "".join(hit.text for hit in examined)
    return all(snippet in joined for snippet in group.contains)
