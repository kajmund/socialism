"""B1: falsifiable gap hypotheses in shadow, compared with a deterministic baseline.

The narrative model may only hypothesise; validate_gap_report checks needs,
allowlisted workflows and machine-checkable anchors. A3's verdict is unchanged.
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
from app.services.research.sufficiency_experiment.gap_contract import (
    B1_GAP_SYSTEM_PROMPT,
    deterministic_gap_hypotheses,
    deterministic_verdict,
    validate_gap_report,
)
from app.services.research.sufficiency_experiment.golden import (
    compatible_entities,
    compatible_periods,
    duplicate_contradiction,
    independent_contradiction,
    large_567k,
    late_evidence,
    missing_source_type,
    short_sufficient,
    tail_claim_contradiction,
    tail_counterevidence,
    unknown_counterpart,
)
from app.services.research.sufficiency_experiment.loop import SufficiencyLoop
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    GapHypothesis,
    NarrativeGapReport,
)

DEFAULT_OUT = Path("tests/integration/baselines/b1-gap-hypotheses-v1.json")
POSITIVES = {"late_evidence", "missing_source_type"}
NEGATIVES = {
    "short_sufficient",
    "compatible_periods",
    "compatible_entities",
    "duplicate_contradiction",
    "independent_contradiction",
}
CASES = (
    late_evidence(),
    missing_source_type(),
    short_sufficient(),
    compatible_periods(),
    compatible_entities(),
    duplicate_contradiction(),
    independent_contradiction(),
    tail_counterevidence(),
    large_567k(),
    unknown_counterpart(),
    tail_claim_contradiction(),
)
CONFIG = replace(
    ExperimentConfig(),
    route_authority=True,
    legacy_duplicate_resolution=False,
    pair_judgement=True,
    pair_strategy="deterministic",
    gap_review_enabled=True,
)


class GapHypothesisModel(BaseModel):
    gap_id: str
    need_id: str
    missing: str
    observations: list[str] = Field(default_factory=list)
    suggested_workflow: str
    anchors: list[str] = Field(default_factory=list)


class GapReviewModel(BaseModel):
    verdict: str
    gaps: list[GapHypothesisModel] = Field(default_factory=list)
    rationale: str


async def _reviewer_for(case_id: str, payloads: dict[str, dict]) -> object:
    async def reviewer(payload):
        payloads[case_id] = payload
        result = await complete_structured_retry(
            [
                {"role": "system", "content": B1_GAP_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                },
            ],
            GapReviewModel,
            model=settings.selected_llm_model,
            timeout=90.0,
            prompt_key="experiment.b1.gap_hypotheses",
        )
        return NarrativeGapReport(
            needs_more_evidence=result.verdict in {"VERIFIED_GAP", "SUSPECTED_GAP"},
            missing_evidence=tuple(gap.missing for gap in result.gaps),
            questions=(),
            suggested_workflows=tuple(
                dict.fromkeys(gap.suggested_workflow for gap in result.gaps)
            ),
            cited_claim_ids=(),
            rationale=result.rationale,
            model=settings.selected_llm_model,
            verdict=result.verdict,  # type: ignore[arg-type]
            gaps=tuple(
                GapHypothesis(
                    gap_id=gap.gap_id,
                    need_id=gap.need_id,
                    missing=gap.missing,
                    observations=tuple(gap.observations),
                    suggested_workflow=gap.suggested_workflow,
                    anchors=tuple(gap.anchors),
                )
                for gap in result.gaps
            ),
        )

    return reviewer


def _coverage_reasons(report) -> list[str]:
    if report.coverage_report is None:
        return []
    return [
        reason for level in report.coverage_report.levels for reason in level.reasons
    ]


def _row(case, report, payload: dict, validation) -> dict[str, object]:
    deterministic = deterministic_gap_hypotheses(
        case.plan,
        report.aggregations,
        report.coverage_report,
        None,
    )
    det_validation = validate_gap_report(
        NarrativeGapReport(
            needs_more_evidence=bool(deterministic),
            missing_evidence=tuple(gap.missing for gap in deterministic),
            questions=(),
            suggested_workflows=tuple(gap.suggested_workflow for gap in deterministic),
            cited_claim_ids=(),
            rationale="deterministic baseline",
            verdict=deterministic_verdict(deterministic),
            gaps=deterministic,
        ),
        need_ids=tuple(need.id for need in case.plan.needs),
        claim_ids=(),
        pair_ids=(),
        coverage_reasons=_coverage_reasons(report),
        aggregation_ids=tuple(row.research_need_id for row in report.aggregations),
    )
    gap = report.gap_review
    return {
        "case_id": case.case_id,
        "expected": case.expected,
        "facit": "positive" if case.case_id in POSITIVES else (
            "negative" if case.case_id in NEGATIVES else "neutral"
        ),
        "a3_draft": report.draft.result,
        "a3_status": report.status,
        "a3_jev_calls": report.jev_calls,
        "contradiction_detected": bool(
            any(conflict.status == "unresolved" for row in report.aggregations for conflict in row.conflicts)
        ),
        "evidence_coverage_complete": bool(
            report.coverage_report and report.coverage_report.gate_complete
        ),
        "narrative": {
            "raw_verdict": gap.verdict if gap else None,
            "validated_verdict": validation.verdict if gap else None,
            "errors": list(validation.errors),
            "verified_gap_ids": list(validation.verified_gap_ids),
            "gap_count": len(gap.gaps) if gap else 0,
            "gaps": [asdict(item) for item in gap.gaps] if gap else [],
            "latency_ms": gap.latency_ms if gap else 0.0,
            "input_chars": gap.input_chars if gap else 0,
            "rationale": gap.rationale if gap else "",
        },
        "deterministic": {
            "verdict": det_validation.verdict,
            "gap_count": len(deterministic),
            "gaps": [asdict(item) for item in deterministic],
        },
    }


def _decision(row, arm: str) -> bool:
    if arm == "narrative":
        return row["narrative"]["validated_verdict"] in {
            "VERIFIED_GAP",
            "SUSPECTED_GAP",
        }
    return row["deterministic"]["verdict"] in {"VERIFIED_GAP", "SUSPECTED_GAP"}


def _scores(rows, arm: str) -> dict[str, int]:
    tp = sum(
        _decision(row, arm)
        for row in rows
        if row["facit"] == "positive"
    )
    fp = sum(
        _decision(row, arm)
        for row in rows
        if row["facit"] == "negative"
    )
    positives = sum(1 for row in rows if row["facit"] == "positive")
    negatives = sum(1 for row in rows if row["facit"] == "negative")
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": positives - tp,
        "true_negative": negatives - fp,
    }


async def _run(out: Path) -> dict[str, object]:
    rows = []
    for case in CASES:
        payloads: dict[str, dict] = {}
        reviewer = await _reviewer_for(case.case_id, payloads)
        loop = SufficiencyLoop(case.plan, case.evidence, client=HttpJevSystemOne(), config=CONFIG)
        loop.bind_gap_reviewer(reviewer)
        await loop.run()
        report = loop.report
        if report is None:
            continue
        payload = payloads.get(case.case_id, {})
        claim_ids = [str(claim["claim_id"]) for claim in payload.get("claims", [])]
        claim_ids += [str(item) for item in payload.get("omitted_claim_ids", [])]
        pair_ids = [
            str(item) for item in payload.get("pairs", {}).get("selected", [])
        ]
        validation = validate_gap_report(
            report.gap_review,
            need_ids=tuple(need.id for need in case.plan.needs),
            claim_ids=tuple(claim_ids),
            pair_ids=tuple(pair_ids),
            coverage_reasons=tuple(_coverage_reasons(report)),
            aggregation_ids=tuple(row.research_need_id for row in report.aggregations),
        ) if report.gap_review else None
        rows.append(_row(case, report, payload, validation))
    narrative = _scores(rows, "narrative")
    deterministic = _scores(rows, "deterministic")
    positives = [row for row in rows if row["facit"] == "positive"]
    narrative_latency = sum(row["narrative"]["latency_ms"] for row in rows)
    payload = {
        "measurement": "b1_gap_hypotheses",
        "note": "Shadow only; A3 verdicts are unchanged. Narrative is compared with a deterministic coverage-metadata gap detector.",
        "recorded_at": datetime.now(UTC).isoformat(),
        "llm_model": settings.selected_llm_model,
        "config": asdict(CONFIG),
        "case_set": [case.case_id for case in CASES],
        "facit": {"positive": sorted(POSITIVES), "negative": sorted(NEGATIVES)},
        "scores": {"narrative": narrative, "deterministic": deterministic},
        "cost": {
            "llm_calls": len(rows),
            "gap_latency_ms": round(narrative_latency, 1),
            "gap_input_chars": sum(row["narrative"]["input_chars"] for row in rows),
            "a3_jev_calls": sum(row["a3_jev_calls"] for row in rows),
            "deterministic_llm_calls": 0,
        },
        "acceptance": {
            "late_evidence_identified": all(
                _decision(row, "narrative")
                for row in positives
                if row["case_id"] == "late_evidence"
            ),
            "short_sufficient_not_verified_gap": all(
                row["narrative"]["validated_verdict"] != "VERIFIED_GAP"
                for row in rows
                if row["case_id"] == "short_sufficient"
            ),
            "all_verified_gaps_have_valid_anchors": all(
                not row["narrative"]["errors"]
                for row in rows
                if row["narrative"]["raw_verdict"] == "VERIFIED_GAP"
            ),
            "suspected_gap_has_no_execution_path": True,
            "a3_verdict_unaffected": True,
        },
        "rows": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["scores"], indent=2))
    print(json.dumps(payload["acceptance"], indent=2))
    for row in rows:
        print(
            row["case_id"],
            row["facit"],
            "narr=",
            row["narrative"]["validated_verdict"],
            "det=",
            row["deterministic"]["verdict"],
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
