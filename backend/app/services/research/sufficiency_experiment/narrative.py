"""Bounded narrative pass. Tools are allowlisted typed workflows only."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from app.services.research.assessment import (
    ResearchAssessmentDraft,
    ResearchNeedAssessment,
)
from app.services.research.models import ResearchPlan
from app.services.research.sufficiency_experiment.tools import (
    ALLOWED_WORKFLOWS,
    RecursionLimitError,
)
from app.services.research.sufficiency_experiment.types import (
    ExperimentConfig,
    NeedAggregation,
    ProvenanceEvent,
)

NARRATIVE_SYSTEM_PROMPT = (
    "You are a bounded sufficiency reviewer. Use only allowlisted typed "
    "workflows. Do not search. Do not open a database. Do not invent "
    "evidence IDs. Return the same sufficiency schema. Recursion is forbidden."
)

NarrativeFn = Callable[[dict[str, Any]], Awaitable[ResearchAssessmentDraft]]


async def run_narrative(
    plan: ResearchPlan,
    aggregations: Sequence[NeedAggregation],
    *,
    config: ExperimentConfig,
    registry: Mapping[str, Any],
    completer: NarrativeFn,
    depth: int,
) -> tuple[ResearchAssessmentDraft, tuple[ProvenanceEvent, ...]]:
    if depth >= config.max_narrative_depth:
        raise RecursionLimitError("narrative may run at most once")
    payload = {
        "system": NARRATIVE_SYSTEM_PROMPT,
        "allowed_tools": sorted(ALLOWED_WORKFLOWS),
        "bound_workflows": sorted(registry),
        "needs": [need.id for need in plan.needs],
        "aggregations": [_row(item) for item in aggregations],
        "max_tool_calls": config.max_tool_calls,
        "max_input_chars": config.max_narrative_input_chars,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > config.max_narrative_input_chars:
        raise ValueError("narrative input exceeds budget")
    draft = await completer(payload)
    event = ProvenanceEvent(
        workflow="narrative",
        input_hash=_hash(encoded),
        output_hash=_hash(draft.rationale),
        parent=None,
    )
    return draft, (event,)


def draft_from_aggregations(
    aggregations: Sequence[NeedAggregation],
    *,
    considered: Sequence[str],
) -> ResearchAssessmentDraft:
    rows = [
        ResearchNeedAssessment(
            research_need_id=item.research_need_id,
            sufficient=item.sufficient,
            supporting_evidence_ids=list(item.supporting_evidence_ids),
            missing_or_weak=item.missing_or_weak,
            contradictions=list(item.contradictions),
        )
        for item in aggregations
    ]
    sufficient = all(row.sufficient for row in rows) if rows else True
    return ResearchAssessmentDraft(
        result="sufficient" if sufficient else "insufficient",
        rationale=(
            "Every ResearchNeed has supporting Jev passages."
            if sufficient
            else "Deterministic aggregation of complete Jev passage verdicts."
        ),
        need_assessments=rows,
        gaps=[
            f"{row.research_need_id}: {row.missing_or_weak}"
            for row in rows
            if not row.sufficient and row.missing_or_weak
        ],
        contradictions=[item for row in rows for item in row.contradictions],
        considered_evidence_ids=list(considered),
        model_provider="jev",
        model_name="sufficiency_experiment",
        model_version="v1",
    )


def _row(item: NeedAggregation) -> dict[str, object]:
    return {
        "research_need_id": item.research_need_id,
        "sufficient": item.sufficient,
        "supporting_evidence_ids": list(item.supporting_evidence_ids),
        "contradictions": list(item.contradictions),
        "undecided_passage_ids": list(item.undecided_passage_ids),
        "needs_narrative": item.needs_narrative,
        "missing_or_weak": item.missing_or_weak,
    }


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
