"""Project coverage obligations from existing ResearchNeed fields."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.research.assessment import AssessableEvidence
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.sufficiency_experiment.types import (
    EvidenceObligation,
    evidence_need_ids,
)


def obligations_for_need(need: ResearchNeed) -> list[EvidenceObligation]:
    if not need.source_types:
        return []
    rows = [
        EvidenceObligation(
            obligation_id=f"{need.id}:relevance",
            need_id=need.id,
            kind="relevance",
            description="At least one relevant passage for the need.",
        ),
        EvidenceObligation(
            obligation_id=f"{need.id}:factual_support",
            need_id=need.id,
            kind="factual_support",
            description="Verified factual support from an independent source.",
            min_independent_sources=2 if "corroboration" in need.capabilities else 1,
        ),
    ]
    for source in need.source_types:
        rows.append(
            EvidenceObligation(
                obligation_id=f"{need.id}:completeness:{source}",
                need_id=need.id,
                kind="completeness",
                description=f"Coverage includes source type {source}.",
            )
        )
    return rows


def obligations_for_plan(plan: ResearchPlan) -> list[EvidenceObligation]:
    return [row for need in plan.needs for row in obligations_for_need(need)]


def present_source_types(
    need: ResearchNeed,
    evidence: Sequence[AssessableEvidence],
) -> tuple[str, ...]:
    found: list[str] = []
    for item in evidence:
        if item.status != "found" or not item.source_type:
            continue
        if need.id not in evidence_need_ids(item):
            continue
        found.append(item.source_type)
    return tuple(dict.fromkeys(found))


def required_job_ids(
    plan: ResearchPlan,
    passage_ids: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        f"{need.id}:{passage_id}" for need in plan.needs for passage_id in passage_ids
    )
