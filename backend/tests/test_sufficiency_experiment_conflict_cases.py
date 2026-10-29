"""Conflict golden cases through the whole SWE workflow, not just aggregation."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.jev.system import parse_noul
from app.services.research.assessment import AssessableEvidence
from app.services.research.evidence_screen import EVIDENCE_SCREEN_QUESTIONS
from app.services.research.sufficiency_experiment.assessor import run_experiment
from app.services.research.sufficiency_experiment.golden import (
    GoldenCase,
    all_golden_cases,
    compatible_entities,
    compatible_periods,
    conflict_benchmark_cases,
    pair_over_budget,
    scripted_benchmark_cases,
)
from app.services.research.sufficiency_experiment.scripted import (
    ScriptedSufficiencyJev,
)


async def _run(
    case: GoldenCase,
    evidence: tuple[AssessableEvidence, ...] | None = None,
):
    return await run_experiment(
        case.plan,
        evidence or case.evidence,
        client=ScriptedSufficiencyJev(),
        counterparts=case.counterparts,
    )


def _conflicts(report: Any) -> list[Any]:
    return [conflict for row in report.aggregations for conflict in row.conflicts]


async def test_conflict_matrix_through_the_workflow() -> None:
    expectations = {
        "duplicate_contradiction": ("insufficient", "uncertain", {"unresolved"}),
        "independent_contradiction": ("insufficient", "uncertain", {"unresolved"}),
        "compatible_periods": ("sufficient", "sufficient", {"not_applicable"}),
        "compatible_entities": ("sufficient", "sufficient", {"not_applicable"}),
        "unknown_counterpart": ("insufficient", "uncertain", {"unresolved"}),
    }
    cases = {case.case_id: case for case in conflict_benchmark_cases()}
    assert set(cases) == set(expectations)
    for case_id, (result, status, conflict_status) in expectations.items():
        report = await _run(cases[case_id])
        assert report.draft.result == result, case_id
        assert report.status == status, case_id
        assert {
            conflict.status for conflict in _conflicts(report)
        } == conflict_status, case_id


async def test_period_resolution_needs_verifiable_metadata() -> None:
    case = compatible_periods()
    missing = tuple(
        replace(item, provenance={}) if item.evidence_id == "period-old" else item
        for item in case.evidence
    )
    report = await _run(case, missing)
    assert _conflicts(report)[0].status == "unresolved"
    assert report.draft.result == "insufficient"

    overlapping = (
        replace(
            case.evidence[0],
            provenance={
                "valid_from": "2024-01-01",
                "valid_to": "2027-12-31",
                "entity_id": "avtal-period",
            },
        ),
        replace(
            case.evidence[1],
            provenance={
                "valid_from": "2026-01-01",
                "valid_to": "2028-12-31",
                "entity_id": "avtal-period",
            },
        ),
    )
    report = await _run(case, overlapping)
    assert _conflicts(report)[0].status == "unresolved"
    assert report.draft.result == "insufficient"


async def test_entity_resolution_needs_verifiable_metadata() -> None:
    case = compatible_entities()
    missing = tuple(
        replace(item, provenance={}) if item.evidence_id == "entity-a" else item
        for item in case.evidence
    )
    report = await _run(case, missing)
    assert _conflicts(report)[0].status == "unresolved"

    same_entity = tuple(
        replace(item, provenance={"entity_id": "avtal-a"}) for item in case.evidence
    )
    report = await _run(case, same_entity)
    assert _conflicts(report)[0].status == "unresolved"


async def test_unknown_counterpart_is_never_invented() -> None:
    case = next(c for c in conflict_benchmark_cases() if c.case_id == "unknown_counterpart")
    report = await _run(case)
    conflict = _conflicts(report)[0]
    assert conflict.status == "unresolved"
    assert conflict.has_unknown_counterpart is True
    evidence_ids = {item.evidence_id for item in case.evidence}
    assert {side.evidence_id for side in conflict.sides} <= evidence_ids
    assert report.quality.allows_sufficient is False
    assert report.draft.result == "insufficient"


def test_pair_over_budget_is_defined_but_not_an_a2_case() -> None:
    case = pair_over_budget()
    assert case.expected == "insufficient"
    assert case.expected_status == "uncertain"
    assert case.case_id not in {item.case_id for item in conflict_benchmark_cases()}
    assert case.case_id in {item.case_id for item in all_golden_cases()}


def test_benchmark_sets_stay_separate() -> None:
    assert [case.case_id for case in scripted_benchmark_cases()] == [
        "tail_counterevidence",
        "late_evidence",
        "large_567k",
        "short_sufficient",
    ]
    assert len(all_golden_cases()) == 18
    ids = [case.case_id for case in all_golden_cases()]
    assert len(ids) == len(set(ids))


async def test_scripted_overrides_are_fixture_data() -> None:
    client = ScriptedSufficiencyJev()
    result = await client.ask(
        state={"evidence_id": "dup-contra", "passage": "irrelevant"},
        questions=EVIDENCE_SCREEN_QUESTIONS,
        model="scripted-jev",
        timeout_seconds=1.0,
    )
    assert parse_noul(result.answers, "likely_duplicate_or_redundant") == 0.89
    result = await client.ask(
        state={"evidence_id": "period-new", "passage": "irrelevant"},
        questions=EVIDENCE_SCREEN_QUESTIONS,
        model="scripted-jev",
        timeout_seconds=1.0,
    )
    assert parse_noul(result.answers, "contradicts_current_evidence") == 0.95
