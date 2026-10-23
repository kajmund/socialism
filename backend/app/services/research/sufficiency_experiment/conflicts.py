"""Deterministic conflict records for the sufficiency experiment.

Redundancy, relevance, source counts and document identity never resolve a
contradiction. A conflict is resolved only by a typed, verifiable difference in
validity period, entity or definition, or by an explicit supersession. A side
that is not identified is never invented: such a conflict stays unresolved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.services.research.assessment import AssessableEvidence
from app.services.research.sufficiency_experiment.types import (
    ConflictRecord,
    ConflictResolution,
    ConflictSide,
    ExperimentConfig,
    PassageEvaluation,
)

_STATUS_BY_KIND = {
    "temporal": "not_applicable",
    "entity": "not_applicable",
    "definition": "not_applicable",
    "superseding": "resolved",
}
_UNKNOWN = "unknown"


@dataclass(frozen=True)
class _Metadata:
    valid_from: datetime | None
    valid_to: datetime | None
    entity_id: str | None
    definition_id: str | None
    superseded_by: str | None


def build_conflicts(
    need_id: str,
    rows: Sequence[PassageEvaluation],
    evidence_by_id: Mapping[str, AssessableEvidence],
    *,
    config: ExperimentConfig,
) -> tuple[ConflictRecord, ...]:
    flagged = [
        row
        for row in rows
        if row.scores.contradicts_current_evidence >= config.contradict_threshold
    ]
    if config.legacy_duplicate_resolution:
        flagged = [
            row
            for row in flagged
            if row.scores.likely_duplicate_or_redundant < config.support_threshold
        ]
    indexed = {row.passage_id: row for row in rows}
    records: list[ConflictRecord] = []
    seen: set[str] = set()
    for row in flagged:
        first = _side(row.evidence_id, row.passage_id, evidence_by_id)
        if not row.counterpart_passage_ids:
            _append(records, seen, _record(need_id, (first,), None))
            continue
        for counterpart_id in row.counterpart_passage_ids:
            second = _counterpart_side(counterpart_id, indexed, evidence_by_id)
            resolution = metadata_resolution(first, second, evidence_by_id)
            _append(records, seen, _record(need_id, (first, second), resolution))
    return tuple(records)


def _append(
    records: list[ConflictRecord],
    seen: set[str],
    record: ConflictRecord,
) -> None:
    if record.conflict_id not in seen:
        seen.add(record.conflict_id)
        records.append(record)


def _record(
    need_id: str,
    sides: tuple[ConflictSide, ...],
    resolution: ConflictResolution | None,
) -> ConflictRecord:
    if len(sides) < 2:
        resolution = None
        status = "unresolved"
        key = f"{need_id}:{sides[0].passage_id or sides[0].evidence_id or _UNKNOWN}"
    else:
        status = _STATUS_BY_KIND[resolution.kind] if resolution else "unresolved"
        ids = sorted((sides[0].passage_id or "", sides[1].passage_id or ""))
        key = f"{need_id}:{ids[0]}:{ids[1]}"
    return ConflictRecord(
        conflict_id=key,
        need_id=need_id,
        status=status,
        sides=sides,
        resolution=resolution,
    )


def _side(
    evidence_id: str,
    passage_id: str | None,
    evidence_by_id: Mapping[str, AssessableEvidence],
) -> ConflictSide:
    item = evidence_by_id.get(evidence_id)
    return ConflictSide(
        evidence_id=evidence_id,
        passage_id=passage_id,
        source_id=item.source_id if item is not None else None,
    )


def _counterpart_side(
    passage_id: str,
    indexed: Mapping[str, PassageEvaluation],
    evidence_by_id: Mapping[str, AssessableEvidence],
) -> ConflictSide:
    row = indexed.get(passage_id)
    if row is None:
        return ConflictSide(evidence_id="", passage_id=passage_id)
    return _side(row.evidence_id, passage_id, evidence_by_id)


def metadata_resolution(
    first: ConflictSide,
    second: ConflictSide,
    evidence_by_id: Mapping[str, AssessableEvidence],
) -> ConflictResolution | None:
    if not first.evidence_id or not second.evidence_id:
        return None
    left = _metadata(first.evidence_id, evidence_by_id)
    right = _metadata(second.evidence_id, evidence_by_id)
    if left is None or right is None:
        return None
    checks = (
        _temporal_reason(left, right, first, second),
        _distinct_reason(
            kind="entity",
            rule_id="distinct_entity",
            left=left.entity_id,
            right=right.entity_id,
            first=first,
            second=second,
        ),
        _distinct_reason(
            kind="definition",
            rule_id="distinct_definition",
            left=left.definition_id,
            right=right.definition_id,
            first=first,
            second=second,
        ),
        _supersession_reason(left, right, first, second),
    )
    return next((reason for reason in checks if reason is not None), None)


def _temporal_reason(
    left: _Metadata,
    right: _Metadata,
    first: ConflictSide,
    second: ConflictSide,
) -> ConflictResolution | None:
    if not _disjoint(left, right):
        return None
    return _reason("temporal", "temporal_disjoint_intervals", first, second)


def _distinct_reason(
    *,
    kind: str,
    rule_id: str,
    left: str | None,
    right: str | None,
    first: ConflictSide,
    second: ConflictSide,
) -> ConflictResolution | None:
    if left is None or right is None or left == right:
        return None
    return _reason(kind, rule_id, first, second)


def _supersession_reason(
    left: _Metadata,
    right: _Metadata,
    first: ConflictSide,
    second: ConflictSide,
) -> ConflictResolution | None:
    superseded = left.superseded_by == second.evidence_id or right.superseded_by == first.evidence_id
    if not superseded:
        return None
    return _reason("superseding", "explicit_supersession", first, second)


def _reason(
    kind: str,
    rule_id: str,
    first: ConflictSide,
    second: ConflictSide,
) -> ConflictResolution:
    return ConflictResolution(
        kind=kind,
        rule_id=rule_id,
        evidence_ids=(first.evidence_id, second.evidence_id),
        detail=f"{rule_id}: {first.passage_id} vs {second.passage_id}",
    )


def _metadata(
    evidence_id: str,
    evidence_by_id: Mapping[str, AssessableEvidence],
) -> _Metadata | None:
    item = evidence_by_id.get(evidence_id)
    if item is None:
        return None
    provenance = item.provenance
    return _Metadata(
        valid_from=_as_datetime(provenance.get("valid_from")),
        valid_to=_as_datetime(provenance.get("valid_to")),
        entity_id=_as_text(provenance.get("entity_id")),
        definition_id=_as_text(provenance.get("definition_id")),
        superseded_by=_as_text(provenance.get("superseded_by")),
    )


def _disjoint(left: _Metadata, right: _Metadata) -> bool:
    if left.valid_to and right.valid_from and left.valid_to < right.valid_from:
        return True
    return bool(right.valid_to and left.valid_from and right.valid_to < left.valid_from)


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
