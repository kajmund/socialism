from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.database.answer_review import KnowledgeAnswerReview
from app.services.execution import (
    add_evidence_items,
    attach_evidence_set,
    create_evidence_set,
    persist_research_assessment,
    persist_runtime_needs,
    freeze_evidence_set,
)
from app.services.research.answer_review import capture_answer_reviews
from app.services.research.assessment import ResearchAssessmentDraft, ResearchNeedAssessment
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.knowledge_question import identity_from_text
from tests.research_reuse.helpers import MAIN, attempt, evidence, need
from tests.research_reuse.probes import capture

pytestmark = pytest.mark.research_reuse


async def persisted_basis(factory, *, sufficient=True, sources=("prop-1976", "prop-1995")):
    async with factory.begin() as session:
        row = await attempt(session)
        evidence_set = await create_evidence_set(session, run_id=row.run_id)
        await attach_evidence_set(session, attempt_id=row.id, evidence_set_id=evidence_set.id)
        await persist_runtime_needs(
            session,
            attempt_id=row.id,
            needs=[
                RuntimeResearchNeed(
                    research_need_id="child",
                    question=need().question,
                    why_needed="Gap",
                    source_types=need().source_types,
                ),
                RuntimeResearchNeed(
                    research_need_id="research-main",
                    question=MAIN,
                    why_needed="Main",
                    source_types=need().source_types,
                ),
            ],
        )
        await add_evidence_items(
            session,
            evidence_set_id=evidence_set.id,
            items=[evidence(source_id=ref) for ref in sources],
        )
        await persist_research_assessment(
            session,
            attempt_id=row.id,
            evidence_set_id=evidence_set.id,
            evidence_fingerprint="two-sources",
            draft=ResearchAssessmentDraft(
                result="sufficient" if sufficient else "insufficient",
                rationale="Basis review",
                need_assessments=[
                    ResearchNeedAssessment(
                        research_need_id="child",
                        sufficient=sufficient,
                        supporting_evidence_ids=[
                            evidence(source_id=ref).evidence_id
                            for ref in sources
                        ],
                    ),
                    ResearchNeedAssessment(
                        research_need_id="research-main",
                        sufficient=sufficient,
                        supporting_evidence_ids=[
                            evidence(source_id=ref).evidence_id
                            for ref in sources
                        ],
                    ),
                ],
            ),
        )
        await freeze_evidence_set(session, evidence_set.id)
        return row.id, evidence_set.id


@pytest.mark.parametrize("sufficient", [True, False], ids=["complete", "partial"])
async def test_answer_basis_keeps_all_sources_and_actual_sufficiency(reuse_db, sufficient):
    attempt_id, set_id = await persisted_basis(reuse_db, sufficient=sufficient)
    async with reuse_db.begin() as session:
        await capture_answer_reviews(session, attempt_id=attempt_id, evidence_set_id=set_id)
        row = await session.scalar(
            select(KnowledgeAnswerReview).where(
                KnowledgeAnswerReview.question_key != identity_from_text(MAIN).identity_key
            )
        )
        assert {item["source_id"] for item in row.answer_basis["evidence"]} == {
            "prop-1976",
            "prop-1995",
        }
        assert row.answer_basis["assessments"][0]["sufficient"] is sufficient
        original_id = row.id
        await capture_answer_reviews(session, attempt_id=attempt_id, evidence_set_id=set_id)
        assert original_id in list(await session.scalars(select(KnowledgeAnswerReview.id)))
        assert len(list(await session.scalars(select(KnowledgeAnswerReview.id)))) == 2


async def test_live_capture_probe_rolls_back_its_real_database_writes(reuse_db):
    attempt_id, _set_id = await persisted_basis(reuse_db)
    result = await capture(reuse_db, attempt_id)
    assert set(result["captured_questions"]) == {need().question, MAIN}
    assert result["writes"] == "rolled_back"
    async with reuse_db() as session:
        assert list(await session.scalars(select(KnowledgeAnswerReview))) == []


async def test_main_question_has_a_complete_reusable_answer_basis(reuse_db):
    attempt_id, set_id = await persisted_basis(reuse_db)
    async with reuse_db() as session:
        captured = await capture_answer_reviews(
            session, attempt_id=attempt_id, evidence_set_id=set_id
        )
        assert MAIN in [question for _key, question in captured]


async def test_main_answer_is_projected_for_the_next_research(reuse_db):
    attempt_id, _set_id = await persisted_basis(reuse_db)
    result = await capture(reuse_db, attempt_id)
    assert result["contract_passed"], result


