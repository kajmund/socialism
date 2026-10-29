"""Existential mode stops after a verified blocking conflict without becoming sufficient."""

from __future__ import annotations

from dataclasses import replace

from app.services.research.sufficiency_experiment.golden import tail_claim_contradiction
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.scripted import (
    ScriptedSufficiencyJev,
)
from app.services.research.sufficiency_experiment.types import ExperimentConfig


async def test_existential_mode_is_partial_and_never_sufficient() -> None:
    case = tail_claim_contradiction()
    config = replace(
        ExperimentConfig(),
        stop_mode="existential",
        pair_jev_concurrency=1,
    )
    loop = SufficiencyLoop(
        case.plan,
        case.evidence,
        client=ScriptedSufficiencyJev(),
        config=config,
    )
    await loop.run()
    report = loop.report
    assert report is not None
    outcome = report.stop_outcome
    assert outcome.goal == "EXISTS_BLOCKING_CONFLICT"
    assert outcome.result == "CONFLICT_FOUND"
    assert outcome.investigation_status == "PARTIAL"
    assert report.draft.result == "insufficient"
    assert loop._pair_calls_skipped > 0
    skipped = [
        pair for pair in report.pairs if pair.error == "stop_condition_met"
    ]
    assert skipped
