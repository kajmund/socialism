"""Compare the experiment to the PR #420 budgeted Cerebras baseline.

Scripted scores are closed-judge unit metrics. Live Jev/Cerebras are a
separate path and report `unavailable` when credentials are missing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from time import perf_counter

from app.jev.system import HttpJevSystemOne, JevSystemOne
from app.services.research.sufficiency_experiment.assessor import run_experiment
from app.services.research.sufficiency_experiment.baseline import (
    PR420_INPUT_CHARS_AFTER,
    PR420_INPUT_CHARS_BEFORE,
    PR420_MODEL,
    PR420_OUTPUT_CAP_TOKENS,
    baseline_verdict,
    baseline_view,
)
from app.services.research.sufficiency_experiment.golden import GoldenCase
from app.services.research.sufficiency_experiment.trace import case_trace
from app.services.research.sufficiency_experiment.types import ExperimentConfig, ExperimentReport


@dataclass(frozen=True)
class PathMetrics:
    result: str
    status: str
    accurate: bool
    false_sufficient: bool
    coverage: float
    latency_ms: float
    jev_calls: int
    llm_calls: int
    input_chars: int
    omitted_evidence: int


@dataclass(frozen=True)
class CaseReport:
    case_id: str
    expected: str
    baseline: PathMetrics
    experiment: PathMetrics
    trace: dict[str, object] | None = None


@dataclass(frozen=True)
class BenchmarkReport:
    cases: tuple[CaseReport, ...]
    measurement: str
    pr420: dict[str, object] = field(default_factory=dict)
    note: str = ""

    def summary(self) -> dict[str, object]:
        return {
            "measurement": self.measurement,
            "note": self.note,
            "accuracy": {
                "baseline": _accuracy(self.cases, "baseline"),
                "experiment": _accuracy(self.cases, "experiment"),
            },
            "false_sufficient_rate": {
                "baseline": _false_sufficient(self.cases, "baseline"),
                "experiment": _false_sufficient(self.cases, "experiment"),
            },
            "confusion": _confusion(self.cases),
            "coverage": {
                "baseline": _mean_coverage(self.cases, "baseline"),
                "experiment": _mean_coverage(self.cases, "experiment"),
            },
            "latency_ms": {
                "baseline": _mean_latency(self.cases, "baseline"),
                "experiment": _mean_latency(self.cases, "experiment"),
            },
            "cost": {
                "baseline": _cost(self.cases, "baseline"),
                "experiment": _cost(self.cases, "experiment"),
            },
            "pr420_cerebras_baseline": self.pr420,
            "cases": [case.case_id for case in self.cases],
        }


def live_keys_configured() -> bool:
    from app.config import settings

    return bool(settings.typesafe_api_key.strip()) and bool(settings.cerebras_api_key.strip())


def live_measurement_status() -> str:
    return "available" if live_keys_configured() else "unavailable"


async def run_benchmark(
    cases: Sequence[GoldenCase],
    *,
    client: JevSystemOne,
    config: ExperimentConfig | None = None,
    measurement: str = "scripted",
    include_trace: bool = False,
) -> BenchmarkReport:
    settings = config or ExperimentConfig()
    rows = [
        await _one(
            case,
            client,
            settings,
            measurement=measurement,
            include_trace=include_trace,
        )
        for case in cases
    ]
    return BenchmarkReport(
        cases=tuple(rows),
        measurement=measurement,
        note="scripted closed judge; not live Jev or Cerebras quality",
        pr420=_pr420(),
    )


async def measure_live_models(
    cases: Sequence[GoldenCase],
    *,
    config: ExperimentConfig | None = None,
    include_trace: bool = False,
) -> BenchmarkReport:
    """Judge the same golden evidence with live Jev passages and the live assessor.

    The baseline stays the PR #420 input window measured locally; it makes no
    model call, so it is labelled as the budgeted encoder, not a Cerebras run.
    """
    if not live_keys_configured():
        return BenchmarkReport(
            cases=(),
            measurement="unavailable",
            note="TYPESAFE_API_KEY and/or CEREBRAS_API_KEY missing; no live scores invented",
            pr420=_pr420(),
        )
    settings = config or ExperimentConfig()
    client = HttpJevSystemOne()
    rows = [
        await _one(case, client, settings, measurement="live", include_trace=include_trace)
        for case in cases
    ]
    return BenchmarkReport(
        cases=tuple(rows),
        measurement="live",
        note=(
            "live Jev passage scores (System One) + live assessor model; "
            "baseline is the PR #420 input window applied locally"
        ),
        pr420=_pr420(),
    )


async def _one(
    case: GoldenCase,
    client: JevSystemOne,
    config: ExperimentConfig,
    *,
    measurement: str,
    include_trace: bool,
) -> CaseReport:
    started = perf_counter()
    view = baseline_view(case.evidence)
    baseline_result = baseline_verdict(view, expected=case.expected, signal=case.signal)
    baseline_ms = (perf_counter() - started) * 1000
    report = await run_experiment(
        case.plan,
        case.evidence,
        client=client,
        config=config,
        live_measurement=measurement,
    )
    return CaseReport(
        case_id=case.case_id,
        expected=case.expected,
        baseline=_baseline_metrics(case, view, baseline_result, baseline_ms),
        experiment=_experiment_metrics(case, report),
        trace=case_trace(case, report, config) if include_trace else None,
    )


def _pr420() -> dict[str, object]:
    return {
        "model": PR420_MODEL,
        "input_chars_before": PR420_INPUT_CHARS_BEFORE,
        "input_chars_after": PR420_INPUT_CHARS_AFTER,
        "output_cap_tokens": PR420_OUTPUT_CAP_TOKENS,
    }


def _baseline_metrics(
    case: GoldenCase,
    view: object,
    result: str,
    latency_ms: float,
) -> PathMetrics:
    return PathMetrics(
        result=result,
        status=result,
        accurate=result == case.expected,
        false_sufficient=result == "sufficient" and case.expected == "insufficient",
        coverage=view.coverage,
        latency_ms=latency_ms,
        jev_calls=0,
        llm_calls=1,
        input_chars=view.encoded_chars,
        omitted_evidence=len(view.omitted_evidence_ids),
    )


def _experiment_metrics(case: GoldenCase, report: ExperimentReport) -> PathMetrics:
    result = report.draft.result
    return PathMetrics(
        result=result,
        status=report.status,
        accurate=result == case.expected,
        false_sufficient=result == "sufficient" and case.expected == "insufficient",
        coverage=report.coverage,
        latency_ms=report.latency_ms,
        jev_calls=report.jev_calls,
        llm_calls=report.llm_calls,
        input_chars=report.judged_chars,
        omitted_evidence=len(report.quality.omitted_evidence_ids),
    )


def _pick(case: CaseReport, path: str) -> PathMetrics:
    return case.baseline if path == "baseline" else case.experiment


def _accuracy(cases: Sequence[CaseReport], path: str) -> float:
    if not cases:
        return 1.0
    return sum(1 for case in cases if _pick(case, path).accurate) / len(cases)


def _false_sufficient(cases: Sequence[CaseReport], path: str) -> float:
    labeled = [case for case in cases if case.expected == "insufficient"]
    if not labeled:
        return 0.0
    return sum(1 for case in labeled if _pick(case, path).false_sufficient) / len(labeled)


def _mean_coverage(cases: Sequence[CaseReport], path: str) -> float:
    if not cases:
        return 1.0
    return sum(_pick(case, path).coverage for case in cases) / len(cases)


def _mean_latency(cases: Sequence[CaseReport], path: str) -> float:
    if not cases:
        return 0.0
    return sum(_pick(case, path).latency_ms for case in cases) / len(cases)


def _cost(cases: Sequence[CaseReport], path: str) -> dict[str, int]:
    return {
        "jev_calls": sum(_pick(case, path).jev_calls for case in cases),
        "llm_calls": sum(_pick(case, path).llm_calls for case in cases),
        "input_chars": sum(_pick(case, path).input_chars for case in cases),
    }


def _confusion(cases: Sequence[CaseReport]) -> dict[str, int]:
    matrix = {
        "true_sufficient": 0,
        "false_sufficient": 0,
        "true_insufficient": 0,
        "false_insufficient": 0,
    }
    for case in cases:
        predicted = case.experiment.result
        if case.expected == "sufficient" and predicted == "sufficient":
            matrix["true_sufficient"] += 1
        elif case.expected == "insufficient" and predicted == "sufficient":
            matrix["false_sufficient"] += 1
        elif case.expected == "insufficient" and predicted == "insufficient":
            matrix["true_insufficient"] += 1
        else:
            matrix["false_insufficient"] += 1
    return matrix
