"""Five coverage levels, explicit controls, no combined percentage."""

from __future__ import annotations

from dataclasses import replace

from app.services.research.sufficiency_experiment.assessor import run_experiment
from app.services.research.sufficiency_experiment.coverage import LEVELS
from app.services.research.sufficiency_experiment.golden import (
    adversarial_empty,
    compatible_periods,
    duplicate_contradiction,
    short_sufficient,
)
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.scripted import ScriptedSufficiencyJev
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    PairFacit,
)

PAIR = "dup-contra:p0:c0|dup-support:p0:c0"


def _levels(report):
    assert report.coverage_report is not None
    return {level.level: level for level in report.coverage_report.levels}


async def test_report_keeps_the_five_levels_separate() -> None:
    case = compatible_periods()
    report = await run_experiment(
        case.plan,
        case.evidence,
        client=ScriptedSufficiencyJev(),
        counterparts=case.counterparts,
    )
    levels = _levels(report)
    assert tuple(levels) == LEVELS
    assert report.coverage_report is not None
    assert not hasattr(report.coverage_report, "score")
    assert levels["narrative"].status == "not_applicable"


async def test_ingestion_is_incomplete_on_found_without_excerpt() -> None:
    case = adversarial_empty()
    report = await run_experiment(
        case.plan, case.evidence, client=ScriptedSufficiencyJev()
    )
    level = _levels(report)["ingestion"]
    assert level.status == "incomplete"
    assert level.reasons == ("found_without_excerpt",)
    assert "coverage_incomplete" in report.quality.reasons


async def test_claim_is_incomplete_when_the_budget_truncates() -> None:
    case = short_sufficient()
    config = replace(ExperimentConfig(), max_claims_per_need=0)
    report = await run_experiment(
        case.plan, case.evidence, client=ScriptedSufficiencyJev(), config=config
    )
    level = _levels(report)["claim"]
    assert level.status == "incomplete"
    assert dict(level.counts)["unprocessed"] == 1
    assert "coverage_incomplete" in report.quality.reasons


async def test_conflict_is_not_measured_without_a_facit() -> None:
    case = compatible_periods()
    report = await run_experiment(
        case.plan,
        case.evidence,
        client=ScriptedSufficiencyJev(),
        counterparts=case.counterparts,
    )
    level = _levels(report)["conflict_candidate"]
    assert level.status == "not_measured"
    assert level.control == "process"
    assert level.gate_complete is True
    assert report.coverage_report is not None
    assert report.coverage_report.gate_complete is True


async def test_pair_budget_without_facit_is_incomplete_and_gates() -> None:
    case = duplicate_contradiction()
    config = replace(ExperimentConfig(), max_pairs_per_need=0)
    report = await run_experiment(
        case.plan, case.evidence, client=ScriptedSufficiencyJev(), config=config
    )
    level = _levels(report)["conflict_candidate"]
    assert level.status == "incomplete"
    assert "pair_budget_omitted" in level.reasons
    assert "coverage_incomplete" in report.quality.reasons


async def _run_with_facit(case, facit: PairFacit, config: ExperimentConfig | None = None):
    loop = SufficiencyLoop(
        case.plan,
        case.evidence,
        client=ScriptedSufficiencyJev(),
        config=config or ExperimentConfig(),
    )
    loop.bind_pair_facit(facit)
    await loop.run()
    assert loop.report is not None
    return loop.report


async def test_missed_facit_pair_blocks_sufficient() -> None:
    case = duplicate_contradiction()
    config = replace(ExperimentConfig(), max_pairs_per_need=0)
    report = await _run_with_facit(
        case,
        PairFacit(candidate_pairs=(PAIR,), contradiction_pairs=(PAIR,)),
        config,
    )
    level = _levels(report)["conflict_candidate"]
    assert level.status == "incomplete"
    assert level.control == "process_and_facit"
    assert "facit_pair_missing" in level.reasons
    assert "coverage_incomplete" in report.quality.reasons
    assert report.draft.result == "insufficient"


async def test_found_facit_pair_is_complete_coverage() -> None:
    case = duplicate_contradiction()
    report = await _run_with_facit(
        case,
        PairFacit(candidate_pairs=(PAIR,), contradiction_pairs=(PAIR,)),
    )
    level = _levels(report)["conflict_candidate"]
    assert level.status == "complete"
    assert dict(level.counts)["facit_missing"] == 0
    assert report.coverage_report is not None
    assert report.coverage_report.gate_complete is True
    assert report.draft.result == "insufficient"
