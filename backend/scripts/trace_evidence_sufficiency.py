"""Trace the live sufficiency experiment pass by pass.

The metrics artifact keeps only verdicts and counts. This writes the full
evidence chain: which passages were judged, what Jev scored, which obligations
verified, which gate reasons fired and which route was chosen.

Run from `backend/` with TYPESAFE_API_KEY and CEREBRAS_API_KEY configured.
Nothing is invented when the keys are missing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from app.services.research.sufficiency_experiment.benchmark import (
    CaseReport,
    measure_live_models,
)
from app.services.research.sufficiency_experiment.golden import (
    GoldenCase,
    scripted_benchmark_cases,
)


def _select(
    cases: Sequence[GoldenCase],
    wanted: Sequence[str] | None,
) -> tuple[GoldenCase, ...]:
    if not wanted:
        return tuple(cases)
    by_id = {case.case_id: case for case in cases}
    unknown = sorted(set(wanted) - set(by_id))
    if unknown:
        raise SystemExit(f"unknown cases {unknown}; known {sorted(by_id)}")
    return tuple(by_id[case_id] for case_id in wanted)


def _summary_line(case: CaseReport) -> str:
    trace = case.trace or {}
    verdict = trace.get("verdict", {})
    signal_passages = trace.get("signal_passages", [])
    contradiction_passages = trace.get("contradiction_passages", [])
    return (
        f"{case.case_id}: {case.experiment.result} "
        f"signal_passages={len(signal_passages)} "
        f"contradiction_passages={len(contradiction_passages)} "
        f"llm_calls={verdict.get('llm_calls')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", nargs="*", default=None)
    args = parser.parse_args()
    report = asyncio.run(
        measure_live_models(
            _select(scripted_benchmark_cases(), args.cases),
            include_trace=True,
        )
    )
    if report.measurement != "live":
        print(report.note)
        return 1
    payload = {
        "measurement": report.measurement,
        "note": report.note,
        "summary": report.summary(),
        "cases": [asdict(case) for case in report.cases],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    for case in report.cases:
        print(_summary_line(case))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
