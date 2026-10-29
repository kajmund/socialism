"""Cassette pairing and semantic/operational quality formulas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.jev.system import JevSystemOneResult, JevUsage
from app.services.research.sufficiency_experiment.arm_quality import (
    CaseOutcome,
    cost_metrics,
    operational_metrics,
    semantic_metrics,
)
from app.services.research.sufficiency_experiment.cassette import (
    CassetteJev,
    CassetteMissError,
    CassetteOrderError,
    RecordingJev,
    entry_key,
)


class StubJev:
    def __init__(self) -> None:
        self.calls = 0

    async def ask(self, *, state, questions, model, timeout_seconds):
        self.calls += 1
        return JevSystemOneResult(
            answers={"relation": {"choice": state["choice"]}},
            model="stub-1",
            latency_ms=1.5,
            input_chars=len(json.dumps(state)),
            usage=JevUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4),
            raw={},
        )


async def test_cassette_records_and_replays_in_order(tmp_path: Path) -> None:
    recorder = RecordingJev(StubJev())
    for choice in ("CONTRADICTS", "COMPATIBLE"):
        await recorder.ask(
            state={"choice": choice},
            questions={"relation": {"type": "choice"}},
            model="jev-latest",
            timeout_seconds=5.0,
        )
    path = tmp_path / "cassette.json"
    recorder.save(path, metadata={"commit": "abc"})
    replayed = CassetteJev.load(path)
    assert replayed.remaining == 2
    first = await replayed.ask(
        state={"choice": "CONTRADICTS"},
        questions={"relation": {"type": "choice"}},
        model="jev-latest",
        timeout_seconds=5.0,
    )
    assert first.answers["relation"]["choice"] == "CONTRADICTS"
    assert first.model == "stub-1"
    assert first.usage.total_tokens == 4
    assert replayed.remaining == 1


async def test_missing_entry_never_falls_back(tmp_path: Path) -> None:
    recorder = RecordingJev(StubJev())
    await recorder.ask(
        state={"choice": "CONTRADICTS"},
        questions={"relation": {}},
        model="jev-latest",
        timeout_seconds=5.0,
    )
    cassette = CassetteJev(recorder.entries)
    with pytest.raises(CassetteOrderError):
        await cassette.ask(
            state={"choice": "COMPATIBLE"},
            questions={"relation": {}},
            model="jev-latest",
            timeout_seconds=5.0,
        )
    cassette = CassetteJev(recorder.entries)
    with pytest.raises(CassetteOrderError):
        await cassette.ask(
            state={"choice": "CONTRADICTS"},
            questions={"relation": {}},
            model="other-model",
            timeout_seconds=5.0,
        )
    empty = CassetteJev([])
    with pytest.raises(CassetteMissError):
        await empty.ask(
            state={},
            questions={},
            model="jev-latest",
            timeout_seconds=5.0,
        )


def test_entry_key_covers_questions_state_and_model() -> None:
    base = entry_key(questions={"q": 1}, state={"s": 1}, model="m")
    assert base == entry_key(questions={"q": 1}, state={"s": 1}, model="m")
    assert base != entry_key(questions={"q": 2}, state={"s": 1}, model="m")
    assert base != entry_key(questions={"q": 1}, state={"s": 2}, model="m")
    assert base != entry_key(questions={"q": 1}, state={"s": 1}, model="m2")


def _outcomes() -> list[CaseOutcome]:
    return [
        CaseOutcome("a", 0, "sufficient", "sufficient", jev_calls=2),
        CaseOutcome("b", 0, "insufficient", "sufficient", jev_calls=2),
        CaseOutcome(
            "c",
            0,
            "insufficient",
            "insufficient",
            technical_failure=True,
            failure_reasons=("timeout",),
            jev_calls=1,
        ),
        CaseOutcome(
            "d",
            0,
            "insufficient",
            "sufficient",
            technical_failure=True,
            jev_calls=1,
        ),
    ]


def test_semantic_metrics_exclude_technical_failures() -> None:
    metrics = semantic_metrics(_outcomes())
    assert metrics["clean_runs"] == 2
    assert metrics["excluded_runs"] == 2
    assert metrics["accuracy"] == 0.5
    assert metrics["false_sufficient"] == 1.0
    assert metrics["false_insufficient"] == 0.0


def test_operational_metrics_keep_failures_visible() -> None:
    metrics = operational_metrics(_outcomes())
    assert metrics["runs"] == 4
    assert metrics["raw_accuracy"] == 0.5
    assert metrics["operational_success"] == 0.25
    assert metrics["technical_failure_rate"] == 0.5
    assert metrics["sufficient_on_failed_call"] == 1
    assert metrics["failure_reasons"] == {"timeout": 1, "unspecified": 1}


def test_verdict_stability_flags_unexplained_differences() -> None:
    rows = [
        CaseOutcome("a", 0, "insufficient", "sufficient"),
        CaseOutcome("a", 1, "insufficient", "insufficient"),
        CaseOutcome("b", 0, "insufficient", "sufficient"),
        CaseOutcome(
            "b", 1, "insufficient", "insufficient", technical_failure=True
        ),
    ]
    stability = operational_metrics(rows)["verdict_stability"]
    assert stability["unstable_cases"] == ["a", "b"]
    assert stability["unstable_unexplained"] == ["a"]


def test_cost_metrics_use_clean_detections() -> None:
    rows = [
        CaseOutcome(
            "a", 0, "insufficient", "insufficient", true_positive_conflict=True, jev_calls=10
        ),
        CaseOutcome(
            "b",
            0,
            "insufficient",
            "insufficient",
            technical_failure=True,
            true_positive_conflict=True,
            jev_calls=10,
        ),
    ]
    metrics = cost_metrics(rows)
    assert metrics["jev_calls"] == 20
    assert metrics["detected_contradictions"] == 1
    assert metrics["cost_per_detected_contradiction"] == 20.0
    assert metrics["cost_per_correct_decision"] == 20.0
