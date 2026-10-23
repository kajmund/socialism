"""Re-run the four wrong B4c decisions with decision diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path

from app.jev.system import HttpJevSystemOne
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.research.sufficiency_experiment.golden import (
    compatible_entities,
    compatible_periods,
)
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.types import ExperimentConfig

DEFAULT_OUT = Path("tests/integration/baselines/b4c-wrong-decisions-v1.json")
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
    for case in (compatible_periods(), compatible_entities()):
        for rep in range(2):
            loop = SufficiencyLoop(
                case.plan,
                case.evidence,
                client=HttpJevSystemOne(),
                config=CONFIG,
            )
            loop.bind_embedding_provider(provider)
            await loop.run()
            report = loop.report
            if report is None or report.decision_diagnostics is None:
                continue
            rows.append(
                {
                    "case_id": case.case_id,
                    "rep": rep,
                    "expected": case.expected,
                    "draft": report.draft.result,
                    "status": report.status,
                    "quality_reasons": list(report.quality.reasons),
                    "coverage_complete": bool(
                        report.coverage_report and report.coverage_report.gate_complete
                    ),
                    "diagnostics": asdict(report.decision_diagnostics),
                    "pair_verdicts": [item.verdict for item in report.pairs],
                    "obligation_states": [
                        {
                            "kind": state.kind,
                            "verified": state.verified,
                            "independent_support": state.independent_support,
                        }
                        for state in report.aggregations[0].obligation_states
                    ],
                    "supporting_evidence_ids": list(
                        report.aggregations[0].supporting_evidence_ids
                    ),
                    "unresolved_conflicts": [
                        conflict.conflict_id
                        for row in report.aggregations
                        for conflict in row.conflicts
                        if conflict.status == "unresolved"
                    ],
                }
            )
    payload = {
        "measurement": "b4c_wrong_decisions",
        "note": "Decision diagnostics on the four false-insufficient compatible decisions.",
        "rows": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in rows:
        print(row["case_id"], "rep", row["rep"], row["status"], row["diagnostics"], row["quality_reasons"][:3])
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
