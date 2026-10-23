"""B0 gap review is shadow-only: recorded, bounded, never decisive."""

from __future__ import annotations

from dataclasses import replace

from app.services.research.sufficiency_experiment.claims import (
    extract_claim_candidates,
)
from app.services.research.sufficiency_experiment.golden import (
    duplicate_contradiction,
    tail_claim_contradiction,
)
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.narrative_gap import (
    build_gap_payload,
)
from app.services.research.sufficiency_experiment.scripted import (
    ScriptedSufficiencyJev,
)
from app.services.research.sufficiency_experiment.segment import segment_evidence
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    NarrativeGapReport,
)


def _report(**overrides) -> NarrativeGapReport:
    values = {
        "needs_more_evidence": True,
        "missing_evidence": ("pair not compared",),
        "questions": ("Is the tail claim compared?",),
        "suggested_workflows": ("evaluate_passages",),
        "cited_claim_ids": (),
        "rationale": "one pair looks missing",
        "model": "fake",
    }
    values.update(overrides)
    return NarrativeGapReport(**values)


def _config(gap: bool, pairs: bool = True) -> ExperimentConfig:
    return replace(
        ExperimentConfig(),
        gap_review_enabled=gap,
        pair_judgement=pairs,
        legacy_duplicate_resolution=pairs is False,
    )


async def _run(case, config, reviewer=None):
    loop = SufficiencyLoop(
        case.plan,
        case.evidence,
        client=ScriptedSufficiencyJev(),
        config=config,
    )
    if reviewer is not None:
        loop.bind_gap_reviewer(reviewer)
    await loop.run()
    assert loop.report is not None
    return loop.report


async def test_gap_review_is_recorded_without_authority() -> None:
    case = duplicate_contradiction()
    calls = []

    async def reviewer(payload):
        calls.append(payload)
        return _report()

    base = await _run(case, _config(False))
    shadow = await _run(case, _config(True), reviewer)
    assert len(calls) == 1
    assert shadow.gap_review is not None
    assert shadow.gap_review.needs_more_evidence is True
    assert shadow.draft.result == base.draft.result
    assert shadow.status == base.status


async def test_disabled_gap_review_never_calls_the_model() -> None:
    case = duplicate_contradiction()
    called = []

    async def reviewer(payload):
        called.append(payload)
        return _report()

    report = await _run(case, _config(False), reviewer)
    assert report.gap_review is None
    assert called == []


async def test_invalid_workflow_suggestion_is_rejected() -> None:
    case = duplicate_contradiction()
    report = await _run(
        case,
        _config(True),
        lambda payload: _async(_report(suggested_workflows=("search",))),
    )
    assert report.gap_review is not None
    assert report.gap_review.error == "invalid_workflow"


async def test_payload_reports_omitted_claims_explicitly() -> None:
    case = tail_claim_contradiction()
    config = ExperimentConfig()
    passages = segment_evidence(case.evidence, max_chars=config.max_passage_chars)
    claims, _ = extract_claim_candidates(
        passages,
        {item.evidence_id: item for item in case.evidence},
        config=config,
    )
    payload = build_gap_payload(
        case.plan,
        (),
        claims=claims,
        selection=None,
        coverage=None,
        max_chars=2_000,
    )
    assert payload["omitted_claim_count"] > 0
    assert len(payload["claims"]) + payload["omitted_claim_count"] == len(claims)


async def _async(value):
    return value
