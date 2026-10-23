"""Verify whether the remaining four errors are support bugs or off-topic fixtures."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path

from app.jev.system import HttpJevSystemOne
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.research.sufficiency_experiment.gap_cases import (
    notice_compatible_entities,
    notice_compatible_periods,
)
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.types import ExperimentConfig

DEFAULT_OUT = Path("tests/integration/baselines/support-on-topic-v1.json")
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
    for case in (notice_compatible_periods(), notice_compatible_entities()):
        for rep in range(2):
            loop = SufficiencyLoop(case.plan, case.evidence, client=HttpJevSystemOne(), config=CONFIG)
            loop.bind_embedding_provider(provider)
            await loop.run()
            report = loop.report
            if report is None:
                continue
            rows.append(
                {
                    "case_id": case.case_id,
                    "rep": rep,
                    "expected": case.expected,
                    "draft": report.draft.result,
                    "status": report.status,
                    "diagnostics": asdict(report.decision_diagnostics),
                    "quality_reasons": list(report.quality.reasons),
                    "screening": [
                        {
                            "evidence_id": evaluation.evidence_id,
                            "relevance": evaluation.scores.relevant_to_question,
                            "support": evaluation.scores.directly_supports_answer,
                            "contradiction": evaluation.scores.contradicts_current_evidence,
                        }
                        for evaluation in report.evaluations
                    ],
                    "obligations": [
                        {
                            "kind": state.kind,
                            "verified": state.verified,
                            "independent_support": state.independent_support,
                        }
                        for row in report.aggregations
                        for state in row.obligation_states
                    ],
                    "pair_verdicts": [item.verdict for item in report.pairs],
                }
            )
    payload = {
        "measurement": "support_on_topic",
        "note": "Same compatible pair logic but the plan question now matches the evidence topic.",
        "rows": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in rows:
        print(row["case_id"], row["rep"], row["status"], row["diagnostics"]["reasons"], row["quality_reasons"])
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
