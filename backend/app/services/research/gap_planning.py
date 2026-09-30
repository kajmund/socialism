"""Plan only the gaps in an assessed question; no retrieval or persistence."""

from collections.abc import Sequence

from app.services.research.assessment import ResearchAssessmentDraft
from app.services.research.followup import (
    FollowUpResearchPlanner,
    RuntimeResearchNeed,
    runtime_needs_from_plan,
    validate_follow_up_drafts,
)
from app.services.research.models import ResearchEvidence, ResearchNeed, ResearchPlan
from app.services.research.need_normalization import ResearchNeedNormalizer
from app.services.research.reuse_gate import answer_is_sufficient, assessable_candidates


async def plan_question_gaps(
    planner: FollowUpResearchPlanner,
    need: ResearchNeed,
    assessment: ResearchAssessmentDraft,
    evidence: Sequence[ResearchEvidence],
    *,
    normalizer: ResearchNeedNormalizer | None = None,
    available_source_types: Sequence[str] | None = None,
) -> list[RuntimeResearchNeed]:
    if answer_is_sufficient(assessment):
        return []
    types = need.source_types if available_source_types is None else available_source_types
    plan = ResearchPlan(needs=[need])
    previous = runtime_needs_from_plan(plan)
    drafts = await planner.plan_follow_ups(
        plan=plan,
        assessment=assessment,
        evidence=assessable_candidates(evidence),
        previous_needs=previous,
        available_source_types=types,
    )
    if normalizer is not None:
        drafts = await normalizer.normalize_follow_up_drafts(drafts)
    return validate_follow_up_drafts(
        drafts,
        previous_needs=previous,
        wave_number=1,
        assessment_pass=1,
        allowed_source_types=types,
    )
