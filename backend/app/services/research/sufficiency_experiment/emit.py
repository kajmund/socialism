"""Build the product assessment draft from obligation aggregations."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.research.assessment import (
    ResearchAssessmentDraft,
    ResearchNeedAssessment,
)
from app.services.research.sufficiency_experiment.types import (
    ExperimentStatus,
    NeedAggregation,
)


def draft_from_aggregations(
    aggregations: Sequence[NeedAggregation],
    *,
    status: ExperimentStatus,
    considered: Sequence[str],
    reasons: Sequence[str] = (),
) -> ResearchAssessmentDraft:
    rows = [
        ResearchNeedAssessment(
            research_need_id=item.research_need_id,
            sufficient=item.sufficient and status == "sufficient",
            supporting_evidence_ids=list(item.supporting_evidence_ids),
            missing_or_weak=item.missing_or_weak,
            contradictions=list(item.unresolved_conflicts),
        )
        for item in aggregations
    ]
    result = "sufficient" if status == "sufficient" else "insufficient"
    return ResearchAssessmentDraft(
        result=result,
        rationale=_rationale(status, reasons),
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
        model_version="v2",
    )


def _rationale(status: ExperimentStatus, reasons: Sequence[str]) -> str:
    extra = f" Reasons: {', '.join(reasons)}." if reasons else ""
    if status == "sufficient":
        return "Every mandatory obligation is verified with independent support."
    if status == "uncertain":
        return "Obligations or contradictions remain unresolved; fail-closed." + extra
    if status == "failed":
        return "Sufficiency evaluation failed; fail-closed." + extra
    return "Mandatory obligations lack verified support." + extra
