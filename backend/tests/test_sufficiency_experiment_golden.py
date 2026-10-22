"""Golden cases vs the PR #420 budgeted Cerebras baseline. Scripted only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.research.assessment_input import ASSESSMENT_MAX_INPUT_CHARS
from app.services.research.sufficiency_experiment.assessor import run_experiment
from app.services.research.sufficiency_experiment.baseline import (
    PR420_INPUT_CHARS_AFTER,
    PR420_INPUT_CHARS_BEFORE,
    baseline_view,
)
from app.services.research.sufficiency_experiment.benchmark import run_benchmark
from app.services.research.sufficiency_experiment.golden import (
    CONTRADICTION_SIGNAL,
    large_567k,
    late_evidence,
    scripted_benchmark_cases,
    tail_counterevidence,
)
from app.services.research.sufficiency_experiment.scripted import ScriptedSufficiencyJev

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "sufficiency_experiment"
    / "pr420_cerebras_baseline.json"
)

@pytest.mark.asyncio
async def test_experiment_judges_complete_golden_cases() -> None:
    client = ScriptedSufficiencyJev()
    for case in scripted_benchmark_cases():
        report = await run_experiment(
            case.plan, case.evidence, client=client, live_measurement="scripted"
        )
        assert report.draft.result == case.expected, case.case_id
        assert report.status == case.expected_status, case.case_id
        assert report.live_measurement == "scripted"


@pytest.mark.asyncio
async def test_tail_and_late_signals_are_visible_only_to_the_experiment() -> None:
    for case in (tail_counterevidence(), late_evidence(), large_567k()):
        view = baseline_view(case.evidence)
        assert view.truncated or not view.contains(CONTRADICTION_SIGNAL)
        assert not view.contains(CONTRADICTION_SIGNAL)
        report = await run_experiment(
            case.plan, case.evidence, client=ScriptedSufficiencyJev()
        )
        assert report.coverage == 1.0
        assert report.draft.result == "insufficient"
        assert report.status == "uncertain"
        assert any(CONTRADICTION_SIGNAL in item.text for item in report.passages)


@pytest.mark.asyncio
async def test_scripted_benchmark_is_labeled_scripted() -> None:
    report = await run_benchmark(
        scripted_benchmark_cases(),
        client=ScriptedSufficiencyJev(),
        measurement="scripted",
    )
    summary = report.summary()
    assert summary["measurement"] == "scripted"
    assert "not live" in summary["note"]
    assert summary["accuracy"]["experiment"] == 1.0
    assert summary["false_sufficient_rate"]["experiment"] == 0.0
    assert summary["false_sufficient_rate"]["baseline"] > 0.0
    assert summary["coverage"]["experiment"] == 1.0
    assert summary["coverage"]["baseline"] < 1.0
    assert summary["pr420_cerebras_baseline"]["input_chars_before"] == PR420_INPUT_CHARS_BEFORE
    assert summary["pr420_cerebras_baseline"]["input_chars_after"] == PR420_INPUT_CHARS_AFTER
    published = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert published["input_chars_before"] == PR420_INPUT_CHARS_BEFORE
    large = next(case for case in report.cases if case.case_id == "large_567k")
    assert large.baseline.input_chars <= ASSESSMENT_MAX_INPUT_CHARS
    assert large.experiment.coverage == 1.0
    assert large.baseline.false_sufficient
    assert large.experiment.status == "uncertain"


def test_late_evidence_is_omitted_by_the_pr420_budget() -> None:
    view = baseline_view(late_evidence().evidence)
    assert "evidence-48" in view.omitted_evidence_ids
    assert not view.contains(CONTRADICTION_SIGNAL)
