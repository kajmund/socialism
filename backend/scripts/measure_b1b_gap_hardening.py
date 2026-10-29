"""B1b: hardened closed-anchor gap review versus the deterministic baseline.

Narrative remains shadow-only. Existing frozen cases run live; five synthetic
semantic-gap cases run with the scripted Jev client so only the narrative model
is live. The rejection criteria are pre-registered in the artifact.
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
from app.services.research.sufficiency_experiment.gap_cases import (
    clean_consistent_pair,
    clean_scope_difference,
    clean_single_short,
    semantic_gap_hours,
    semantic_gap_synonyms,
)
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
from app.services.research.sufficiency_experiment.scripted import (
    ScriptedSufficiencyJev,
)
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    GapHypothesis,
    NarrativeGapReport,
)

DEFAULT_OUT = Path("tests/integration/baselines/b1b-gap-hardening-v1.json")
LIVE_POSITIVES = {"late_evidence", "missing_source_type"}
LIVE_NEGATIVES = {
    "short_sufficient",
    "compatible_periods",
    "compatible_entities",
    "duplicate_contradiction",
    "independent_contradiction",
}
LIVE_NEUTRAL = {"tail_counterevidence", "large_567k", "unknown_counterpart", "tail_claim_contradiction"}
SYNTHETIC_POSITIVES = {"semantic_gap_synonyms", "semantic_gap_hours"}
SYNTHETIC_NEGATIVES = {"clean_consistent_pair", "clean_single_short", "clean_scope_difference"}
SYNTHETIC = {
    "semantic_gap_synonyms": semantic_gap_synonyms(),
    "semantic_gap_hours": semantic_gap_hours(),
    "clean_consistent_pair": clean_consistent_pair(),
    "clean_single_short": clean_single_short(),
    "clean_scope_difference": clean_scope_difference(),
}
LIVE_CASES = (
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
PROTOCOL = {
    "purpose": "last bounded test of narrative gap detection",
    "continue_to_B2": [
        "incremental_verified_gap_yield >= 1 (narrative finds a true gap the deterministic baseline misses)",
        "narrative false positives <= deterministic false positives + 1",
        "valid_report_rate >= 0.9",
        "unsupported_anchor_rate == 0",
        "marginal cost per useful gap reported",
    ],
    "retire_if_match": "incremental yield == 0 and quality is not better than the deterministic baseline",
    "end_branch_if_worse": "narrative has lower precision or more false positives than the baseline",
}


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


def _reviewer(case, payloads: dict[str, dict]):
    async def reviewer(payload):
        payloads[case.case_id] = payload
        result = await complete_structured_retry(
            [
                {"role": "system", "content": B1_GAP_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
            ],
            GapReviewModel,
            model=settings.selected_llm_model,
            timeout=90.0,
            prompt_key="experiment.b1b.gap_hardening",
        )
        return NarrativeGapReport(
            needs_more_evidence=result.verdict in {"VERIFIED_GAP", "SUSPECTED_GAP"},
            missing_evidence=tuple(gap.missing for gap in result.gaps),
            questions=(),
            suggested_workflows=tuple(dict.fromkeys(gap.suggested_workflow for gap in result.gaps)),
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


def _anchor_map(payload: dict) -> dict[str, str]:
    return {
        str(item["id"]): str(item["need_id"])
        for item in payload.get("available_anchors", [])
    }


def _coverage_reasons(report) -> list[str]:
    if report.coverage_report is None:
        return []
    return [reason for level in report.coverage_report.levels for reason in level.reasons]


def _gap_anchor_ok(gap: GapHypothesis, anchors: dict[str, str]) -> bool:
    if not gap.anchors:
        return False
    needs = [anchors.get(anchor) for anchor in gap.anchors]
    return all(need is not None for need in needs) and any(
        need in {"", gap.need_id} for need in needs
    )


def _row(case, report, payload, validation) -> dict:
    det = deterministic_gap_hypotheses(
        case.plan, report.aggregations, report.coverage_report, None
    )
    det_validation = validate_gap_report(
        NarrativeGapReport(
            needs_more_evidence=bool(det),
            missing_evidence=tuple(gap.missing for gap in det),
            questions=(),
            suggested_workflows=tuple(gap.suggested_workflow for gap in det),
            cited_claim_ids=(),
            rationale="deterministic",
            verdict=deterministic_verdict(det),
            gaps=det,
        ),
        need_ids=tuple(need.id for need in case.plan.needs),
        claim_ids=(),
        pair_ids=(),
        coverage_reasons=_coverage_reasons(report),
        aggregation_ids=tuple(row.research_need_id for row in report.aggregations),
    )
    gap = report.gap_review
    anchors = _anchor_map(payload)
    gaps = gap.gaps if gap else ()
    return {
        "case_id": case.case_id,
        "facit": (
            "positive" if case.case_id in LIVE_POSITIVES | SYNTHETIC_POSITIVES
            else "negative" if case.case_id in LIVE_NEGATIVES | SYNTHETIC_NEGATIVES
            else "neutral"
        ),
        "jev": "scripted" if case.case_id in SYNTHETIC else "live",
        "a3_draft": report.draft.result,
        "a3_status": report.status,
        "narrative": {
            "raw_verdict": gap.verdict if gap else None,
            "validated_verdict": validation.verdict if gap else None,
            "errors": list(validation.errors) if validation else [],
            "gaps": [asdict(item) for item in gaps],
            "unsupported_anchor_gaps": [
                item.gap_id for item in gaps if not _gap_anchor_ok(item, anchors)
            ],
            "latency_ms": gap.latency_ms if gap else 0.0,
            "input_chars": gap.input_chars if gap else 0,
            "rationale": gap.rationale if gap else "",
        },
        "deterministic": {
            "verdict": det_validation.verdict,
            "gaps": [asdict(item) for item in det],
        },
        "a3_jev_calls": report.jev_calls,
    }


def _detected(row, arm: str) -> bool:
    if arm == "narrative":
        return row["narrative"]["validated_verdict"] in {"VERIFIED_GAP", "SUSPECTED_GAP"}
    return row["deterministic"]["verdict"] in {"VERIFIED_GAP", "SUSPECTED_GAP"}


def _scores(rows, arm: str) -> dict[str, int]:
    positives = [row for row in rows if row["facit"] == "positive"]
    negatives = [row for row in rows if row["facit"] == "negative"]
    tp = sum(_detected(row, arm) for row in positives)
    fp = sum(_detected(row, arm) for row in negatives)
    return {"true_positive": tp, "false_positive": fp,
            "false_negative": len(positives) - tp, "true_negative": len(negatives) - fp}


async def _run(out: Path) -> dict:
    rows = []
    live_client = HttpJevSystemOne()
    for case in LIVE_CASES + tuple(SYNTHETIC.values()):
        payloads: dict[str, dict] = {}
        client = live_client if case.case_id in {c.case_id for c in LIVE_CASES} else ScriptedSufficiencyJev()
        loop = SufficiencyLoop(case.plan, case.evidence, client=client, config=CONFIG)
        loop.bind_gap_reviewer(_reviewer(case, payloads))
        await loop.run()
        report = loop.report
        if report is None:
            continue
        payload = payloads.get(case.case_id, {})
        anchors = _anchor_map(payload)
        validation = validate_gap_report(
            report.gap_review,
            need_ids=tuple(need.id for need in case.plan.needs),
            claim_ids=tuple(anchors),
            pair_ids=(),
            coverage_reasons=tuple(_coverage_reasons(report)),
            aggregation_ids=tuple(row.research_need_id for row in report.aggregations),
            available_anchors=anchors,
        ) if report.gap_review else None
        rows.append(_row(case, report, payload, validation))
    narrative = _scores(rows, "narrative")
    deterministic = _scores(rows, "deterministic")
    narrative_tp = {row["case_id"] for row in rows if row["facit"] == "positive" and _detected(row, "narrative")}
    deterministic_tp = {row["case_id"] for row in rows if row["facit"] == "positive" and _detected(row, "deterministic")}
    incremental = sorted(narrative_tp - deterministic_tp)
    negatives = [row for row in rows if row["facit"] == "negative"]
    all_gaps = [gap for row in rows for gap in row["narrative"]["gaps"]]
    unsupported = [gap for row in rows for gap in row["narrative"]["unsupported_anchor_gaps"]]
    classified = [row for row in rows if row["facit"] != "neutral"]
    valid = [
        row
        for row in classified
        if row["narrative"]["raw_verdict"] is not None
        and row["narrative"]["validated_verdict"] not in {None, "UNDETERMINED"}
    ]
    false_workflow = [row for row in negatives if row["narrative"]["gaps"]]
    llm_calls = len(rows)
    metrics = {
        "classified_cases": len(classified),
        "excluded_neutral_cases": [row["case_id"] for row in rows if row["facit"] == "neutral"],
        "gap_precision": round(narrative["true_positive"] / (narrative["true_positive"] + narrative["false_positive"]), 3) if narrative["true_positive"] + narrative["false_positive"] else None,
        "gap_recall": round(narrative["true_positive"] / (narrative["true_positive"] + narrative["false_negative"]), 3) if narrative["true_positive"] + narrative["false_negative"] else None,
        "valid_report_rate": round(len(valid) / len(classified), 3) if classified else None,
        "unsupported_anchor_rate": round(len(unsupported) / len(all_gaps), 3) if all_gaps else 0.0,
        "false_workflow_proposal_rate": round(len(false_workflow) / len(negatives), 3) if negatives else None,
        "incremental_gap_yield": len(incremental),
        "incremental_gap_ids": incremental,
        "marginal_cost_per_useful_gap": (
            round(llm_calls / len(incremental), 3) if incremental else None
        ),
    }
    if (
        len(incremental) >= 1
        and narrative["false_positive"] <= deterministic["false_positive"] + 1
        and (metrics["valid_report_rate"] or 0) >= 0.9
        and metrics["unsupported_anchor_rate"] == 0
    ):
        decision = "CONTINUE_TO_B2"
    elif (
        narrative["false_positive"] > deterministic["false_positive"]
        or (metrics["gap_precision"] or 0) < (
            deterministic["true_positive"]
            / max(1, deterministic["true_positive"] + deterministic["false_positive"])
        )
    ):
        decision = "END_NARRATIVE_BRANCH"
    else:
        decision = "RETIRE_NARRATIVE_GAP_DETECTION"
    payload = {
        "measurement": "b1b_gap_hardening",
        "recorded_at": datetime.now(UTC).isoformat(),
        "llm_model": settings.selected_llm_model,
        "protocol": PROTOCOL,
        "note": "Shadow only; five synthetic cases use scripted Jev and are labelled jev=scripted.",
        "config": asdict(CONFIG),
        "scores": {"narrative": narrative, "deterministic": deterministic},
        "metrics": metrics,
        "decision": decision,
        "cost": {
            "llm_calls": llm_calls,
            "gap_latency_ms": round(sum(row["narrative"]["latency_ms"] for row in rows), 1),
            "gap_input_chars": sum(row["narrative"]["input_chars"] for row in rows),
            "a3_jev_calls": sum(row["a3_jev_calls"] for row in rows),
            "deterministic_llm_calls": 0,
        },
        "rows": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["scores"], indent=2))
    print(json.dumps(metrics, indent=2))
    print("decision:", decision)
    for row in rows:
        print(row["case_id"], row["facit"], row["jev"], row["narrative"]["validated_verdict"], row["deterministic"]["verdict"])
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
