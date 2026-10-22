"""A2: redundancy never resolves a conflict; only a typed reason does."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.research.assessment import AssessableEvidence
from app.services.research.evidence_screen import EvidenceJevScores
from app.services.research.models import ResearchNeed
from app.services.research.sufficiency_experiment.aggregate import aggregate_need
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    PassageEvaluation,
)


def _evidence(
    evidence_id: str,
    *,
    provenance: dict[str, object] | None = None,
) -> AssessableEvidence:
    return AssessableEvidence(
        evidence_id=evidence_id,
        research_need_id="research_1",
        source_type="case_knowledge",
        status="found",
        title=evidence_id,
        excerpt="text",
        locator=None,
        source_id=f"source-{evidence_id}",
        source_url=None,
        provider="fixture",
        score=1.0,
        provenance=provenance or {},
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_hash=f"hash-{evidence_id}",
    )


def _row(
    passage_id: str,
    *,
    evidence_id: str,
    support: float = 0.1,
    relevant: float = 0.9,
    contradict: float = 0.1,
    duplicate: float = 0.1,
    counterparts: tuple[str, ...] = (),
) -> PassageEvaluation:
    return PassageEvaluation(
        job_id=f"research_1:{passage_id}",
        need_id="research_1",
        passage_id=passage_id,
        evidence_id=evidence_id,
        scores=EvidenceJevScores(
            evidence_id=evidence_id,
            source_type="case_knowledge",
            content_hash=f"hash-{evidence_id}",
            relevant_to_question=relevant,
            directly_supports_answer=support,
            contradicts_current_evidence=contradict,
            material_new_information=0.1,
            likely_duplicate_or_redundant=duplicate,
            primary_or_high_authority_for_question=0.1,
            latency_ms=0.0,
        ),
        independence_key=f"source-{evidence_id}",
        counterpart_passage_ids=counterparts,
    )


def _need() -> ResearchNeed:
    return ResearchNeed(
        id="research_1",
        question="q",
        why_needed="w",
        source_types=["case_knowledge"],  # type: ignore[arg-type]
    )


def _aggregate(rows: list[PassageEvaluation], evidence: list[AssessableEvidence]):
    by_id = {item.evidence_id: item for item in evidence}
    return aggregate_need(
        _need(),
        rows,
        config=ExperimentConfig(),
        evidence_by_id=by_id,
        source_types_present=("case_knowledge",),
    )


def _supporting_row() -> PassageEvaluation:
    return _row("p0", evidence_id="e1", support=0.95)


def test_duplicate_score_never_resolves_a_contradiction() -> None:
    row = _aggregate(
        [
            _supporting_row(),
            _row("p1", evidence_id="e2", contradict=0.95, duplicate=0.89),
        ],
        [_evidence("e1"), _evidence("e2")],
    )
    assert row.conflicts[0].status == "unresolved"
    assert row.conflicts[0].resolution is None
    assert row.unresolved_conflicts == (row.conflicts[0].conflict_id,)
    assert row.sufficient is False
    assert row.status == "uncertain"


def test_single_side_conflict_is_never_resolved() -> None:
    row = _aggregate(
        [_supporting_row(), _row("p1", evidence_id="e2", contradict=0.95)],
        [_evidence("e1"), _evidence("e2")],
    )
    conflict = row.conflicts[0]
    assert conflict.has_unknown_counterpart is True
    assert conflict.status == "unresolved"
    assert conflict.resolution is None


def test_disjoint_validity_periods_are_not_applicable() -> None:
    old = _evidence(
        "e1",
        provenance={"valid_from": "2024-01-01", "valid_to": "2024-12-31"},
    )
    new = _evidence(
        "e2",
        provenance={"valid_from": "2026-01-01", "valid_to": "2026-12-31"},
    )
    row = _aggregate(
        [
            _row("p0", evidence_id="e1", support=0.95),
            _row("p1", evidence_id="e2", contradict=0.95, counterparts=("p0",)),
        ],
        [old, new],
    )
    conflict = row.conflicts[0]
    assert conflict.status == "not_applicable"
    assert conflict.resolution is not None
    assert conflict.resolution.kind == "temporal"
    assert conflict.resolution.evidence_ids == ("e2", "e1")
    assert row.unresolved_conflicts == ()
    assert row.sufficient is True


def test_distinct_contracts_are_not_applicable() -> None:
    first = _evidence("e1", provenance={"entity_id": "avtal-1"})
    second = _evidence("e2", provenance={"entity_id": "avtal-2"})
    row = _aggregate(
        [
            _row("p0", evidence_id="e1", support=0.95),
            _row("p1", evidence_id="e2", contradict=0.95, counterparts=("p0",)),
        ],
        [first, second],
    )
    conflict = row.conflicts[0]
    assert conflict.status == "not_applicable"
    assert conflict.resolution is not None
    assert conflict.resolution.kind == "entity"


def test_explicit_supersession_is_resolved() -> None:
    old = _evidence("e1", provenance={"superseded_by": "e2"})
    new = _evidence("e2")
    row = _aggregate(
        [
            _row("p0", evidence_id="e1", support=0.95),
            _row("p1", evidence_id="e2", contradict=0.95, counterparts=("p0",)),
        ],
        [old, new],
    )
    conflict = row.conflicts[0]
    assert conflict.status == "resolved"
    assert conflict.resolution is not None
    assert conflict.resolution.kind == "superseding"
    assert row.unresolved_conflicts == ()


def test_pair_without_metadata_stays_unresolved() -> None:
    row = _aggregate(
        [
            _supporting_row(),
            _row("p1", evidence_id="e2", contradict=0.95, counterparts=("p0",)),
        ],
        [_evidence("e1"), _evidence("e2")],
    )
    assert row.conflicts[0].status == "unresolved"
    assert row.conflicts[0].resolution is None


def test_missing_counterpart_evaluation_stays_unresolved() -> None:
    row = _aggregate(
        [
            _supporting_row(),
            _row("p1", evidence_id="e2", contradict=0.95, counterparts=("p9",)),
        ],
        [_evidence("e1"), _evidence("e2")],
    )
    assert row.conflicts[0].status == "unresolved"


def test_conflict_ids_are_stable_and_pair_order_independent() -> None:
    rows_a = [
        _supporting_row(),
        _row("p1", evidence_id="e2", contradict=0.95, counterparts=("p0",)),
    ]
    left = _aggregate(rows_a, [_evidence("e1"), _evidence("e2")])
    right = _aggregate(rows_a, [_evidence("e1"), _evidence("e2")])
    assert left.conflicts[0].conflict_id == right.conflicts[0].conflict_id
    assert left.conflicts[0].conflict_id.endswith(":p0:p1")
