"""A saved answer follows the canonical question when its execution role changes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, text

from app.database.models import DocumentVersionRecord, KnowledgeQuestionRow, TextUnitRecord
from app.services.execution import list_evidence_items, list_runtime_needs
from app.services.research import ResearchPlan, execute_attempt_research
from app.services.research.answer_review import capture_answer_reviews
from app.services.research.planner import ResearchObjective
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from tests.research_reuse.helpers import CHILD, MAIN, attempt, need, reviewed_answer
from tests.research_reuse.test_04_main_answer import persisted_basis
from tests.test_research_question_evidence import RecordingSource, _router

pytestmark = pytest.mark.research_reuse


async def stored_counts(factory):
    async with factory() as session:
        return tuple([
            await session.scalar(select(func.count()).select_from(model))
            for model in (DocumentVersionRecord, TextUnitRecord, KnowledgeQuestionRow)
        ])


async def saved_questions(factory):
    old_attempt, old_set = await persisted_basis(factory)
    async with factory.begin() as session:
        await capture_answer_reviews(session, attempt_id=old_attempt, evidence_set_id=old_set)
        return dict((await session.execute(select(
            KnowledgeQuestionRow.display_text, KnowledgeQuestionRow.id,
        ))).all())


@pytest.mark.parametrize("question", [MAIN, CHILD], ids=["saved-main", "saved-child"])
@pytest.mark.parametrize("role", ["main", "child"], ids=["as-main", "as-child"])
async def test_saved_answer_skips_source_work_and_decomposition_in_either_role(
    reuse_db, no_source_work, question, role,
):
    canonical = (await saved_questions(reuse_db))[question]
    before = await stored_counts(reuse_db)
    expected_id = "research-main" if role == "main" else "child"
    forbidden = SimpleNamespace(
        plan_research=AsyncMock(side_effect=AssertionError("Unexpected decomposition")),
        plan_follow_ups=AsyncMock(side_effect=AssertionError("Unexpected follow-up")),
    )
    source = RecordingSource("swedish_preparatory_works")
    source.research = AsyncMock(side_effect=AssertionError("Unexpected source retrieval"))

    async def assessed(plan, items):
        assert [(row.id, row.question) for row in plan.needs] == [(expected_id, question)]
        assert items and all(item.provider == "graph_v2" for item in items)
        assert all(item.provenance.get("answer_fact_id") for item in items)
        assert {item.source_id for item in items} == {"prop-1976", "prop-1995"}
        assert all(item.provenance["previous_answer_status"] == "sufficient" for item in items)
        # Real SQL and only one connection: model work cannot retain that connection.
        async with reuse_db() as other:
            assert await other.scalar(text("SELECT 1")) == 1
        return await reviewed_answer(plan, items)

    adapter = SimpleNamespace(assess=AsyncMock(side_effect=assessed))
    inputs = (
        {"research_objective": ResearchObjective(question)} if role == "main"
        else {"research_plan": ResearchPlan(needs=[need(question=question)])}
    )
    async with reuse_db() as session:
        row = await attempt(session, objective=question)
        await session.commit()
        result = await execute_attempt_research(
            session, attempt_id=row.id, assessor=adapter, router=_router(source)[0],
            research_planner=forbidden, planner=forbidden,
            question_graph=SqlQuestionEvidenceGraph(), session_factory=reuse_db, **inputs,
        )
        runtime = await list_runtime_needs(session, row.id)
        items = await list_evidence_items(session, result.evidence_set_id)
        assert result.status == "ready"
        assert [(row.research_need_id, row.knowledge_question_id) for row in runtime] == [
            (expected_id, canonical),
        ]
        assert items and all(item.provenance.get("answer_fact_id") for item in items)
        assert {item.source_id for item in items} == {"prop-1976", "prop-1995"}
    assert adapter.assess.await_count >= 1
    assert await stored_counts(reuse_db) == before
    source.research.assert_not_awaited()
    forbidden.plan_research.assert_not_awaited()
    forbidden.plan_follow_ups.assert_not_awaited()
    for boundary in no_source_work.values():
        boundary.assert_not_called()
