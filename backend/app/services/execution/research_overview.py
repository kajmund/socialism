"""Question-specific assessment projection for the research monitor."""

from app.database.models import ResearchAssessment
from app.services.execution.schemas import ResearchNeedAssessmentOut
from app.services.research.assessment import need_assessment_from_json


def need_assessment_view(
    assessment: ResearchAssessment | None,
    need_id: str,
) -> ResearchNeedAssessmentOut | None:
    raw = (
        next(
            (
                item
                for item in assessment.need_assessments or []
                if item.get("research_need_id") == need_id
            ),
            None,
        )
        if assessment
        else None
    )
    if raw is None:
        return None
    parsed = need_assessment_from_json(raw)
    return ResearchNeedAssessmentOut(
        research_need_id=parsed.research_need_id,
        sufficient=parsed.sufficient,
        supporting_evidence_ids=parsed.supporting_evidence_ids,
        missing_or_weak=parsed.missing_or_weak,
        contradictions=parsed.contradictions,
        further_information=parsed.further_information,
    )
