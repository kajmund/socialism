from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from app.llm.research_followup import FollowUpNeedModel, FollowUpPlanModel, LlmFollowUpPlanner
from app.services.research.assessment import ResearchAssessmentDraft, ResearchNeedAssessment
from app.services.research.followup import (
    FollowUpNeedDraft,
    RuntimeResearchNeed,
    validate_follow_up_drafts,
)
from app.services.research.knowledge_question import identity_from_text, tenant_question_scope
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.question_iteration import (
    RelatedKnowledgeQuestion,
    prepare_iterative_follow_ups,
)
from tests.research_reuse.helpers import context, evidence, need, pending_contract
from tests.research_reuse.probes import gaps

pytestmark = pytest.mark.research_reuse


async def test_sufficient_answer_never_calls_gap_planner(reuse_db):
    builder = AsyncMock(side_effect=RuntimeError("Planner must not be constructed"))
    assessment = ResearchAssessmentDraft(result="sufficient", rationale="Already answered")
    assert (
        await gaps(reuse_db, need(), [evidence()], assessment, context=context(), builder=builder)
        == []
    )
    builder.assert_not_called()


async def test_only_missing_information_is_sent_to_real_planner_adapter(reuse_db):
    import json

    completer = AsyncMock(
        return_value=FollowUpPlanModel(
            needs=[
                FollowUpNeedModel(
                    question="Vilka lagändringar infördes 1995?",
                    why_needed="Senare lagändringar saknas",
                    source_gap="Senare lagändringar saknas",
                    source_types=need().source_types,
                    parent_research_need_id="child",
                )
            ]
        )
    )
    adapter = LlmFollowUpPlanner(
        completer=completer,
        system_prompt="Mock model boundary",
        user_prompt="{assessment_json}",
    )
    assessment = ResearchAssessmentDraft(
        result="insufficient",
        rationale="Införandet är belagt, senare ändringar saknas",
        need_assessments=[
            ResearchNeedAssessment(
                research_need_id="child",
                sufficient=False,
                missing_or_weak="Senare lagändringar saknas",
            )
        ],
        gaps=["Senare lagändringar saknas"],
    )
    rows = await gaps(
        reuse_db,
        need(),
        [evidence()],
        assessment,
        context=context(),
        builder=AsyncMock(return_value=adapter),
    )
    payload = json.loads(completer.call_args.args[0][1]["content"])
    assert payload["gaps"] == assessment.gaps
    assert len(rows) == 1 and rows[0].parent_research_need_id == "child"
    assert rows[0].source_gap == "Senare lagändringar saknas"


def test_existing_exact_questions_and_unavailable_sources_are_not_new_gaps():
    previous = [
        RuntimeResearchNeed(
            research_need_id="child",
            question=need().question,
            why_needed="Known",
            source_types=need().source_types,
        )
    ]
    drafts = [
        FollowUpNeedDraft(
            question=need().question, why_needed="Repeat", source_types=need().source_types
        ),
        FollowUpNeedDraft(
            question="En annan fråga?", why_needed="Gap", source_types=["web_search"]
        ),
    ]
    assert (
        validate_follow_up_drafts(
            drafts, previous_needs=previous, wave_number=1, allowed_source_types=need().source_types
        )
        == []
    )


@pytest.mark.parametrize("duplicate_in", ["previous-wave", "same-batch"])
@pending_contract("Punkt 3: canonical semantic duplicates are currently accepted as new executions")
async def test_same_canonical_question_is_not_executed_twice(reuse_db, duplicate_in):
    graph = SqlQuestionEvidenceGraph()
    async with reuse_db() as session:
        canonical = await graph.upsert_question(
            session, identity_from_text(need().question), tenant_question_scope(1)
        )
        previous = (
            [
                RuntimeResearchNeed(
                    research_need_id="already",
                    question=need().question,
                    why_needed="Known",
                    source_types=need().source_types,
                    knowledge_question_id=canonical.id,
                )
            ]
            if duplicate_in == "previous-wave"
            else []
        )
        candidates = [
            RuntimeResearchNeed(
                research_need_id="new",
                question="Hur påverkade nya lagar paragraf 36?",
                why_needed="Same meaning",
                source_types=need().source_types,
                origin="derived",
            )
        ]
        if duplicate_in == "same-batch":
            candidates.append(
                replace(
                    candidates[0],
                    research_need_id="newer",
                    question="Vad innebar lagändringarna för paragrafen?",
                )
            )
        relations = AsyncMock()
        relations.related_questions.return_value = [RelatedKnowledgeQuestion(canonical, "same_as")]
        rows = await prepare_iterative_follow_ups(
            session,
            graph=graph,
            context=context(),
            accepted=candidates,
            previous=previous,
            relations=relations,
        )
        assert all(row.knowledge_question_id == canonical.id for row in rows)
        assert len(rows) == (0 if previous else 1), "Canonical ID must be resolved before queuing"
