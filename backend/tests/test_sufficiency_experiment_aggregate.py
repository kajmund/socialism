"""Obligation aggregation. Naive single-support and contradiction-wins fail."""

from __future__ import annotations

import pytest

from app.services.research.evidence_screen import EvidenceJevScores
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.sufficiency_experiment.aggregate import (
    aggregate_need,
    aggregate_plan,
)
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    PassageEvaluation,
)


def _scores(
    evidence_id: str,
    *,
    relevant: float = 0.1,
    support: float = 0.1,
    contradict: float = 0.1,
) -> EvidenceJevScores:
    return EvidenceJevScores(
        evidence_id=evidence_id,
        source_type="case_knowledge",
        content_hash=f"hash-{evidence_id}",
        relevant_to_question=relevant,
        directly_supports_answer=support,
        contradicts_current_evidence=contradict,
        material_new_information=0.1,
        likely_duplicate_or_redundant=0.1,
        primary_or_high_authority_for_question=0.1,
        latency_ms=0.0,
    )


def _row(
    need_id: str,
    *,
    evidence_id: str,
    passage_id: str,
    independence_key: str,
    relevant: float = 0.1,
    support: float = 0.1,
    contradict: float = 0.1,
) -> PassageEvaluation:
    return PassageEvaluation(
        job_id=f"{need_id}:{passage_id}",
        need_id=need_id,
        passage_id=passage_id,
        evidence_id=evidence_id,
        scores=_scores(
            evidence_id, relevant=relevant, support=support, contradict=contradict
        ),
        independence_key=independence_key,
    )


def _need(*, source_types: list[str], capabilities: list[str] | None = None) -> ResearchNeed:
    return ResearchNeed(
        id="research_1",
        question="q",
        why_needed="w",
        source_types=source_types,  # type: ignore[arg-type]
        capabilities=capabilities or [],
    )


def test_one_supporting_passage_is_not_enough_when_completeness_is_missing() -> None:
    config = ExperimentConfig()
    need = _need(source_types=["case_knowledge", "swedish_law"])
    row = aggregate_need(
        need,
        [
            _row(
                "research_1",
                evidence_id="e1",
                passage_id="p0",
                independence_key="source-a",
                relevant=0.9,
                support=0.9,
            )
        ],
        config=config,
        evidence_by_id={},
        source_types_present=("case_knowledge",),
    )
    assert row.sufficient is False
    assert row.status == "insufficient"
    assert any(
        state.kind == "completeness" and not state.verified
        for state in row.obligation_states
    )


def test_contradiction_is_uncertain_not_final_insufficient() -> None:
    config = ExperimentConfig()
    need = _need(source_types=["case_knowledge"])
    row = aggregate_need(
        need,
        [
            _row(
                "research_1",
                evidence_id="e1",
                passage_id="p0",
                independence_key="source-a",
                relevant=0.9,
                support=0.9,
            ),
            _row(
                "research_1",
                evidence_id="e1",
                passage_id="p1",
                independence_key="source-a",
                relevant=0.9,
                contradict=0.9,
            ),
        ],
        config=config,
        evidence_by_id={},
        source_types_present=("case_knowledge",),
    )
    assert row.sufficient is False
    assert row.status == "uncertain"
    assert row.unresolved_conflicts
    assert row.contradictions == ("p1",)
    conflict = row.conflicts[0]
    assert conflict.status == "unresolved"
    assert conflict.has_unknown_counterpart is True
    assert conflict.resolution is None


def test_five_duplicates_are_one_independence_key() -> None:
    config = ExperimentConfig()
    need = _need(source_types=["case_knowledge"], capabilities=["corroboration"])
    rows = [
        _row(
            "research_1",
            evidence_id=f"e{index}",
            passage_id=f"p{index}",
            independence_key="source-shared",
            relevant=0.9,
            support=0.9,
        )
        for index in range(5)
    ]
    row = aggregate_need(
        need,
        rows,
        config=config,
        evidence_by_id={},
        source_types_present=("case_knowledge",),
    )
    assert row.sufficient is False
    support = next(state for state in row.obligation_states if state.kind == "factual_support")
    assert support.independent_support == 1
    assert support.verified is False


def test_unknown_source_types_are_uncertain() -> None:
    config = ExperimentConfig()
    need = _need(source_types=[])
    row = aggregate_need(
        need,
        [
            _row(
                "research_1",
                evidence_id="e1",
                passage_id="p0",
                independence_key="source-a",
                relevant=0.9,
                support=0.9,
            )
        ],
        config=config,
        evidence_by_id={},
    )
    assert row.unknown_requirements is True
    assert row.status == "uncertain"
    assert row.sufficient is False


def test_missing_need_evaluations_fail_loudly() -> None:
    plan = ResearchPlan(needs=[_need(source_types=["case_knowledge"])])
    with pytest.raises(ValueError, match="no passage evaluations"):
        aggregate_plan(plan, [], config=ExperimentConfig(), evidence_by_id={})
