"""Ticket 30: exhaustive vs existential execution on the frozen cases."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path

from app.jev.system import HttpJevSystemOne
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.research.sufficiency_experiment.gap_cases import (
    candidate_miss_synonyms,
    synonym_contradiction_notice,
    synonym_contradiction_semester,
)
from app.services.research.sufficiency_experiment.golden import (
    duplicate_contradiction,
    independent_contradiction,
    late_evidence,
    tail_claim_contradiction,
    tail_counterevidence,
)
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.types import ExperimentConfig

DEFAULT_OUT = Path("tests/integration/baselines/early-stop-v1.json")
CASES = (
    tail_counterevidence(),
    late_evidence(),
    duplicate_contradiction(),
    independent_contradiction(),
    tail_claim_contradiction(),
    candidate_miss_synonyms(),
    synonym_contradiction_semester(),
    synonym_contradiction_notice(),
)
BASE = replace(
    ExperimentConfig(),
    route_authority=True,
    legacy_duplicate_resolution=False,
    pair_judgement=True,
    pair_strategy="hybrid",
    pair_ordering="metadata",
)


async def _run(mode: str, reps: int) -> dict:
    config = replace(BASE, stop_mode=mode)
    provider = OpenAIEmbeddingProvider.from_settings()
    rows = []
    for rep in range(reps):
        for case in CASES:
            loop = SufficiencyLoop(case.plan, case.evidence, client=HttpJevSystemOne(), config=config)
            loop.bind_embedding_provider(provider)
            await loop.run()
            report = loop.report
            if report is None:
                continue
            stop = report.stop_outcome
            rows.append(
                {
                    "mode": mode,
                    "rep": rep,
                    "case_id": case.case_id,
                    "expected": case.expected,
                    "draft": report.draft.result,
                    "status": report.status,
                    "correct": report.draft.result == case.expected,
                    "false_sufficient": report.draft.result == "sufficient" and case.expected == "insufficient",
                    "jev_calls": report.jev_calls,
                    "latency_ms": report.latency_ms,
                    "selected_pairs": len(report.pair_selection.selected) if report.pair_selection else 0,
                    "evaluated_pairs": sum(1 for pair in report.pairs if pair.status != "unevaluated"),
                    "skipped_pairs": sum(1 for pair in report.pairs if pair.error == "stop_condition_met"),
                    "started_pairs": loop._pair_calls_started,
                    "in_flight_at_stop": loop._pair_in_flight_at_stop,
                    "stop": asdict(stop),
                    "stop_blocking": bool(report.stop_shadow.blocking),
                    "diagnostics": list(report.decision_diagnostics.reasons),
                }
            )
    totals = {
        "runs": len(rows),
        "correct": sum(row["correct"] for row in rows),
        "false_sufficient": sum(row["false_sufficient"] for row in rows),
        "jev_calls": sum(row["jev_calls"] for row in rows),
        "latency_ms": round(sum(row["latency_ms"] for row in rows), 1),
        "evaluated_pairs": sum(row["evaluated_pairs"] for row in rows),
        "skipped_pairs": sum(row["skipped_pairs"] for row in rows),
        "in_flight_at_stop": sum(row["in_flight_at_stop"] for row in rows),
        "partial_runs": sum(row["stop"]["investigation_status"] == "PARTIAL" for row in rows),
        "invalid_stops": sum(
            row["skipped_pairs"] > 0 and not row["stop_blocking"] for row in rows
        ),
        "sufficient_presented_as_partial": sum(
            row["draft"] == "sufficient" and row["stop"]["investigation_status"] == "PARTIAL"
            for row in rows
        ),
    }
    return {"config": asdict(config), "rows": rows, "totals": totals}


async def _main(out: Path, reps: int) -> dict:
    exhaustive = await _run("exhaustive", reps)
    existential = await _run("existential", reps)
    payload = {
        "measurement": "early_stop",
        "note": "Exhaustive vs existential (verified blocking conflict) with D config; production behavior unchanged.",
        "reps": reps,
        "arms": {"exhaustive": exhaustive, "existential": existential},
        "actual_avoided_calls": exhaustive["totals"]["jev_calls"]
        - existential["totals"]["jev_calls"],
        "wall_time_delta_ms": round(
            exhaustive["totals"]["latency_ms"] - existential["totals"]["latency_ms"], 1
        ),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"exhaustive": exhaustive["totals"], "existential": existential["totals"]}, indent=2))
    print("actual_avoided_calls", payload["actual_avoided_calls"], "wall_delta_ms", payload["wall_time_delta_ms"])
    print(f"wrote {out}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--reps", type=int, default=2)
    args = parser.parse_args()
    asyncio.run(_main(args.out, args.reps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
