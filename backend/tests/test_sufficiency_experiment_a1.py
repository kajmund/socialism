"""A1: Jev uncertainty must not be ignored when the final status is set."""

from __future__ import annotations

from dataclasses import replace

from app.jev.system import JevSystemOneResult, JevUsage
from app.services.research.evidence_screen import EVIDENCE_SCREEN_QUESTIONS
from app.services.research.fast_controller import ASSESSMENT_QUESTIONS
from app.services.research.sufficiency_experiment.assessor import run_experiment
from app.services.research.sufficiency_experiment.golden import short_sufficient
from app.services.research.sufficiency_experiment.route import (
    authoritative_outcome,
    validate_route,
)
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    QualityDecision,
)

A0 = replace(
    ExperimentConfig(),
    route_authority=False,
    legacy_duplicate_resolution=True,
    pair_judgement=False,
)
A1 = replace(
    ExperimentConfig(),
    route_authority=True,
    legacy_duplicate_resolution=True,
    pair_judgement=False,
)


class RouteClient:
    def __init__(self, *, answerable: float, gap: float) -> None:
        self.answerable = answerable
        self.gap = gap

    async def ask(self, *, state, questions, model, timeout_seconds):
        if set(questions) == set(EVIDENCE_SCREEN_QUESTIONS):
            answers = {
                "relevant_to_question": _noul(0.95),
                "directly_supports_answer": _noul(0.95),
                "contradicts_current_evidence": _noul(0.05),
                "material_new_information": _noul(0.5),
                "likely_duplicate_or_redundant": _noul(0.05),
                "primary_or_high_authority_for_question": _noul(0.5),
            }
        elif set(questions) == set(ASSESSMENT_QUESTIONS):
            answers = {
                "answerable_now": _noul(self.answerable),
                "material_gap": _noul(self.gap),
                "contradiction": _noul(0.05),
                "follow_up_change": _noul(0.05),
                "additional_source": _noul(0.05),
            }
        else:
            raise AssertionError("unexpected question set")
        return JevSystemOneResult(
            answers=answers,
            model="scripted-a1",
            latency_ms=0.0,
            input_chars=0,
            usage=JevUsage(),
            raw={},
        )


def _noul(flag: float) -> dict[str, float]:
    return {"noul": flag}


def _quality(allows: bool) -> QualityDecision:
    return QualityDecision(
        allows_sufficient=allows,
        escalate_permitted=not allows,
        applicable_subworkflows=(),
        reasons=() if allows else ("obligations_unverified",),
        span_coverage=1.0,
        semantic_complete=allows,
        omitted_evidence_ids=(),
        missing_evaluations=(),
        budget_exhausted=False,
    )


def test_authority_predicate_uses_four_signals() -> None:
    assert (
        authoritative_outcome(
            answerable_now=0.95, material_gap=0.05, contradiction=0.05, confidence=0.95
        )
        == "sufficient"
    )
    assert (
        authoritative_outcome(
            answerable_now=0.85, material_gap=0.05, contradiction=0.05, confidence=0.95
        )
        == "uncertain"
    )
    assert (
        authoritative_outcome(
            answerable_now=0.05, material_gap=0.95, contradiction=0.05, confidence=0.95
        )
        == "insufficient"
    )


def test_finish_without_outcome_is_rejected() -> None:
    route = validate_route(
        "FINISH",
        _quality(True),
        evidence_ids=(),
        jev_outcome="sufficient",
    )
    assert route.valid is False
    assert route.choice == "UNCERTAIN"
    assert route.rejection == "FINISH without final outcome"


def test_finish_sufficient_with_blocked_gate_is_rejected() -> None:
    route = validate_route(
        "FINISH",
        _quality(False),
        evidence_ids=(),
        jev_outcome="sufficient",
        final_outcome="sufficient",
    )
    assert route.valid is False
    assert route.rejection is not None


async def test_a0_ignores_route_uncertainty_but_a1_does_not() -> None:
    case = short_sufficient()
    assert case is not None
    a0 = await run_experiment(
        case.plan,
        case.evidence,
        client=RouteClient(answerable=0.85, gap=0.05),
        config=A0,
    )
    a1 = await run_experiment(
        case.plan,
        case.evidence,
        client=RouteClient(answerable=0.85, gap=0.05),
        config=A1,
    )
    assert a0.draft.result == "sufficient"
    assert a1.draft.result == "insufficient"


async def test_a1_never_upgrades_a_failed_gate() -> None:
    case = short_sufficient()
    report = await run_experiment(
        case.plan,
        case.evidence,
        client=RouteClient(answerable=0.05, gap=0.95),
        config=A1,
    )
    assert report.draft.result == "insufficient"
