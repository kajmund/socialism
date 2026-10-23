"""Shadow stop points are recorded but never change execution."""

from __future__ import annotations

from app.services.research.sufficiency_experiment.golden import duplicate_contradiction
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.scripted import (
    ScriptedSufficiencyJev,
)
from app.services.research.sufficiency_experiment.types import ExperimentConfig


async def test_conflict_shadow_stop_is_recorded_without_authority() -> None:
    case = duplicate_contradiction()
    loop = SufficiencyLoop(
        case.plan,
        case.evidence,
        client=ScriptedSufficiencyJev(),
        config=ExperimentConfig(),
    )
    await loop.run()
    assert loop.report is not None
    shadow = loop.report.stop_shadow
    assert shadow is not None
    assert shadow.condition == "conflict_confirmed"
    assert shadow.pair_verdict == "CONTRADICTS"
    assert shadow.would_stop is True
    assert shadow.blocking is True
    assert shadow.conflict_id is not None
    assert loop.report.draft.result == "insufficient"
