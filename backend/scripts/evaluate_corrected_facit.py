"""Evaluate D against versioned facit v2. Historical B4c numbers are untouched."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.jev.system import HttpJevSystemOne
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.research.sufficiency_experiment.facit_qa import load_facit
from app.services.research.sufficiency_experiment.gap_cases import (
    candidate_miss_synonyms,
    notice_compatible_entities,
    notice_compatible_periods,
    synonym_contradiction_notice,
    synonym_contradiction_semester,
)
from app.services.research.sufficiency_experiment.golden import (
    all_golden_cases,
    conflict_benchmark_cases,
    scripted_benchmark_cases,
    tail_claim_contradiction,
)
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.types import ExperimentConfig

DEFAULT_OUT = Path("tests/integration/baselines/facit-v2-d-evaluation.json")
FACIT = Path("tests/integration/baselines/golden-facit-v2.json")
CONFIG = replace(
    ExperimentConfig(),
    route_authority=True,
    legacy_duplicate_resolution=False,
    pair_judgement=True,
    pair_strategy="hybrid",
    pair_ordering="metadata",
)


async def _run(out: Path, reps: int) -> dict:
    entries = {case.case_id: case for case in load_facit(FACIT)}
    cases = {case.case_id: case for case in all_golden_cases()}
    cases.update({case.case_id: case for case in scripted_benchmark_cases()})
    cases.update({case.case_id: case for case in conflict_benchmark_cases()})
    cases.update(
        {
            case.case_id: case
            for case in (
                tail_claim_contradiction(),
                candidate_miss_synonyms(),
                synonym_contradiction_semester(),
                synonym_contradiction_notice(),
                notice_compatible_periods(),
                notice_compatible_entities(),
            )
        }
    )
    provider = OpenAIEmbeddingProvider.from_settings()
    rows = []
    selected = [
        case_id
        for case_id, facit in entries.items()
        if facit.status == "valid" and case_id in cases
    ]
    for rep in range(reps):
        for case_id in selected:
            case = cases[case_id]
            facit = entries[case_id]
            loop = SufficiencyLoop(case.plan, case.evidence, client=HttpJevSystemOne(), config=CONFIG)
            loop.bind_embedding_provider(provider)
            await loop.run()
            report = loop.report
            if report is None:
                continue
            rows.append(
                {
                    "case_id": case_id,
                    "rep": rep,
                    "expected": facit.expected_decision,
                    "draft": report.draft.result,
                    "status": report.status,
                    "correct": report.draft.result == facit.expected_decision,
                    "false_sufficient": report.draft.result == "sufficient" and facit.expected_decision == "insufficient",
                    "false_insufficient": report.draft.result == "insufficient" and facit.expected_decision == "sufficient",
                    "coverage_complete": bool(report.coverage_report and report.coverage_report.gate_complete),
                    "diagnostics": list(report.decision_diagnostics.reasons),
                }
            )
    payload = {
        "measurement": "facit_v2_d_evaluation",
        "recorded_at": datetime.now(UTC).isoformat(),
        "facit": str(FACIT),
        "facit_version": "v2",
        "note": "New D run against v2. Historical B4c v1 numbers are preserved and not rewritten.",
        "cases": selected,
        "reps": reps,
        "correct": sum(row["correct"] for row in rows),
        "runs": len(rows),
        "false_sufficient": sum(row["false_sufficient"] for row in rows),
        "false_insufficient": sum(row["false_insufficient"] for row in rows),
        "rows": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("runs", "correct", "false_sufficient", "false_insufficient")}, indent=2))
    for row in rows:
        if not row["correct"]:
            print("WRONG", row["case_id"], row["rep"], row["draft"], row["expected"], row["diagnostics"])
    print(f"wrote {out}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--reps", type=int, default=2)
    args = parser.parse_args()
    asyncio.run(_run(args.out, args.reps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
