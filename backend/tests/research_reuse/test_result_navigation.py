"""Near-question reuse, bounded traversal, partial answers and fail-closed Jev."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text

from app.database.graph_v2 import GraphNode
from app.jev.system import JevClientError
from app.services.research import execute_attempt_research
from app.services.research.planner import ResearchObjective
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.result_judge import Coverage
from app.services.research.result_search import MAX_EDGES, find_completed_research
from tests.research_reuse.helpers import MAIN, attempt, context, need
from tests.research_reuse.test_completed_result import ready_result, counts
from tests.research_reuse.result_helpers import mock_result_jev
from tests.test_research_question_evidence import RecordingSource, _router

pytestmark = pytest.mark.research_reuse
ALIAS = "Hur används 36 § avtalslagen av svenska domstolar?"


async def test_reused_dag_question_keeps_requested_identity_and_one_card(
    reuse_db, result_jev, monkeypatch
):
    from app.api.execution import get_attempt_research_overview
    from app.database.models import ExecutionAttempt, ResearchQuestion
    from app.services.research.question_attempt_worker import AttemptResearchQuestionWorker
    from app.services.research.question_domain import (
        GeneralQuestionDraft,
        create_general_question,
        create_specific_question,
    )
    from app.services.research.question_execution import ExecutableResearchQuestion

    await ready_result(reuse_db)
    forbidden = AsyncMock(
        side_effect=AssertionError("Cached result must not republish expert knowledge")
    )
    monkeypatch.setattr(
        "app.services.research.question_attempt_worker.publish_research_question_knowledge",
        forbidden,
    )
    async with reuse_db.begin() as session:
        parent = await attempt(session)
        specific = await create_specific_question(
            session, run_id=parent.run_id, text="Avtalslagen", context={}, origin_kind="api"
        )
        general = await create_general_question(
            session,
            attempt_id=parent.id,
            specific_question_id=specific.id,
            draft=GeneralQuestionDraft(
                question=ALIAS, why_needed="Identifierad lucka", assigned_expert_id="expert"
            ),
        )
        incoming = ExecutableResearchQuestion(
            id=general.id,
            attempt_id=parent.id,
            specific_question_id=specific.id,
            knowledge_question_id=general.knowledge_question_id,
            question=ALIAS,
            why_needed=general.why_needed,
            depth=0,
            raised_by_expert_ids=(),
            assigned_expert_id="expert",
        )
    source = RecordingSource("swedish_preparatory_works")
    source.research = AsyncMock(side_effect=AssertionError("No source fetch on full reuse"))
    worker = AttemptResearchQuestionWorker(
        session_factory=reuse_db,
        router_factory=lambda _session: _router(source)[0],
        research_planner=SimpleNamespace(
            plan_research=AsyncMock(side_effect=AssertionError("No decomposition on full reuse"))
        ),
    )
    outcome = await worker.research_question(incoming)
    assert outcome.follow_ups == ()
    forbidden.assert_not_awaited()
    async with reuse_db.begin() as session:
        row = await session.get(ResearchQuestion, incoming.id)
        row.status = "completed"
        child = await session.get(ExecutionAttempt, outcome.execution_attempt_id)
        assert (
            child.input_snapshot["research_result_reuse"]["knowledge_question_id"]
            == incoming.knowledge_question_id
        )
    async with reuse_db() as session:
        overview = await get_attempt_research_overview(
            incoming.attempt_id, session=session, user=SimpleNamespace(role="admin", kund_id=None)
        )
        assert len(overview.questions) == 1
        assert (
            overview.questions[0].status == "answered"
            and overview.questions[0].need_assessment.sufficient
        )


async def test_partial_result_only_fetches_assessed_gap(reuse_db, monkeypatch):
    from app.services.research.assessment import ResearchAssessmentDraft, ResearchNeedAssessment
    from app.services.research.followup import FollowUpNeedDraft
    from app.services.research.planner import FakeResearchPlanner
    from tests.research_reuse.helpers import FreshSource, reviewed_answer

    mock_result_jev(monkeypatch, reuse_db, outcome="PARTIAL")
    await ready_result(reuse_db)
    gap = "Vilka nya avgöranden om 36 § har tillkommit?"

    async def assess(plan, items):
        if all(item.provider == "graph_v2" for item in items):
            assert items, "Saved partial evidence must reach sufficiency assessment"
            return ResearchAssessmentDraft(
                result="insufficient",
                rationale="Nya avgöranden saknas",
                need_assessments=[
                    ResearchNeedAssessment(
                        research_need_id=plan.needs[0].id,
                        sufficient=False,
                        missing_or_weak="Nya avgöranden saknas",
                    )
                ],
                gaps=["Nya avgöranden saknas"],
            )
        return await reviewed_answer(plan, items)

    async def gaps(**kwargs):
        assert kwargs["evidence"] and kwargs["assessment"].result == "insufficient"
        return [
            FollowUpNeedDraft(
                question=gap,
                why_needed="Nya avgöranden saknas",
                source_gap="Nya avgöranden saknas",
                source_types=need().source_types,
                parent_research_need_id="research-main",
            )
        ]

    source = FreshSource()
    initial = FakeResearchPlanner([])
    async with reuse_db() as session:
        row = await attempt(session, objective=ALIAS)
        await session.commit()
        result = await execute_attempt_research(
            session,
            attempt_id=row.id,
            research_objective=ResearchObjective(ALIAS),
            router=_router(source)[0],
            session_factory=reuse_db,
            research_planner=initial,
            assessor=SimpleNamespace(assess=AsyncMock(side_effect=assess)),
            planner=SimpleNamespace(plan_follow_ups=AsyncMock(side_effect=gaps)),
            question_graph=SqlQuestionEvidenceGraph(),
        )
        assert "research_result_reuse" not in row.input_snapshot
    assert result.status == "ready" and initial.calls == []
    assert source.questions == [gap]


async def test_near_question_uses_jev_and_original_snapshot(reuse_db, result_jev, no_source_work):
    previous, frozen = await ready_result(reuse_db)
    before = await counts(reuse_db)
    source = RecordingSource("swedish_preparatory_works")
    source.research = AsyncMock(side_effect=AssertionError("No source retrieval"))
    assessor = SimpleNamespace(
        assess=AsyncMock(side_effect=AssertionError("Jev already established full coverage"))
    )
    async with reuse_db() as session:
        row = await attempt(session, objective=ALIAS)
        await session.commit()
        result = await execute_attempt_research(
            session,
            attempt_id=row.id,
            research_objective=ResearchObjective(ALIAS),
            assessor=assessor,
            router=_router(source)[0],
            session_factory=reuse_db,
            question_graph=SqlQuestionEvidenceGraph(),
        )
        assert result.status == "ready" and result.evidence_set_id == frozen
        ref = row.input_snapshot["research_result_reuse"]
        assert ref["match"] == "nearby" and ref["source_attempt_id"] == previous
        assert ref["coverage"]["outcome"] == "FULL"
    assert result_jev.await_count >= 2
    assert await counts(reuse_db) == before
    for boundary in no_source_work.values():
        boundary.assert_not_called()


@pytest.mark.parametrize("outcome,confidence", [("PARTIAL", 0.99), ("NONE", 0.99), ("FULL", 0.5)])
async def test_similarity_does_not_override_partial_or_uncertain_coverage(
    reuse_db, monkeypatch, outcome, confidence
):
    mock_result_jev(monkeypatch, reuse_db, outcome=outcome, confidence=confidence)
    await ready_result(reuse_db)
    found = await find_completed_research(
        reuse_db, need(question=ALIAS), context(), {"objective": {}, "run": {}}
    )
    assert found.answer is None
    assert any(saved.question == MAIN for saved in found.partial) is (outcome == "PARTIAL")


async def test_jev_error_propagates_without_alternate_model_or_writes(reuse_db, monkeypatch):
    client = mock_result_jev(monkeypatch, reuse_db)
    client.side_effect = JevClientError("429", category="rate_limit")
    await ready_result(reuse_db)
    before = await counts(reuse_db)
    with pytest.raises(JevClientError, match="429"):
        await find_completed_research(
            reuse_db, need(question=ALIAS), context(), {"objective": {}, "run": {}}
        )
    assert await counts(reuse_db) == before


async def test_cancelled_jev_returns_the_only_connection(reuse_db, monkeypatch):
    client = mock_result_jev(monkeypatch, reuse_db)
    entered = asyncio.Event()

    async def pending(**_kwargs):
        entered.set()
        await asyncio.Event().wait()

    client.side_effect = pending
    await ready_result(reuse_db)
    task = asyncio.create_task(
        find_completed_research(
            reuse_db, need(question=ALIAS), context(), {"objective": {}, "run": {}}
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=2)
    async with reuse_db() as session:
        assert await session.scalar(text("SELECT 1")) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with reuse_db() as session:
        assert await session.scalar(text("SELECT 1")) == 1


async def test_cycle_is_bounded_and_low_relevance_does_not_prune_other_seeds(reuse_db):
    from app.services.graph_v2.questions import question_node
    from app.services.graph_v2.types import FactInput, SourceRef
    from app.services.graph_v2.write import resolve_fact
    from app.services.research.result_search import ResultSearch, _traverse
    from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
    from app.services.research.knowledge_question import identity_from_text, tenant_question_scope
    from app.database.models import KnowledgeQuestionRow

    await ready_result(reuse_db)
    async with reuse_db.begin() as session:
        graph = SqlQuestionEvidenceGraph()
        seed = await graph.upsert_question(
            session, identity_from_text("Other 36 § branch"), tenant_question_scope(1)
        )
        other = await question_node(session, await session.get(KnowledgeQuestionRow, seed.id))
        answered = await session.scalar(
            select(GraphNode).where(GraphNode.name == MAIN, GraphNode.node_type == "core.question")
        )
        for source, target in ((other, answered), (answered, other)):
            await resolve_fact(
                session,
                FactInput(
                    source_id=source.id,
                    target_id=target.id,
                    predicate="research.decomposed_to",
                    scope=tenant_question_scope(1).tenant,
                    fact_text="related questions",
                    sources=(SourceRef("episode", "test-cycle"),),
                ),
            )
        seeds = [other.id, answered.id]
    visits = []

    async def navigate(_need, _context, edges):
        visits.extend(edge["id"] for edge in edges)
        # Ignore the first branch; the independently seeded answer remains discoverable.
        return {edge["id"] for edge in edges if edge["predicate"] == "research.answered_by"}

    judge = SimpleNamespace(
        navigate=AsyncMock(side_effect=navigate),
        covers=AsyncMock(return_value=Coverage("FULL", 0.99, "mock")),
    )
    found = ResultSearch()
    await _traverse(
        reuse_db,
        need(question=ALIAS),
        context(),
        {"objective": {}, "run": {}},
        frontier=seeds,
        judge=judge,
        result=found,
    )
    assert found.answer is not None
    assert len(visits) == len(set(visits)) <= MAX_EDGES


@pytest.mark.parametrize("key", ["research.result_navigation", "research.result_coverage"])
async def test_empty_database_seeds_result_prompts(client_db, key):
    import json
    from app.services.prompt_fields_store import get_prompt_field_by_key

    _client, factory = client_db
    async with factory() as session:
        field = await get_prompt_field_by_key(session, key)
        assert field.active and {"dd", "politik", "expertgranskning"} <= set(field.modules)
        for value in (field.default_sv, field.default_en, field.default_nb):
            question = json.loads(value)
            assert question["type"] in {"choice", "noul"}


async def test_embeddings_do_not_merge_canonical_question_identity(monkeypatch):
    from app.services.research.composition import build_standard_question_graph
    from app.services.research.knowledge_question import ExactQuestionIdentityMatcher

    graph = build_standard_question_graph()
    assert isinstance(graph._matcher, ExactQuestionIdentityMatcher)
