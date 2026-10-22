"""Counterfactual A2 replay over a frozen live trace.

The live screen never flags the planted contradictions, so the resolved/
unresolved behaviour cannot be observed by re-running the experiment. This
rebuilds the measured evaluations, forces the signal passages to a
contradiction score, and re-runs aggregation, conflict records and the gate.
Duplicate scores stay exactly as measured.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.services.research.sufficiency_experiment.golden import (
    scripted_benchmark_cases,
)
from app.services.research.sufficiency_experiment.replay import replay_case

DEFAULT_TRACE = Path("tests/integration/baselines/sufficiency-contradiction-trace-v1.json")
DEFAULT_OUT = Path("tests/integration/baselines/sufficiency-conflict-replay-v1.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--contradiction-score", type=float, default=0.95)
    args = parser.parse_args()
    raw = args.trace.read_bytes()
    trace = json.loads(raw)
    cases = {case.case_id: case for case in scripted_benchmark_cases()}
    rows = [
        replay_case(
            cases[case["case_id"]],
            case["trace"],
            contradiction_score=args.contradiction_score,
            force=cases[case["case_id"]].expected == "insufficient",
        )
        for case in trace["cases"]
    ]
    payload = {
        "measurement": "counterfactual_replay",
        "note": (
            "Frozen live scores with each trap's signal passage forced to a "
            "contradiction; duplicate scores are unchanged. Not a live run."
        ),
        "source_trace": str(args.trace),
        "source_trace_sha256": hashlib.sha256(raw).hexdigest(),
        "forced_contradiction_score": args.contradiction_score,
        "cases": rows,
    }
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for row in rows:
        print(
            f"{row['case_id']}: {row['draft_result']} "
            f"status={row['status']} unresolved={len(row['unresolved_conflicts'])} "
            f"duplicate={row['duplicate_scores']}"
        )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
