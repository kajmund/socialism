"""Iterative KnowledgeQuestion-driven research: reuse, gaps, DAG, freeze."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    KnowledgeQuestionLineage,
    KnowledgeQuestionRow,
    TextUnitRecord,
)
from app.services.execution import (
    create_attempt,
    get_attempt,
    get_evidence_set,
    list_evidence_items,
    list_runtime_needs,
)
from app.services.knowledge.claims import (
    KnowledgeClaim,
    answer_research_need,
    knowledge_claim_id,
    persist_knowledge_claim,
    supersede_knowledge_claim,
)
from app.services.research.execution import execute_attempt_research
from app.services.research.knowledge_question import (
    identity_from_text,
    research_question_key,
    tenant_question_scope,
)
from app.services.research.models import ResearchPlan
from app.services.research.question_graph_memory import InMemoryQuestionEvidenceGraph
from app.services.research.question_iteration import (
    CanonicalOnlyQuestionResolver,
    collect_grounded_refs,
    list_question_children,
    match_canonical_question,
    record_question_lineage,
    resolve_or_create_knowledge_question,
)
from tests.test_research_assessment import RecordingAssessor, _fixed_draft
from tests.test_research_execution import RecordingSource, _created_attempt, _need, _router
from tests.test_research_loop import ScriptedPlanner, SequenceAssessor, _follow_up


ROOT_QUESTION = "What is the published rate?"
FOLLOW_UP_QUESTION = "Which source states the published rate?"


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session, factory
    await engine.dispose()


def _root_need(*source_types: str, need_id: str = "research_1") -> object:
    return _need(need_id, *source_types, question=ROOT_QUESTION)


async def _seed_claim(
    session: AsyncSession,
    *,
    customer_id: int,
    question: str,
    source_type: str,
    unit_text: str = "The published rate is 32 percent.",
    doc_id: str = "doc-rate",
) -> str:
    if await session.get(CanonicalDocumentRecord, doc_id) is None:
        session.add(
            CanonicalDocumentRecord(
                id=doc_id,
                customer_id=customer_id,
                source_type="upload",
                canonical_uri=f"doc://{doc_id}",
                title="Rate note",
                extra={},
            )
        )
        session.add(
            DocumentVersionRecord(
                id=f"ver-{doc_id}",
                document_id=doc_id,
                content_hash=f"hash-{doc_id}",
                mime_type="text/plain",
                extra={},
            )
        )
        session.add(
            TextUnitRecord(
                id=f"tu-{doc_id}",
                document_version_id=f"ver-{doc_id}",
                document_id=doc_id,
                section_id=None,
                ordinal=0,
                text=unit_text,
                content_hash=f"tu-{doc_id}",
            )
        )
        await session.flush()
    value: dict[str, object] = {"rate": 32}
    claim = KnowledgeClaim(
        id=knowledge_claim_id(
            document_version_id=f"ver-{doc_id}",
            predicate="core.published_rate",
            value=value,
        ),
        customer_id=customer_id,
        document_id=doc_id,
        document_version_id=f"ver-{doc_id}",
        predicate="core.published_rate",
        value=value,
        supporting_text_unit_ids=(f"tu-{doc_id}",),
    )
    await persist_knowledge_claim(session, claim)
    await answer_research_need(
        session,
        research_need_id=f"prior-{source_type}",
        question_key=research_question_key(question),
        claim_ids=[claim.id],
        source_type=source_type,
    )
    await session.flush()
    return claim.id


@pytest.mark.asyncio
async def test_root_question_creates_and_reuses_canonical_knowledge_question(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, run, first = await _created_attempt(session, slug="kq-root")
    result = await execute_attempt_research(
        session,
        attempt_id=first.id,
        research_plan=ResearchPlan(needs=[_root_need("case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        question_graph=graph,
    )
    identity = identity_from_text(ROOT_QUESTION)
    first_q = await match_canonical_question(
        session, ROOT_QUESTION, tenant_question_scope(customer.id)
    )
    assert result.status == "ready"
    assert first_q is not None
    assert first_q.identity_key == identity.identity_key
    needs = await list_runtime_needs(session, first.id)
    assert needs[0].knowledge_question_id == first_q.id

    second = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={"model": "config-a"},
        input_snapshot={"question": ROOT_QUESTION},
    )
    await execute_attempt_research(
        session,
        attempt_id=second.id,
        research_plan=ResearchPlan(needs=[_root_need("case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        question_graph=graph,
    )
    rows = list(
        (
            await session.execute(
                select(KnowledgeQuestionRow).where(
                    KnowledgeQuestionRow.customer_id == customer.id,
                    KnowledgeQuestionRow.identity_key == identity.identity_key,
                )
            )
        ).scalars()
    )
    assert [row.id for row in rows] == [first_q.id]
    reused = await list_runtime_needs(session, second.id)
    assert reused[0].knowledge_question_id == first_q.id


@pytest.mark.asyncio
async def test_fresh_grounded_claims_skip_matching_source_type(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, _run, attempt = await _created_attempt(session, slug="kq-fresh")
    await _seed_claim(
        session,
        customer_id=customer.id,
        question=ROOT_QUESTION,
        source_type="case_knowledge",
    )
    await session.commit()
    covered = RecordingSource("case_knowledge", excerpt="should not run")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_root_need("case_knowledge")]),
        router=_router(covered)[0],
        question_graph=graph,
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    assert covered.calls == 0
    assert items[0].provenance["knowledge_claim_ids"]
    assert items[0].provenance["reuse"]["origin"] == "persistent_knowledge"


@pytest.mark.asyncio
async def test_partial_coverage_retrieves_only_the_gap(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, _run, attempt = await _created_attempt(session, slug="kq-gap")
    await _seed_claim(
        session,
        customer_id=customer.id,
        question=ROOT_QUESTION,
        source_type="case_knowledge",
    )
    await session.commit()
    covered = RecordingSource("case_knowledge", excerpt="should not run")
    live = RecordingSource("web", excerpt="live web hit")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_root_need("case_knowledge", "web")]),
        router=_router(covered, live)[0],
        question_graph=graph,
    )
    excerpts = {item.excerpt for item in await list_evidence_items(session, result.evidence_set_id)}
    assert covered.calls == 0
    assert live.calls == 1
    assert "The published rate is 32 percent." in excerpts
    assert "live web hit" in excerpts


@pytest.mark.asyncio
async def test_follow_up_creates_child_knowledge_question_with_lineage(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, _run, attempt = await _created_attempt(session, slug="kq-child")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_root_need("case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        question_graph=graph,
        assessor=SequenceAssessor(
            [
                _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[]),
                _fixed_draft(result="sufficient", need_id="research_1", evidence_ids=[]),
            ]
        ),
        planner=ScriptedPlanner([[_follow_up(FOLLOW_UP_QUESTION)]]),
    )
    parent = await match_canonical_question(
        session, ROOT_QUESTION, tenant_question_scope(customer.id)
    )
    child = await match_canonical_question(
        session, FOLLOW_UP_QUESTION, tenant_question_scope(customer.id)
    )
    assert result.status == "ready"
    assert parent is not None and child is not None
    assert parent.id != child.id
    children = await list_question_children(session, parent.id)
    assert [(edge.child_question_id, edge.why_needed) for edge in children] == [
        (child.id, "lucka i bedömningen")
    ]
    derived = [row for row in await list_runtime_needs(session, attempt.id) if row.origin == "derived"]
    assert derived[0].knowledge_question_id == child.id
    assert derived[0].generated_from_question_id == parent.id


@pytest.mark.asyncio
async def test_same_follow_up_in_later_wave_reuses_child_and_edge(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, _run, attempt = await _created_attempt(session, slug="kq-dedupe")
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_root_need("case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        question_graph=graph,
        assessor=SequenceAssessor(
            [
                _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[]),
                _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[]),
                _fixed_draft(result="sufficient", need_id="research_1", evidence_ids=[]),
            ]
        ),
        planner=ScriptedPlanner(
            [
                [_follow_up(FOLLOW_UP_QUESTION)],
                [_follow_up(FOLLOW_UP_QUESTION)],
            ]
        ),
    )
    identity = identity_from_text(FOLLOW_UP_QUESTION)
    rows = list(
        (
            await session.execute(
                select(KnowledgeQuestionRow).where(
                    KnowledgeQuestionRow.customer_id == customer.id,
                    KnowledgeQuestionRow.identity_key == identity.identity_key,
                )
            )
        ).scalars()
    )
    assert len(rows) == 1
    parent = await match_canonical_question(
        session, ROOT_QUESTION, tenant_question_scope(customer.id)
    )
    assert parent is not None
    first = await record_question_lineage(
        session,
        parent_question_id=parent.id,
        child_question_id=rows[0].id,
        why_needed="lucka i bedömningen",
    )
    second = await record_question_lineage(
        session,
        parent_question_id=parent.id,
        child_question_id=rows[0].id,
        why_needed="another wave",
    )
    edges = list(
        (
            await session.execute(
                select(KnowledgeQuestionLineage).where(
                    KnowledgeQuestionLineage.parent_question_id == parent.id,
                    KnowledgeQuestionLineage.child_question_id == rows[0].id,
                )
            )
        ).scalars()
    )
    assert first is not None and second is not None
    assert first.parent_question_id == second.parent_question_id
    assert len(edges) == 1
    derived = [row for row in await list_runtime_needs(session, attempt.id) if row.origin == "derived"]
    assert len(derived) == 1


@pytest.mark.asyncio
async def test_already_answered_follow_up_does_not_fetch(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, _run, attempt = await _created_attempt(session, slug="kq-answered")
    await _seed_claim(
        session,
        customer_id=customer.id,
        question=FOLLOW_UP_QUESTION,
        source_type="case_knowledge",
        doc_id="doc-follow",
    )
    await session.commit()
    live = RecordingSource("case_knowledge", excerpt="root live")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_root_need("case_knowledge")]),
        router=_router(live)[0],
        question_graph=graph,
        assessor=RecordingAssessor(
            _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[])
        ),
        planner=ScriptedPlanner([[_follow_up(FOLLOW_UP_QUESTION)]]),
        max_follow_up_waves=2,
    )
    reloaded = await get_attempt(session, attempt.id)
    derived = [row for row in await list_runtime_needs(session, attempt.id) if row.origin == "derived"]
    assert result.status == "ready"
    assert derived == []
    assert live.calls == 1
    assert reloaded.research_stop_reason == "no_novel_followups"


@pytest.mark.asyncio
async def test_superseded_claim_reopens_gap(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, _run, attempt = await _created_attempt(session, slug="kq-stale")
    claim_id = await _seed_claim(
        session,
        customer_id=customer.id,
        question=ROOT_QUESTION,
        source_type="case_knowledge",
    )
    await supersede_knowledge_claim(session, claim_id)
    await session.commit()
    live = RecordingSource("case_knowledge", excerpt="replacement hit")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_root_need("case_knowledge")]),
        router=_router(live)[0],
        question_graph=graph,
    )
    excerpts = {item.excerpt for item in await list_evidence_items(session, result.evidence_set_id)}
    assert live.calls == 1
    assert "replacement hit" in excerpts


@pytest.mark.asyncio
async def test_two_runtime_needs_share_one_knowledge_question(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, _run, attempt = await _created_attempt(session, slug="kq-share")
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(
            needs=[
                _root_need("case_knowledge", need_id="research_1"),
                _root_need("web", need_id="research_2"),
            ]
        ),
        router=_router(
            RecordingSource("case_knowledge"),
            RecordingSource("web", excerpt="web rate"),
        )[0],
        question_graph=graph,
    )
    needs = await list_runtime_needs(session, attempt.id)
    assert {row.research_need_id for row in needs} == {"research_1", "research_2"}
    assert needs[0].knowledge_question_id
    assert needs[0].knowledge_question_id == needs[1].knowledge_question_id
    rows = list(
        (
            await session.execute(
                select(KnowledgeQuestionRow).where(
                    KnowledgeQuestionRow.customer_id == customer.id
                )
            )
        ).scalars()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_iteration_stops_when_completeness_is_reached(db):
    session, _factory = db
    planner = ScriptedPlanner([[_follow_up(FOLLOW_UP_QUESTION)]])
    result = await execute_attempt_research(
        session,
        attempt_id=(await _created_attempt(session, slug="kq-complete"))[2].id,
        research_plan=ResearchPlan(needs=[_root_need("case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        assessor=RecordingAssessor(),
        planner=planner,
        question_graph=InMemoryQuestionEvidenceGraph(),
    )
    reloaded = await get_attempt(session, result.attempt_id)
    assert result.status == "ready"
    assert reloaded.research_stop_reason == "sufficient"
    assert reloaded.research_wave == 0
    assert planner.calls == []


@pytest.mark.asyncio
async def test_max_iteration_guard_freezes_safely(db):
    session, _factory = db
    planner = ScriptedPlanner(
        [[_follow_up("Wave one gap")], [_follow_up("Wave two gap")]]
    )
    _customer, _run, attempt = await _created_attempt(session, slug="kq-max")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_root_need("case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        question_graph=InMemoryQuestionEvidenceGraph(),
        assessor=RecordingAssessor(
            _fixed_draft(result="insufficient", need_id="research_1", evidence_ids=[])
        ),
        planner=planner,
        max_follow_up_waves=1,
    )
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, result.evidence_set_id)
    assert result.status == "ready"
    assert reloaded.research_stop_reason == "max_iterations"
    assert evidence_set.status == "frozen"
    assert len(planner.calls) == 1


@pytest.mark.asyncio
async def test_frozen_evidence_set_keeps_grounded_provenance(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, _run, attempt = await _created_attempt(session, slug="kq-freeze")
    claim_id = await _seed_claim(
        session,
        customer_id=customer.id,
        question=ROOT_QUESTION,
        source_type="case_knowledge",
    )
    await session.commit()
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_root_need("case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        question_graph=graph,
    )
    evidence_set = await get_evidence_set(session, result.evidence_set_id)
    question = await match_canonical_question(
        session, ROOT_QUESTION, tenant_question_scope(customer.id)
    )
    assert evidence_set.status == "frozen"
    assert evidence_set.graph_revision_at_freeze is not None
    assert evidence_set.grounded_refs["knowledge_claim_ids"] == [claim_id]
    assert evidence_set.grounded_refs["document_version_ids"] == ["ver-doc-rate"]
    assert evidence_set.grounded_refs["text_unit_ids"] == ["tu-doc-rate"]
    assert question is not None
    assert question.id in evidence_set.grounded_refs["knowledge_question_ids"]


@pytest.mark.asyncio
async def test_domain_neutral_resolver_seam_does_not_cluster(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, _run, _attempt = await _created_attempt(session, slug="kq-neutral")
    scope = tenant_question_scope(customer.id)
    first = await resolve_or_create_knowledge_question(
        session,
        graph=graph,
        question="How is the metric defined?",
        scope=scope,
        relations=CanonicalOnlyQuestionResolver(),
    )
    second = await resolve_or_create_knowledge_question(
        session,
        graph=graph,
        question="How is the metric defined?",
        scope=scope,
        relations=CanonicalOnlyQuestionResolver(),
    )
    related = await CanonicalOnlyQuestionResolver().related_questions(
        normalized_text=first.normalized_text,
        identity_key=first.identity_key,
        scope=scope,
    )
    refs = collect_grounded_refs(
        question_ids=[first.id],
        items=[],
    )
    assert first.id == second.id
    assert related == []
    assert refs["knowledge_question_ids"] == [first.id]
    assert "legal" not in first.normalized_text


@pytest.mark.asyncio
async def test_cycle_guard_refuses_parent_child_loop(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, _run, _attempt = await _created_attempt(session, slug="kq-cycle")
    scope = tenant_question_scope(customer.id)
    parent = await resolve_or_create_knowledge_question(
        session, graph=graph, question=ROOT_QUESTION, scope=scope
    )
    child = await resolve_or_create_knowledge_question(
        session, graph=graph, question=FOLLOW_UP_QUESTION, scope=scope
    )
    created = await record_question_lineage(
        session,
        parent_question_id=parent.id,
        child_question_id=child.id,
        why_needed="expand",
    )
    looped = await record_question_lineage(
        session,
        parent_question_id=child.id,
        child_question_id=parent.id,
        why_needed="loop",
    )
    assert created is not None
    assert looped is None
    assert await list_question_children(session, child.id) == []
