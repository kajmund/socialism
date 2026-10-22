"""Deterministic per-need aggregation of Jev verdicts."""

from __future__ import annotations

import pytest

from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.sufficiency_experiment.aggregate import (
    aggregate_need,
    aggregate_plan,
)
from app.services.research.sufficiency_experiment.types import PassageEvaluation


def _row(need_id: str, verdict: str, *, evidence_id: str, passage_id: str) -> PassageEvaluation:
    return PassageEvaluation(
        job_id=f"{need_id}:{passage_id}",
        need_id=need_id,
        passage_id=passage_id,
        evidence_id=evidence_id,
        verdict=verdict,  # type: ignore[arg-type]
        model="scripted",
        latency_ms=0.0,
        input_chars=1,
        request_hash="x",
    )


def test_contradiction_wins_over_support() -> None:
    row = aggregate_need(
        "research_1",
        [
            _row("research_1", "SUPPORTED", evidence_id="e1", passage_id="p0"),
            _row("research_1", "CONTRADICTS", evidence_id="e1", passage_id="p1"),
        ],
    )
    assert row.sufficient is False
    assert row.contradictions == ("p1",)
    assert row.needs_narrative is False


def test_undecided_without_support_requests_narrative() -> None:
    row = aggregate_need(
        "research_1",
        [_row("research_1", "UNDECIDED", evidence_id="e1", passage_id="p0")],
    )
    assert row.sufficient is False
    assert row.needs_narrative is True


def test_missing_need_evaluations_fail_loudly() -> None:
    plan = ResearchPlan(
        needs=[
            ResearchNeed(
                id="research_1",
                question="q",
                why_needed="w",
                source_types=["case_knowledge"],
            )
        ]
    )
    with pytest.raises(ValueError, match="no passage evaluations"):
        aggregate_plan(plan, [])
