"""Shadow measurement of potential conflict-confirmed stop points. No execution change."""

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

DEFAULT_OUT = Path("tests/integration/baselines/stop-shadow-v1.json")
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
CONFIG = replace(
    ExperimentConfig(),
    route_authority=True,
    legacy_duplicate_resolution=False,
    pair_judgement=True,
    pair_strategy="hybrid",
    pair_ordering="metadata",
)


async def _run(out: Path) -> dict:
    provider = OpenAIEmbeddingProvider.from_settings()
    rows = []
    for case in CASES:
        for rep in range(2):
            loop = SufficiencyLoop(case.plan, case.evidence, client=HttpJevSystemOne(), config=CONFIG)
            loop.bind_embedding_provider(provider)
            await loop.run()
            report = loop.report
            if report is None or report.stop_shadow is None:
                continue
            rows.append(
                {
                    "case_id": case.case_id,
                    "rep": rep,
                    "draft": report.draft.result,
                    "status": report.status,
                    "jev_calls": report.jev_calls,
                    "diagnostics": asdict(report.decision_diagnostics),
                    "stop": asdict(report.stop_shadow),
                }
            )
    would_stop = [row for row in rows if row["stop"]["would_stop"]]
    payload = {
        "measurement": "stop_shadow",
        "note": "Shadow only: potential conflict-confirmed stops; execution and final verdicts unchanged.",
        "rows": rows,
        "summary": {
            "cases": len(rows),
            "would_stop": len(would_stop),
            "estimated_calls_saved": sum(row["stop"]["estimated_calls_saved"] for row in would_stop),
            "estimated_latency_saved_ms": round(sum(row["stop"]["estimated_latency_saved_ms"] for row in would_stop), 1),
            "coverage_incomplete_at_stop": sum(not row["stop"]["coverage_complete"] for row in would_stop),
            "stops_with_coverage_complete": sum(row["stop"]["coverage_complete"] for row in would_stop),
        },
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    for row in rows:
        print(row["case_id"], row["rep"], row["stop"])
    print(f"wrote {out}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    asyncio.run(_run(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
