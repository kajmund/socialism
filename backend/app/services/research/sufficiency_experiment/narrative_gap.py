"""B0 shadow gap review. The narrative model has no decision authority.

It receives a bounded, explicitly-truncated view of the A3 state and may only
report missing evidence, open questions and allowlisted workflow suggestions.
The result is recorded next to the run; emit/route/gate never read it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from time import perf_counter

from app.services.research.models import ResearchPlan
from app.services.research.sufficiency_experiment.tools import ALLOWED_WORKFLOWS
from app.services.research.sufficiency_experiment.types import (
    ClaimCandidate,
    CoverageReport,
    ExperimentConfig,
    NeedAggregation,
    NarrativeGapReport,
    PairSelection,
)

NarrativeGapFn = Callable[[dict[str, object]], Awaitable[NarrativeGapReport]]

GAP_SYSTEM_PROMPT = (
    "You are a bounded evidence-gap reviewer for a research workflow. Use only "
    "the supplied state. Do not invent evidence ids. Report which questions or "
    "evidence relations remain open, which evidence is missing, and which of the "
    "allowlisted workflows should run next. Return the requested schema. You do "
    "not decide sufficiency and you may not claim that all evidence was reviewed."
)


def build_gap_payload(
    plan: ResearchPlan,
    aggregations: tuple[NeedAggregation, ...],
    *,
    claims: tuple[ClaimCandidate, ...],
    selection: PairSelection | None,
    coverage: CoverageReport | None,
    max_chars: int,
) -> dict[str, object]:
    base: dict[str, object] = {
        "needs": [
            {"id": need.id, "question": need.question, "source_types": need.source_types}
            for need in plan.needs
        ],
        "aggregations": [
            {
                "need_id": row.research_need_id,
                "status": row.status,
                "missing_or_weak": row.missing_or_weak,
                "unresolved_conflicts": list(row.unresolved_conflicts),
                "unknown_requirements": row.unknown_requirements,
            }
            for row in aggregations
        ],
        "pairs": {
            "selected": [pair.pair_id for pair in selection.selected]
            if selection
            else [],
            "candidates": len(selection.candidates) if selection else 0,
            "omitted_by_budget": selection.omitted_by_budget if selection else 0,
        },
        "coverage": (
            json.loads(json.dumps(_coverage_payload(coverage)))
            if coverage is not None
            else None
        ),
        "allowed_workflows": sorted(ALLOWED_WORKFLOWS),
    }
    if len(_encoded(base)) > max_chars:
        raise ValueError("gap review base exceeds max_gap_input_chars")
    included: list[dict[str, object]] = []
    omitted_sample: list[str] = []
    omitted_count = 0

    def note_omitted(claim_id: str) -> None:
        nonlocal omitted_count
        omitted_count += 1
        if len(omitted_sample) < 20:
            omitted_sample.append(claim_id)

    for claim in claims:
        if claim.extraction_status != "extracted":
            continue
        row = {
            "claim_id": claim.claim_id,
            "evidence_id": claim.evidence_id,
            "passage_id": claim.passage_id,
            "text": claim.text,
        }
        included_ids = [str(item["claim_id"]) for item in included] + [claim.claim_id]
        candidate = {
            **base,
            "claims": [*included, row],
            "omitted_claim_ids": omitted_sample,
            "omitted_claim_count": omitted_count,
            "available_anchors": _available_anchors(
                claims,
                selection,
                aggregations,
                coverage,
                claim_ids=set(included_ids) | set(omitted_sample),
            ),
        }
        if len(_encoded(candidate)) > max_chars:
            note_omitted(claim.claim_id)
        else:
            included.append(row)
    while included:
        candidate = {
            **base,
            "claims": included,
            "omitted_claim_ids": omitted_sample,
            "omitted_claim_count": omitted_count,
            "available_anchors": _available_anchors(
                claims,
                selection,
                aggregations,
                coverage,
                claim_ids=set(str(item["claim_id"]) for item in included)
                | set(omitted_sample),
            ),
        }
        if len(_encoded(candidate)) <= max_chars:
            break
        note_omitted(str(included.pop()["claim_id"]))
    payload = {
        **base,
        "claims": included,
        "omitted_claim_ids": omitted_sample,
        "omitted_claim_count": omitted_count,
        "available_anchors": _available_anchors(
            claims,
            selection,
            aggregations,
            coverage,
            claim_ids=set(str(item["claim_id"]) for item in included)
            | set(omitted_sample),
        ),
    }
    if len(_encoded(payload)) > max_chars:
        raise ValueError("gap review payload exceeds max_gap_input_chars")
    return payload


async def run_gap_review(
    payload: dict[str, object],
    *,
    completer: NarrativeGapFn,
    config: ExperimentConfig,
) -> NarrativeGapReport:
    encoded = _encoded(payload)
    if len(encoded) > config.max_gap_input_chars:
        raise ValueError("gap review payload exceeds max_gap_input_chars")
    started = perf_counter()
    report = await completer(payload)
    unknown = set(report.suggested_workflows) - ALLOWED_WORKFLOWS
    if unknown:
        return NarrativeGapReport(
            needs_more_evidence=False,
            missing_evidence=(),
            questions=(),
            suggested_workflows=(),
            cited_claim_ids=(),
            rationale=f"invalid workflow suggestions: {sorted(unknown)}",
            latency_ms=(perf_counter() - started) * 1000,
            input_chars=len(encoded),
            error="invalid_workflow",
        )
    return NarrativeGapReport(
        needs_more_evidence=report.needs_more_evidence,
        missing_evidence=tuple(report.missing_evidence),
        questions=tuple(report.questions),
        suggested_workflows=tuple(report.suggested_workflows),
        cited_claim_ids=tuple(report.cited_claim_ids),
        rationale=report.rationale,
        latency_ms=(perf_counter() - started) * 1000,
        input_chars=len(encoded),
        model=report.model,
        verdict=report.verdict,
        gaps=tuple(report.gaps),
        validation_error=report.validation_error,
    )


def _available_anchors(
    claims: tuple[ClaimCandidate, ...],
    selection: PairSelection | None,
    aggregations: tuple[NeedAggregation, ...],
    coverage: CoverageReport | None,
    *,
    claim_ids: set[str],
) -> list[dict[str, str]]:
    anchors: list[dict[str, str]] = []
    for claim in claims:
        if claim.extraction_status != "extracted" or claim.claim_id not in claim_ids:
            continue
        need_id = claim.research_need_ids[0] if claim.research_need_ids else ""
        anchors.append(
            {"id": f"claim:{claim.claim_id}", "kind": "claim", "need_id": need_id}
        )
    if selection is not None:
        for pair in selection.selected:
            anchors.append(
                {
                    "id": f"pair:{pair.pair_id}",
                    "kind": "pair",
                    "need_id": pair.need_id,
                }
            )
    for row in aggregations:
        anchors.append(
            {
                "id": f"aggregation:{row.research_need_id}",
                "kind": "aggregation",
                "need_id": row.research_need_id,
            }
        )
    if coverage is not None:
        for level in coverage.levels:
            for reason in level.reasons:
                anchors.append(
                    {
                        "id": f"coverage:{reason}",
                        "kind": "coverage",
                        "need_id": "",
                    }
                )
    return anchors


def _coverage_payload(coverage: CoverageReport) -> dict[str, object]:
    return {
        "levels": [
            {
                "level": level.level,
                "status": level.status,
                "reasons": list(level.reasons),
            }
            for level in coverage.levels
        ],
        "gate_complete": coverage.gate_complete,
    }


def _encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
