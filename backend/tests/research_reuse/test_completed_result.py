"""Completed-result reuse contracts: constant writes, temporal guards and UI reads."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, func, select

from app.database.graph_v2 import GraphFact, GraphNode
from app.database.models import (
    EvidenceSet,
    EvidenceSetItem,
    ExecutionAttempt,
    ResearchAssessment,
    ResearchProgressEvent,
    ResearchRuntimeNeed,
)
from app.services.execution import list_runtime_needs, list_research_assessments
from app.services.research import ResearchPlan, execute_attempt_research
from app.services.research.answer_review import capture_answer_reviews
from app.services.research.planner import ResearchObjective
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.result_search import find_completed_research
from tests.research_reuse.helpers import CHILD, MAIN, attempt, context, need
from tests.research_reuse.test_04_main_answer import persisted_basis
from tests.test_research_question_evidence import RecordingSource, _router

pytestmark = pytest.mark.research_reuse


async def ready_result(factory, *, sources=("prop-1976", "prop-1995")):
    previous, frozen = await persisted_basis(factory, sources=sources)
    async with factory.begin() as session:
        row = await session.get(ExecutionAttempt, previous)
        row.status = "ready"
        await capture_answer_reviews(session, attempt_id=previous, evidence_set_id=frozen)
    return previous, frozen


@pytest.mark.parametrize("when", ["before-lookup", "during-lookup"])
async def test_lost_worker_lease_does_not_bind_saved_result(reuse_db, monkeypatch, when):
    import asyncio
    from app.services.research.result_search import find_completed_research

    await ready_result(reuse_db)
    lost = asyncio.Event()
    if when == "before-lookup":
        lost.set()

    async def lookup(*args, **kwargs):
        result = await find_completed_research(*args, **kwargs)
        lost.set()
        return result

    monkeypatch.setattr("app.services.research.result_execution.find_completed_research", lookup)
    async with reuse_db() as session:
        row = await attempt(session)
        await session.commit()
        row_id = row.id
        with pytest.raises(asyncio.CancelledError):
            await execute_attempt_research(
                session,
                attempt_id=row_id,
                research_objective=ResearchObjective(MAIN),
                lease_lost=lost,
                router=_router(RecordingSource("swedish_preparatory_works"))[0],
                session_factory=reuse_db,
            )
    async with reuse_db() as session:
        row = await session.get(ExecutionAttempt, row_id)
        assert row.status == "created" and row.evidence_set_id is None


async def counts(factory):
    async with factory() as session:
        return tuple(
            [
                await session.scalar(select(func.count()).select_from(model))
                for model in (
                    EvidenceSet,
                    EvidenceSetItem,
                    GraphFact,
                    GraphNode,
                    ResearchAssessment,
                    ResearchRuntimeNeed,
                    ResearchProgressEvent,
                )
            ]
        )


async def test_context_identity_preserves_specific_material_and_ignores_new_ids(reuse_db):
    from app.services.research.question_domain import create_specific_question
    from app.services.research.result_store import meaningful_context

    async with reuse_db.begin() as session:
        row = await attempt(session)
        contexts = []
        for index, material in enumerate(("same", "same", "changed")):
            specific = await create_specific_question(
                session,
                run_id=row.run_id,
                text="Samma fråga",
                context={"contract": material},
                origin_kind="api",
            )
            contexts.append(
                await meaningful_context(
                    session,
                    ResearchObjective(
                        MAIN,
                        context={
                            "specific_question_id": specific.id,
                            "research_question_id": str(index),
                            "knowledge_question_id": str(index),
                            "assigned_expert_id": str(index),
                        },
                    ),
                )
            )
        assert contexts[0] == contexts[1]
        assert contexts[0] != contexts[2]


@pytest.mark.parametrize("question", [MAIN, CHILD], ids=["main-answer", "subquestion-answer"])
@pytest.mark.parametrize("role", ["main", "subquestion"])
async def test_exact_result_reuses_same_snapshot_with_one_update(
    reuse_db, no_source_work, monkeypatch, *, question, role
):
    _previous, frozen = await ready_result(reuse_db, sources=[f"source-{i}" for i in range(77)])
    before = await counts(reuse_db)
    forbidden = SimpleNamespace(
        assess=AsyncMock(side_effect=AssertionError("No assessment on exact reuse")),
        plan_research=AsyncMock(side_effect=AssertionError("No decomposition on exact reuse")),
        plan_follow_ups=AsyncMock(side_effect=AssertionError("No gap planning on exact reuse")),
    )
    monkeypatch.setattr(
        "app.services.research.result_search._nearby",
        AsyncMock(side_effect=AssertionError("No embedding/Jev on exact reuse")),
    )
    source = RecordingSource("swedish_preparatory_works")
    source.research = AsyncMock(side_effect=AssertionError("No source retrieval"))
    async with reuse_db() as session:
        row = await attempt(session, objective=question)
        await session.commit()
        writes = []

        def track(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        engine = reuse_db.kw["bind"].sync_engine
        event.listen(engine, "before_cursor_execute", track)
        try:
            result = await execute_attempt_research(
                session,
                attempt_id=row.id,
                research_objective=ResearchObjective(question),
                research_plan=ResearchPlan(needs=[need(question=question)])
                if role == "subquestion"
                else None,
                research_planner=forbidden,
                assessor=forbidden,
                planner=forbidden,
                router=_router(source)[0],
                question_graph=SqlQuestionEvidenceGraph(),
                session_factory=reuse_db,
            )
        finally:
            event.remove(engine, "before_cursor_execute", track)
        assert result.status == "ready" and result.evidence_set_id == frozen
        assert len(writes) == 1 and "UPDATE execution_attempts" in writes[0]
        runtime = await list_runtime_needs(session, row.id)
        assessment = await list_research_assessments(session, row.id)
        assert len(runtime) == len(assessment) == 1
        assert runtime[0].question == question
        assert assessment[0].result == "sufficient"
        assert len(assessment[0].need_assessments[0]["supporting_evidence_ids"]) == 77
    assert await counts(reuse_db) == before
    for boundary in no_source_work.values():
        boundary.assert_not_called()


@pytest.mark.parametrize(
    "guard",
    [
        "invalidated-answer",
        "invalidated-dependency",
        "expired-source",
        "wrong-case",
        "wrong-customer",
    ],
)
async def test_invalid_or_other_scope_result_is_not_reused(reuse_db, monkeypatch, guard):
    from datetime import UTC, datetime
    from app.config import settings
    from app.services.research.answer_graph import ANSWER_PREDICATE

    await ready_result(reuse_db)
    if guard.startswith("invalidated"):
        async with reuse_db.begin() as session:
            answer = await session.scalar(
                select(GraphFact)
                .join(GraphNode, GraphNode.id == GraphFact.target_id)
                .where(GraphFact.predicate == ANSWER_PREDICATE, GraphNode.name == MAIN)
            )
            if guard == "invalidated-answer":
                answer.status = "invalidated"
                answer.invalid_at = datetime.now(UTC)
            else:
                node = await session.get(GraphNode, answer.target_id)
                value = deepcopy(node.attributes)
                value["basis"][0]["metadata"]["graph_fact_ids"] = ["missing-or-invalidated-fact"]
                node.attributes = value
    if guard == "expired-source":
        monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 0)
    judge = SimpleNamespace(navigate=AsyncMock(return_value=set()), covers=AsyncMock())
    scope = (
        context(customer_id=2)
        if guard == "wrong-customer"
        else context(case_id="other")
        if guard == "wrong-case"
        else context()
    )
    found = await find_completed_research(
        reuse_db, need(question=MAIN), scope, {"objective": {}, "run": {}}, judge=judge
    )
    assert found.answer is None
    judge.covers.assert_not_awaited()


async def test_api_can_read_cross_run_frozen_result_without_new_rows(reuse_db):
    from app.api.execution import (
        get_execution_attempt,
        get_execution_run_attempts,
        get_attempt_research_overview,
    )

    await ready_result(reuse_db)
    source = RecordingSource("swedish_preparatory_works")
    async with reuse_db() as session:
        row = await attempt(session)
        await session.commit()
        await execute_attempt_research(
            session,
            attempt_id=row.id,
            research_objective=ResearchObjective(MAIN),
            router=_router(source)[0],
            question_graph=SqlQuestionEvidenceGraph(),
            session_factory=reuse_db,
        )
        row_id, run_id = row.id, row.run_id
        before = await counts_after_release(session, reuse_db)
        user = SimpleNamespace(role="admin", kund_id=None)
        output = await get_execution_attempt(row_id, session=session, user=user)
        assert output.status == "ready" and output.assessment.result == "sufficient"
        listed = await get_execution_run_attempts(run_id, session=session, user=user)
        assert (
            listed[0].assessment.result == "sufficient"
            and listed[0].runtime_needs[0].question == MAIN
        )
        overview = await get_attempt_research_overview(row_id, session=session, user=user)
        assert len(overview.questions) == 1 and overview.questions[0].status == "answered"
        assert overview.questions[0].source_count == 2
        await session.rollback()
    assert await counts(reuse_db) == before


async def counts_after_release(session, factory):
    await session.rollback()
    return await counts(factory)


async def test_ttl_candidate_keeps_valid_result_and_original_review_clock(reuse_db):
    from datetime import UTC, datetime, timedelta
    from app.database.answer_review import KnowledgeAnswerReview

    await ready_result(reuse_db)
    due = datetime.now(UTC) - timedelta(days=1)
    async with reuse_db.begin() as session:
        review = await session.scalar(
            select(KnowledgeAnswerReview).where(KnowledgeAnswerReview.question == MAIN)
        )
        review.status, review.ttl, review.review_after = "candidate", "soon", due
        previous_clock = review.created_at
    found = await find_completed_research(
        reuse_db, need(question=MAIN), context(), {"objective": {}, "run": {}}
    )
    assert found.match == "exact"
    async with reuse_db() as session:
        review = await session.scalar(
            select(KnowledgeAnswerReview).where(KnowledgeAnswerReview.question == MAIN)
        )
        assert review.status == "candidate" and review.created_at == previous_clock
        assert review.review_after.replace(tzinfo=UTC) == due


async def test_live_probe_uses_production_lookup_and_performs_no_research_writes(
    reuse_db, tmp_path
):
    from tests.research_reuse.result_live import run
    from app.services.research.plan import research_plan_to_snapshot

    old, frozen = await ready_result(reuse_db)
    async with reuse_db.begin() as session:
        row = await session.get(ExecutionAttempt, old)
        row.research_plan_snapshot = research_plan_to_snapshot(
            ResearchPlan(needs=[need(question=MAIN)])
        )
    before = await counts(reuse_db)
    output = tmp_path / "timings.json"
    result = await run(
        SimpleNamespace(attempt_id=old, need_id=None, question=None, repeat=2, output=str(output)),
        factory=reuse_db,
    )
    assert [row["match"] for row in result["measurements"]] == ["exact", "exact"]
    assert all(row["evidence_set_id"] == frozen for row in result["measurements"])
    assert output.exists() and await counts(reuse_db) == before
