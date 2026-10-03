"""A sufficient Graph answer ends research before any source ingestion work."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, text

from app.database.answer_review import KnowledgeAnswerReview
from app.database.models import DocumentVersionRecord, KnowledgeQuestionRow, TextUnitRecord
from app.services.execution import list_evidence_items, list_runtime_needs
from app.services.research.execution import execute_attempt_research
from tests.research_reuse.helpers import MAIN, attempt, objective, reviewed_answer
from tests.test_research_graph_v2_reuse import Embeddings
from tests.test_research_question_evidence import RecordingSource, _router

pytestmark = pytest.mark.research_reuse


async def _stored_source_counts(factory):
    async with factory() as session:
        return tuple(
            [await session.scalar(select(func.count()).select_from(model))
             for model in (DocumentVersionRecord, TextUnitRecord)]
        )


async def _execute(factory, source, assessor, forbidden_planners):
    async with factory() as session:
        row = await attempt(session)
        await session.commit()
        result = await execute_attempt_research(
            session, attempt_id=row.id, research_objective=objective(),
            research_planner=forbidden_planners, planner=forbidden_planners,
            completeness_reviewer=forbidden_planners, assessor=assessor,
            router=_router(source)[0], session_factory=factory,
        )
        needs = await list_runtime_needs(session, row.id)
        items = await list_evidence_items(session, result.evidence_set_id)
        assert result.status == "ready"
        assert [(need.research_need_id, need.question) for need in needs] == [("research-main", MAIN)]
        assert items and all(item.provider == "graph_v2" for item in items)
        assert all(item.source_id == "doc-customer-1" for item in items)
        assert all(item.provenance["document_version_id"] == "version-customer-1" for item in items)
        return bool(row.input_snapshot.get("research_result_reuse"))


async def test_sufficient_main_knowledge_and_saved_answer_skip_all_source_work(
    graph_basis, monkeypatch, no_source_work,
):
    embedding = Embeddings()
    embedding.embed = AsyncMock(wraps=embedding.embed)
    monkeypatch.setattr("app.services.research.composition.research_embeddings", lambda: embedding)

    async def assessed(plan, items):
        assert [need.question for need in plan.needs] == [MAIN]
        assert items and all(item.provider == "graph_v2" for item in items)
        # The production read path must return its only connection before assessment.
        async with graph_basis() as other:
            assert await other.scalar(text("SELECT 1")) == 1
        return await reviewed_answer(plan, items)

    assessor = SimpleNamespace(assess=AsyncMock(side_effect=assessed))
    forbidden = SimpleNamespace(
        plan_research=AsyncMock(side_effect=AssertionError("Unexpected decomposition")),
        plan_follow_ups=AsyncMock(side_effect=AssertionError("Unexpected follow-up")),
        review=AsyncMock(side_effect=AssertionError("Already assessed")),
    )
    source = RecordingSource("swedish_preparatory_works")
    source.research = AsyncMock(side_effect=AssertionError("Unexpected source retrieval"))
    counts = await _stored_source_counts(graph_basis)

    for saved_answer in (False, True):
        reused = await _execute(graph_basis, source, assessor, forbidden)
        assert reused is saved_answer
        assert await _stored_source_counts(graph_basis) == counts

    assert assessor.assess.await_count == 1
    # Query embeddings are permitted. No document text may be embedded on this path.
    assert [call.args[0] for call in embedding.embed.await_args_list] == [[MAIN]]
    source.research.assert_not_awaited()
    for boundary in no_source_work.values():
        boundary.assert_not_called()
    forbidden.plan_research.assert_not_awaited()
    forbidden.plan_follow_ups.assert_not_awaited()
    forbidden.review.assert_not_awaited()
    async with graph_basis() as session:
        assert await session.scalar(select(func.count()).select_from(KnowledgeQuestionRow)) == 1
        # Reuse captures the same review version without resetting its TTL lifecycle.
        reviews = list(await session.scalars(select(KnowledgeAnswerReview)))
        assert len(reviews) == 1 and reviews[0].status == "awaiting_ttl"
