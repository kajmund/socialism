"""B0: measure what a shadow narrative gap review identifies.

No decision authority. The A3 arm is unchanged; the gap review is recorded next
to it. The live model is the configured Cerebras model, and the experiment
prompt is intentionally experiment-only (flagged in ticket 11).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import settings
from app.jev.system import HttpJevSystemOne
from app.llm import complete_structured_retry
from app.services.research.sufficiency_experiment.golden import (
    conflict_benchmark_cases,
    scripted_benchmark_cases,
    tail_claim_contradiction,
)
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.narrative_gap import (
    GAP_SYSTEM_PROMPT,
)
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    NarrativeGapReport,
)

DEFAULT_OUT = Path("tests/integration/baselines/b0-gap-review-v1.json")
CASE_SET = tuple(scripted_benchmark_cases()) + tuple(conflict_benchmark_cases()) + (
    tail_claim_contradiction(),
)
GAP_FACIT = {"late_evidence": True}
CONFIG = replace(
    ExperimentConfig(),
    route_authority=True,
    legacy_duplicate_resolution=False,
    pair_judgement=True,
    pair_strategy="deterministic",
    gap_review_enabled=True,
)


class GapModel(BaseModel):
    needs_more_evidence: bool
    missing_evidence: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    suggested_workflows: list[str] = Field(default_factory=list)
    cited_claim_ids: list[str] = Field(default_factory=list)
    rationale: str


async def _reviewer(payload: dict[str, object]) -> NarrativeGapReport:
    result = await complete_structured_retry(
        [
            {"role": "system", "content": GAP_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            },
        ],
        GapModel,
        model=settings.selected_llm_model,
        timeout=90.0,
        prompt_key="experiment.b0.gap_review",
    )
    return NarrativeGapReport(
        needs_more_evidence=result.needs_more_evidence,
        missing_evidence=tuple(result.missing_evidence),
        questions=tuple(result.questions),
        suggested_workflows=tuple(result.suggested_workflows),
        cited_claim_ids=tuple(result.cited_claim_ids),
        rationale=result.rationale,
        model=settings.selected_llm_model,
    )


async def _run(out: Path) -> dict[str, object]:
    client = HttpJevSystemOne()
    rows = []
    for case in CASE_SET:
        loop = SufficiencyLoop(case.plan, case.evidence, client=client, config=CONFIG)
        loop.bind_gap_reviewer(_reviewer)
        await loop.run()
        report = loop.report
        if report is None:
            continue
        conflicts = [c for row in report.aggregations for c in row.conflicts]
        unresolved = [c for c in conflicts if c.status == "unresolved"]
        gap = report.gap_review
        rows.append(
            {
                "case_id": case.case_id,
                "expected": case.expected,
                "draft": report.draft.result,
                "decision_correct": report.draft.result == case.expected,
                "contradiction_detected": bool(unresolved),
                "evidence_coverage_complete": bool(
                    report.coverage_report and report.coverage_report.gate_complete
                ),
                "a3_jev_calls": report.jev_calls,
                "gap": asdict(gap) if gap else None,
                "gap_needs_more_evidence": bool(
                    gap and gap.needs_more_evidence
                ),
                "gap_error": gap.error if gap else None,
            }
        )
    positives = [row for row in rows if GAP_FACIT.get(row["case_id"], False)]
    negatives = [row for row in rows if not GAP_FACIT.get(row["case_id"], False)]
    flagged = [row for row in rows if row["gap_needs_more_evidence"]]
    payload = {
        "measurement": "b0_gap_review",
        "note": (
            "Shadow only: the gap review does not affect the A3 verdict. One "
            "live run; gap facit is late_evidence only (the one case A3 did not "
            "solve by contradiction detection)."
        ),
        "recorded_at": datetime.now(UTC).isoformat(),
        "llm_model": settings.selected_llm_model,
        "config": asdict(CONFIG),
        "metrics": {
            "gap_true_positive": sum(
                row["gap_needs_more_evidence"] for row in positives
            ),
            "gap_false_negative": sum(
                not row["gap_needs_more_evidence"] for row in positives
            ),
            "gap_false_positive": sum(
                row["gap_needs_more_evidence"] for row in negatives
            ),
            "cases_flagged": len(flagged),
            "gap_errors": sum(1 for row in rows if row["gap_error"]),
        },
        "rows": rows,
    }
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload["metrics"], indent=2))
    for row in rows:
        print(
            row["case_id"],
            row["draft"],
            "gap=",
            row["gap_needs_more_evidence"],
            row["gap_error"],
        )
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
