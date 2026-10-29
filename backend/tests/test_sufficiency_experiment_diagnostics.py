"""Decision diagnostics are additive reasons, not a new final contract."""

from __future__ import annotations

from app.services.research.sufficiency_experiment.golden import (
    duplicate_contradiction,
    no_support,
    short_sufficient,
    tail_claim_contradiction,
)
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.scripted import (
    ScriptedSufficiencyJev,
)
from app.services.research.sufficiency_experiment.types import ExperimentConfig


async def _report(case):
    loop = SufficiencyLoop(
        case.plan,
        case.evidence,
        client=ScriptedSufficiencyJev(),
        config=ExperimentConfig(),
    )
    await loop.run()
    assert loop.report is not None
    return loop.report


async def test_sufficient_diagnostic() -> None:
    report = await _report(short_sufficient())
    assert report.status == "sufficient"
    assert report.decision_diagnostics is not None
    assert report.decision_diagnostics.reasons == ("SUFFICIENT",)


async def test_support_incomplete_diagnostic() -> None:
    report = await _report(no_support())
    assert report.status in {"insufficient", "uncertain"}
    assert report.decision_diagnostics is not None
    assert "SUPPORT_INCOMPLETE" in report.decision_diagnostics.reasons


async def test_conflict_diagnostic_keeps_reason() -> None:
    report = await _report(duplicate_contradiction())
    assert report.decision_diagnostics is not None
    assert "CONTRADICTION_FOUND" in report.decision_diagnostics.reasons
    assert report.decision_diagnostics.unique_conflicts


async def test_coverage_and_conflict_can_coexist() -> None:
    report = await _report(tail_claim_contradiction())
    assert report.decision_diagnostics is not None
    reasons = set(report.decision_diagnostics.reasons)
    assert "CONTRADICTION_FOUND" in reasons
    assert "COVERAGE_INCOMPLETE" in reasons