@pytest.mark.parametrize("main_question", [MAIN, "Hur bedöms avtalsvillkor enligt paragraf 36?"])
async def test_a_second_research_reuses_the_whole_assessed_main_answer(reuse_db, main_question, result_jev):
    from app.database.graph_v2 import GraphFact, GraphNode
    from app.services.execution import list_runtime_needs, list_evidence_items
    from app.services.research import execute_attempt_research
    from app.services.research.planner import (
        FakeResearchPlanner,
        ResearchNeedDraft,
        ResearchObjective,
    )
    from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
    from tests.research_reuse.helpers import FreshSource, reviewed_answer, objective
    from tests.test_research_question_evidence import _router

    source = FreshSource()
    adapter = SimpleNamespace(assess=AsyncMock(side_effect=reviewed_answer))
    drafts = [
        ResearchNeedDraft(
            question=question, why_needed="Missing aspect", source_types=need().source_types
        )
        for question in [need().question, "Vilka rättsfall är vägledande för 36 §?"]
    ]
    initial = FakeResearchPlanner(drafts)
    graph = SqlQuestionEvidenceGraph()
    async with reuse_db() as session:
        first = await attempt(session)
        await session.commit()
        completed = await execute_attempt_research(
            session,
            attempt_id=first.id,
            research_objective=objective(),
            research_planner=initial,
            router=_router(source)[0],
            assessor=adapter,
            question_graph=graph,
            session_factory=reuse_db,
        )
        assert completed.status == "ready"
        assert len(source.questions) == 2
        canonical = next(
            row.knowledge_question_id
            for row in await list_runtime_needs(session, first.id)
            if row.research_need_id == "research-main"
        )
        facts_before = list(
            await session.scalars(
                select(GraphFact).where(GraphFact.predicate == "research.answered_by")
            )
        )
        assert facts_before, [
            (r.research_need_id, r.question_key)
            for r in await list_runtime_needs(session, first.id)
        ]
        await session.commit()
        from app.services.research.graph_lookup import lookup_question
        from tests.research_reuse.helpers import context

        direct = await lookup_question(
            reuse_db, need(question=MAIN, need_id="research-main", question_id=canonical), context()
        )
        assert direct, [(f.attributes, f.source_id, f.target_id) for f in facts_before]

    class SemanticBoundary:
        embedding_metadata = ("mock", "v1", 3)

        async def index(self, _rows):
            pass

        async def match(self, *, normalized_text, identity_key, candidates):
            if normalized_text == main_question.casefold() and main_question != MAIN:
                return next((row for row in candidates if row.id == canonical), None)
            return None

    new_source = FreshSource()
    no_decomposition = FakeResearchPlanner(drafts)
    sole_judgment = SimpleNamespace(assess=AsyncMock(side_effect=reviewed_answer))
    no_second_review = SimpleNamespace(
        review=AsyncMock(side_effect=AssertionError("Main objective already assessed"))
    )
    async with reuse_db() as session:
        second = await attempt(session, objective=main_question)
        await session.commit()
        result = await execute_attempt_research(
            session,
            attempt_id=second.id,
            research_objective=ResearchObjective(main_question),
            research_planner=no_decomposition,
            router=_router(new_source)[0],
            assessor=sole_judgment,
            completeness_reviewer=no_second_review,
            question_graph=SqlQuestionEvidenceGraph(matcher=SemanticBoundary()),
            session_factory=reuse_db,
        )
        runtime = await list_runtime_needs(session, second.id)
        assert result.status == "ready"
        assert len(runtime) == 1 and runtime[0].knowledge_question_id == canonical
        assert new_source.questions == [] and no_decomposition.calls == []
        assert sole_judgment.assess.await_count == 0
        assert result.evidence_set_id == completed.evidence_set_id
        no_second_review.review.assert_not_awaited()
        items = await list_evidence_items(session, result.evidence_set_id)
        assert {item.source_id for item in items if item.source_type != "derived"} == {
            "source:research_1",
            "source:research_2",
        }
        # Source provenance remains the original provider on the shared frozen set.
        assert all(item.provider == "mock-public-source" for item in items if item.source_type != "derived")
        await session.commit()
        answers = list(
            await session.scalars(select(GraphNode).where(GraphNode.node_type == "research.answer"))
        )
        assert any(row.attributes["assessment"]["sufficient"] for row in answers)
        assert (
            len(
                list(
                    await session.scalars(
                        select(GraphFact).where(GraphFact.predicate == "research.answered_by")
                    )
                )
            )
            >= 3
        )


