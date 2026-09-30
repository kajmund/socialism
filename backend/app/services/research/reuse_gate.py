"""Question-specific sufficiency gate, shared by research and the step laboratory."""

from collections.abc import Sequence

from app.services.execution.snapshots import snapshot_research_evidence
from app.services.research.assessment import (
    AssessableEvidence,
    ResearchAssessor,
    ResearchAssessmentDraft,
    sanitize_assessment_draft,
)
from app.services.research.models import ResearchEvidence, ResearchNeed, ResearchPlan


def fresh_evidence(items: Sequence[ResearchEvidence]) -> list[ResearchEvidence]:
    return [item for item in items if item.metadata.get("reuse", {}).get("freshness") == "fresh"]


def assessable_candidates(items: Sequence[ResearchEvidence]) -> list[AssessableEvidence]:
    return [
        AssessableEvidence(
            evidence_id=item.evidence_id,
            research_need_id=item.research_need_id,
            source_type=item.source_type,
            status=item.status,
            title=item.title,
            excerpt=item.excerpt,
            locator=item.locator,
            source_id=item.source_id,
            source_url=item.source_url,
            provider=item.provider,
            score=item.score,
            provenance=item.metadata,
            retrieved_at=item.retrieved_at,
            content_hash=snapshot_research_evidence(item).content_hash,
            legal_result=item.legal_result,
        )
        for item in items
    ]


async def assess_reuse(
    assessor: ResearchAssessor,
    need: ResearchNeed,
    items: Sequence[ResearchEvidence],
) -> ResearchAssessmentDraft:
    plan = ResearchPlan(needs=[need])
    evidence = assessable_candidates(fresh_evidence(items))
    draft = await assessor.assess(plan, evidence)
    return sanitize_assessment_draft(draft, plan=plan, evidence=evidence)


def answer_is_sufficient(draft: ResearchAssessmentDraft) -> bool:
    return (
        draft.result == "sufficient"
        and not draft.contradictions
        and all(
            row.sufficient and row.supporting_evidence_ids and not row.contradictions
            for row in draft.need_assessments
        )
        and bool(draft.need_assessments)
    )
