"""Coverage metrics against passage and document gold. No Jev."""

from __future__ import annotations

from collections import Counter

from overgraph_ingest.coverage.status import (
    HAS_EVIDENCE,
    NEEDS_ANALYSIS,
    NOT_FOUND,
    THRESHOLDS,
    UNEXAMINED,
    VERIFIED_ABSENT,
    DocumentStatus,
    assign_statuses,
)
from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit


def evaluate_selection(
    *,
    name: str,
    selected: list[SearchHit],
    units: list[StoredUnit],
    gold: RetrievalGold,
    relevant_keys: set[str],
    extra_units: int = 0,
    phase1_units: int | None = None,
) -> dict[str, object]:
    statuses = assign_statuses(selected, units, gold, relevant_keys)
    relevant_docs = set(gold.relevant_documents)
    found_docs = {path for path, row in statuses.items() if row.has_evidence}
    found_units = {hit.key for hit in selected if hit.key in relevant_keys}
    counts = Counter(row.status for row in statuses.values())
    missed = sorted(relevant_docs - found_docs)
    touched_without_evidence = sorted(
        path
        for path in relevant_docs
        if statuses.get(path) is not None
        and not statuses[path].has_evidence
        and statuses[path].status != UNEXAMINED
    )
    false_negative = sorted(
        path
        for path, row in statuses.items()
        if path in relevant_docs and row.status == VERIFIED_ABSENT
    )
    unresolved = sorted(
        {
            path
            for path, row in statuses.items()
            if row.status == NEEDS_ANALYSIS
            or (path in relevant_docs and row.status in {UNEXAMINED, NOT_FOUND, NEEDS_ANALYSIS})
        }
    )
    return {
        "strategy": name,
        "candidates": len(selected),
        "would_be_jev_calls": len(selected),
        "phase1_units": phase1_units,
        "extra_units": extra_units,
        "document_recall": (len(found_docs & relevant_docs) / len(relevant_docs))
        if relevant_docs
        else 0.0,
        "evidence_recall": (len(found_units) / len(relevant_keys)) if relevant_keys else 0.0,
        "documents_found": len(found_docs & relevant_docs),
        "documents_expected": len(relevant_docs),
        "false_negative_documents": false_negative,
        "unexamined_relevant_documents": [
            path for path in missed if statuses.get(path) and statuses[path].status == UNEXAMINED
        ],
        "touched_relevant_without_evidence": touched_without_evidence,
        "unresolved_documents": unresolved,
        "missed_relevant_documents": missed,
        "status_counts": dict(counts),
        "curve": coverage_curve(selected, gold, relevant_keys),
        "documents": [_status_row(row, relevant_docs) for row in statuses.values()],
    }


def coverage_curve(
    selected: list[SearchHit],
    gold: RetrievalGold,
    relevant_keys: set[str],
    thresholds: tuple[float, ...] = THRESHOLDS,
) -> dict[str, object]:
    expected = set(gold.relevant_documents)
    found_docs: set[str] = set()
    found_units: set[str] = set()
    reached: dict[str, int | None] = {str(threshold): None for threshold in thresholds}
    for index, hit in enumerate(selected, start=1):
        if hit.key in relevant_keys:
            found_units.add(hit.key)
            if hit.relative_path in expected:
                found_docs.add(hit.relative_path)
        recall = (len(found_docs) / len(expected)) if expected else 0.0
        for threshold in thresholds:
            key = str(threshold)
            if reached[key] is None and recall + 1e-12 >= threshold:
                reached[key] = index
    return {
        "units_to_document_recall": reached,
        "final_document_recall": (len(found_docs) / len(expected)) if expected else 0.0,
        "final_evidence_recall": (len(found_units) / len(relevant_keys)) if relevant_keys else 0.0,
    }


def _status_row(row: DocumentStatus, relevant_docs: set[str]) -> dict[str, object]:
    return {
        "relative_path": row.relative_path,
        "status": row.status,
        "examined_units": row.examined_units,
        "document_units": row.document_units,
        "has_evidence": row.has_evidence,
        "coverage_complete": row.coverage_complete,
        "verified_absent": row.verified_absent,
        "relevant": row.relative_path in relevant_docs,
    }