@pytest.mark.parametrize("sufficient", [True, False])
async def test_graph_answer_preserves_status_all_sources_and_context(reuse_db, sufficient):
    from dataclasses import replace
    from app.database.graph_v2 import GraphFact, GraphNode
    from app.database.models import KnowledgeQuestionRow
    from app.services.research.graph_lookup import lookup_question
    from tests.research_reuse.helpers import context

    attempt_id, set_id = await persisted_basis(reuse_db, sufficient=sufficient)
    async with reuse_db.begin() as session:
        await capture_answer_reviews(session, attempt_id=attempt_id, evidence_set_id=set_id)
        canonical = await session.scalar(
            select(KnowledgeQuestionRow).where(KnowledgeQuestionRow.display_text == MAIN)
        )
        nodes = list(
            await session.scalars(select(GraphNode).where(GraphNode.node_type == "research.answer"))
        )
        main = next(row for row in nodes if row.name == MAIN)
        assert main.attributes["assessment"]["sufficient"] is sufficient
        assert len(main.attributes["basis"]) == 2
        assert main.attributes["assessment"]["needs"][0]["supporting_evidence_ids"]
        first_ids = set(
            await session.scalars(
                select(GraphFact.id).where(GraphFact.predicate == "research.answered_by")
            )
        )
        await capture_answer_reviews(session, attempt_id=attempt_id, evidence_set_id=set_id)
        assert (
            set(
                await session.scalars(
                    select(GraphFact.id).where(GraphFact.predicate == "research.answered_by")
                )
            )
            == first_ids
        )
        canonical_id = canonical.id
    question = need(question=MAIN, question_id=canonical_id)
    correct = context()
    items = await lookup_question(reuse_db, question, correct)
    assert {item.source_id for item in items} == {"prop-1976", "prop-1995"}
    assert all(
        item.metadata["previous_answer_status"] == ("sufficient" if sufficient else "partial")
        for item in items
    )
    for forbidden in [
        context(customer_id=2),
        context(case_id="other-case"),
        replace(correct, scope=replace(correct.scope, module="politik")),
    ]:
        assert await lookup_question(reuse_db, question, forbidden) == []


async def test_an_expired_source_cannot_be_hidden_by_a_fresh_answer_episode(reuse_db, monkeypatch):
    from datetime import datetime, UTC, timedelta
    from app.config import settings
    from app.database.models import KnowledgeQuestionRow
    from app.services.research.graph_reuse import lookup_graph_evidence
    from tests.research_reuse.helpers import context

    attempt_id, set_id = await persisted_basis(reuse_db)
    async with reuse_db.begin() as session:
        await capture_answer_reviews(session, attempt_id=attempt_id, evidence_set_id=set_id)
        canonical = await session.scalar(
            select(KnowledgeQuestionRow).where(KnowledgeQuestionRow.display_text == MAIN)
        )
        canonical_id = canonical.id
    monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 60)
    async with reuse_db() as session:
        items = await lookup_graph_evidence(
            session,
            need=need(question=MAIN, question_id=canonical_id),
            context=context(),
            now=datetime.now(UTC) + timedelta(seconds=61),
        )
    assert items == []


async def test_main_answer_keeps_more_sources_than_the_fact_search_limit(reuse_db, monkeypatch):
    from app.config import settings
    from app.database.models import KnowledgeQuestionRow
    from app.services.research.graph_lookup import lookup_question
    from tests.research_reuse.helpers import context

    sources = [f"original:{index}" for index in range(12)]
    attempt_id, set_id = await persisted_basis(reuse_db, sources=sources)
    async with reuse_db.begin() as session:
        await capture_answer_reviews(session, attempt_id=attempt_id, evidence_set_id=set_id)
        canonical_id = await session.scalar(
            select(KnowledgeQuestionRow.id).where(KnowledgeQuestionRow.display_text == MAIN)
        )
    monkeypatch.setattr(settings, "research_knowledge_lookup_limit", 1)
    items = await lookup_question(reuse_db, need(question=MAIN, question_id=canonical_id), context())
    assert {item.source_id for item in items} == set(sources)


async def test_graph_answer_preserves_original_text_and_legal_interpretation(reuse_db):
    from dataclasses import replace
    from app.database.models import KnowledgeQuestionRow
    from app.services.research.graph_lookup import lookup_question
    from tests.research_reuse.helpers import context
    from tests.test_legal_research_result import _result

    legal = _result()
    async with reuse_db.begin() as session:
        row = await attempt(session)
        evidence_set = await create_evidence_set(session, run_id=row.run_id)
        await attach_evidence_set(session, attempt_id=row.id, evidence_set_id=evidence_set.id)
        await persist_runtime_needs(
            session,
            attempt_id=row.id,
            needs=[RuntimeResearchNeed(
                research_need_id="research-main", question=MAIN, why_needed="Main",
                source_types=["swedish_law"],
            )],
        )
        await add_evidence_items(
            session, evidence_set_id=evidence_set.id,
            items=[replace(evidence(need_id="research-main"), source_type="swedish_law", legal_result=legal)],
        )
        await freeze_evidence_set(session, evidence_set.id)
        await capture_answer_reviews(session, attempt_id=row.id, evidence_set_id=evidence_set.id)
        canonical_id = await session.scalar(
            select(KnowledgeQuestionRow.id).where(KnowledgeQuestionRow.display_text == MAIN)
        )
    items = await lookup_question(
        reuse_db,
        replace(need(question=MAIN, question_id=canonical_id), source_types=["swedish_law"]),
        context(),
    )
    assert items[0].legal_result == legal
    assert items[0].legal_result.raw_text == legal.raw_text
    assert items[0].legal_result.statute.citations == legal.statute.citations
