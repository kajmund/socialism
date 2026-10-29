"""A0 freeze: original live measurement, no assessment-rule changes."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from time import perf_counter

from app.config import settings
from app.jev.system import HttpJevSystemOne
from app.services.research.sufficiency_experiment.assessor import run_experiment
from app.services.research.sufficiency_experiment.baseline import (
    baseline_verdict,
    baseline_view,
)
from app.services.research.sufficiency_experiment.benchmark import (
    BenchmarkReport,
    CaseReport,
    _baseline_metrics,
    _experiment_metrics,
    _pr420,
)
from app.services.research.sufficiency_experiment.golden import (
    scripted_benchmark_cases,
)
from app.services.research.sufficiency_experiment.types import ExperimentConfig


class RecordingClient:
    def __init__(self) -> None:
        self._inner = HttpJevSystemOne()
        self.attempts: list[dict[str, object]] = []
        self.calls: list[dict[str, object]] = []
        self.errors: list[str] = []

    async def ask(self, *, state, questions, model, timeout_seconds):
        self.attempts.append({"model": model})
        try:
            result = await self._inner.ask(
                state=state,
                questions=questions,
                model=model,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            self.errors.append(type(exc).__name__)
            raise
        self.calls.append(
            {
                "model": result.model,
                "latency_ms": result.latency_ms,
                "input_chars": result.input_chars,
                "answers": result.answers,
            }
        )
        return result


async def run(rep: str) -> dict[str, object]:
    config = ExperimentConfig()
    rows = []
    raw_calls = []
    for case in scripted_benchmark_cases():
        client = RecordingClient()
        started = perf_counter()
        view = baseline_view(case.evidence)
        baseline_result = baseline_verdict(
            view, expected=case.expected, signal=case.signal
        )
        baseline_ms = (perf_counter() - started) * 1000
        report = await run_experiment(
            case.plan,
            case.evidence,
            client=client,
            config=config,
            live_measurement="live",
        )
        rows.append(
            CaseReport(
                case_id=case.case_id,
                expected=case.expected,
                baseline=_baseline_metrics(case, view, baseline_result, baseline_ms),
                experiment=_experiment_metrics(case, report),
            )
        )
        raw_calls.append(
            {
                "case_id": case.case_id,
                "attempts": len(client.attempts),
                "calls": client.calls,
                "errors": client.errors,
                "evaluations": len(report.evaluations),
                "evaluation_errors": [
                    row.job_id for row in report.evaluations if row.error
                ],
                "quality_reasons": list(report.quality.reasons),
                "quality": asdict(report.quality),
                "report_jev_calls": report.jev_calls,
            }
        )
    bench = BenchmarkReport(
        cases=tuple(rows),
        measurement="live",
        note="A0 freeze: original PR #422/#426 path, unchanged rules.",
        pr420=_pr420(),
    )
    models = sorted(
        {
            str(call["model"])
            for case in raw_calls
            for call in case["calls"]
        }
    )
    return {
        "freeze": "A0",
        "rep": rep,
        "recorded_at": datetime.now(UTC).isoformat(),
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "commit_short": subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip(),
        "config": asdict(config),
        "settings": {
            "jev_model": settings.jev_model,
            "research_jev_model": settings.research_jev_model,
            "typesafe_base_url": settings.typesafe_base_url,
            "jev_timeout_seconds": settings.jev_timeout_seconds,
            "research_jev_timeout_seconds": settings.research_jev_timeout_seconds,
            "llm_provider": settings.llm_provider,
        },
        "resolved_models": models,
        "summary": bench.summary(),
        "cases": [asdict(row) for row in rows],
        "raw_calls": raw_calls,
        "totals": {
            "jev_calls": sum(row.experiment.jev_calls for row in rows),
            "llm_calls": sum(row.experiment.llm_calls for row in rows),
            "attempts": sum(case["attempts"] for case in raw_calls),
            "client_calls": sum(len(case["calls"]) for case in raw_calls),
            "client_errors": sum(len(case["errors"]) for case in raw_calls),
            "latency_ms": round(
                sum(row.experiment.latency_ms for row in rows), 3
            ),
        },
    }


def main() -> int:
    out = sys.argv[1]
    payload = asyncio.run(run(out.rsplit("/", 1)[-1]))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "rep",
                    "commit_short",
                    "resolved_models",
                    "summary",
                    "totals",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
