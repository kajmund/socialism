"""A3 pair judgement: Jev detects, A2 resolves, nothing silently sufficient."""

from __future__ import annotations

from dataclasses import replace

from app.jev.system import JevClientError, JevSystemOneResult, JevUsage
from app.services.research.sufficiency_experiment.assessor import run_experiment
from app.services.research.sufficiency_experiment.claims import (
    extract_claim_candidates,
)
from app.services.research.sufficiency_experiment.golden import all_golden_cases
from app.services.research.sufficiency_experiment.pair_eval import (
    evaluate_pair,
    merge_pair_conflicts,
    pair_coverage,
)
from app.services.research.sufficiency_experiment.pairs import select_pairs
from app.services.research.sufficiency_experiment.scripted import ScriptedSufficiencyJev
from app.services.research.sufficiency_experiment.segment import segment_evidence
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    NeedAggregation,
    ObligationState,
    PairEvaluation,
)


class StubJev:
    def __init__(self, *, choice: str | None = None, error: Exception | None = None):
        self.choice = choice
        self.error = error
        self.calls = 0

    async def ask(self, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return JevSystemOneResult(
            answers={"relation": {"choice": self.choice}},
            model="stub",
            latency_ms=0.0,
            input_chars=0,
            usage=JevUsage(),
            raw={},
        )


def _config() -> ExperimentConfig:
    return ExperimentConfig()


def _parts(case_id: str):
    case = next(c for c in all_golden_cases() if c.case_id == case_id)
    config = _config()
    passages = segment_evidence(case.evidence, max_chars=config.max_passage_chars)
    claims, _ = extract_claim_candidates(
        passages,
        {item.evidence_id: item for item in case.evidence},
        config=config,
    )
    return case, passages, claims


async def _pair(case_id: str):
    case, passages, claims = _parts(case_id)
    selection = await select_pairs(
        claims, case.plan.needs, strategy="deterministic", config=_config()
    )
    pair = selection.selected[0]
    return {
        "pair": pair,
        "claims": {claim.claim_id: claim for claim in claims},
        "passages": {passage.passage_id: passage for passage in passages},
        "evidence": {item.evidence_id: item for item in case.evidence},
    }


async def _evaluate(case_id: str, stub: StubJev, *, config: ExperimentConfig | None = None):
    parts = await _pair(case_id)
    return await evaluate_pair(
        parts["pair"],
        claims=parts["claims"],
        passages=parts["passages"],
        evidence_by_id=parts["evidence"],
        client=stub,
        config=config or _config(),
    )


async def test_state_budget_skips_without_a_call() -> None:
    stub = StubJev(choice="CONTRADICTS")
    row = await _evaluate(
        "duplicate_contradiction",
        stub,
        config=replace(_config(), max_pair_state_chars=20),
    )
    assert row.status == "unevaluated"
    assert row.error == "pair_state_budget"
    assert stub.calls == 0


async def test_invalid_choice_is_unevaluated() -> None:
    row = await _evaluate("duplicate_contradiction", StubJev(choice="MAYBE"))
    assert row.status == "unevaluated"
    assert row.error == "invalid_response"


async def test_timeout_is_unevaluated() -> None:
    error = JevClientError("timed out", category="timeout")
    row = await _evaluate("duplicate_contradiction", StubJev(error=error))
    assert row.status == "unevaluated"
    assert row.error == "timeout"


async def test_insufficient_is_uncertain_not_technical() -> None:
    row = await _evaluate("duplicate_contradiction", StubJev(choice="INSUFFICIENT"))
    assert row.status == "uncertain"
    assert row.verdict == "INSUFFICIENT"
    coverage = pair_coverage((row,))
    assert coverage.uncertain == 1
    assert coverage.unevaluated == 0
    assert coverage.complete is True


async def test_contradicts_without_metadata_stays_unresolved() -> None:
    parts = await _pair("duplicate_contradiction")
    row = await _evaluate("duplicate_contradiction", StubJev(choice="CONTRADICTS"))
    aggregation = _aggregation()
    merged = merge_pair_conflicts(
        (aggregation,),
        (row,),
        claims=parts["claims"],
        evidence_by_id=parts["evidence"],
    )[0]
    assert merged.status == "uncertain"
    assert merged.conflicts[0].flagged_by == "jev_fact_pair"
    assert merged.conflicts[0].status == "unresolved"


async def test_compatible_creates_no_conflict() -> None:
    parts = await _pair("duplicate_contradiction")
    row = await _evaluate("duplicate_contradiction", StubJev(choice="COMPATIBLE"))
    merged = merge_pair_conflicts(
        (_aggregation(),),
        (row,),
        claims=parts["claims"],
        evidence_by_id=parts["evidence"],
    )[0]
    assert merged.conflicts == ()
    assert merged.status == "sufficient"


async def test_scope_difference_needs_verified_metadata() -> None:
    verified = await _evaluate("compatible_periods", StubJev(choice="SCOPE_DIFFERENCE"))
    parts = await _pair("compatible_periods")
    resolved = merge_pair_conflicts(
        (_aggregation(),),
        (verified,),
        claims=parts["claims"],
        evidence_by_id=parts["evidence"],
    )[0]
    assert resolved.conflicts[0].status == "not_applicable"
    assert resolved.status == "sufficient"

    unverified = await _evaluate(
        "duplicate_contradiction", StubJev(choice="SCOPE_DIFFERENCE")
    )
    other = await _pair("duplicate_contradiction")
    pending = merge_pair_conflicts(
        (_aggregation(),),
        (unverified,),
        claims=other["claims"],
        evidence_by_id=other["evidence"],
    )[0]
    assert pending.conflicts[0].status == "unresolved"
    assert pending.status == "uncertain"


async def test_contradicts_with_verified_scope_metadata_is_not_applicable() -> None:
    row = await _evaluate("compatible_periods", StubJev(choice="CONTRADICTS"))
    parts = await _pair("compatible_periods")
    merged = merge_pair_conflicts(
        (_aggregation(),),
        (row,),
        claims=parts["claims"],
        evidence_by_id=parts["evidence"],
    )[0]
    assert merged.conflicts[0].status == "not_applicable"


def test_unevaluated_pair_is_incomplete_coverage() -> None:
    coverage = pair_coverage(
        (
            PairEvaluation(
                pair_id="a|b",
                need_id="research_1",
                left_claim_id="a",
                right_claim_id="b",
                verdict=None,
                status="unevaluated",
                sources=("deterministic",),
                state_chars=10,
                latency_ms=0.0,
                error="timeout",
            ),
        )
    )
    assert coverage.complete is False
    assert coverage.reasons == ("timeout",)


def _aggregation() -> NeedAggregation:
    return NeedAggregation(
        research_need_id="research_1",
        status="sufficient",
        sufficient=True,
        obligation_states=(
            ObligationState(
                obligation_id="research_1:factual_support",
                kind="factual_support",
                verified=True,
                independent_support=1,
                contradicting_passage_ids=(),
            ),
        ),
        supporting_evidence_ids=("period-new",),
        contradictions=(),
        unresolved_conflicts=(),
        missing_or_weak="",
        unknown_requirements=False,
        conflicts=(),
    )


async def test_workflow_blocks_sufficient_on_unevaluated_pair() -> None:
    case = next(
        case
        for case in all_golden_cases()
        if case.case_id == "duplicate_contradiction"
    )
    config = replace(ExperimentConfig(), max_pair_state_chars=10)
    report = await run_experiment(
        case.plan,
        case.evidence,
        client=ScriptedSufficiencyJev(),
        config=config,
        counterparts=case.counterparts,
    )
    assert report.pair_coverage is not None
    assert report.pair_coverage.complete is False
    assert "pair_coverage_incomplete" in report.quality.reasons
    assert report.draft.result == "insufficient"
