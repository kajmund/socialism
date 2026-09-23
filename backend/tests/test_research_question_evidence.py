"""Question → Evidence graph seam. Does not add a second research engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.database.models import Kund
from app.services.execution import (
    create_attempt,
    create_run,
    get_attempt,
    list_evidence_items,
    list_need_executions,
    list_runtime_needs,
)
from app.services.research import (
    ResearchNeed,
    ResearchPlan,
    ResearchRouter,
    ResearchSourceRegistry,
    execute_attempt_research,
    research_evidence,
)
from app.services.research.assessment import (
    ResearchAssessmentDraft,
    ResearchNeedAssessment,
)
from app.services.research.execution import research_context_from_run
from app.services.research.graphiti_adapter import (
    GraphitiQuestionEvidenceGraph,
    InMemoryGraphitiClient,
    UnavailableGraphitiClient,
    link_from_graphiti_edge,
    link_to_graphiti_edge,
)
from app.services.research.knowledge_question import (
    evidence_visibility,
    identity_from_text,
    knowledge_question_identity_key,
    public_question_scope,
    stable_evidence_ref,
    tenant_question_scope,
)
from app.services.research.question_graph import (
    ANSWERED_BY,
    QuestionEvidenceGraphError,
    QuestionEvidenceLink,
)
from app.services.research.question_graph_memory import InMemoryQuestionEvidenceGraph
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.question_reuse import (
    classify_freshness,
    should_skip_providers,
    upsert_persisted_evidence,
)


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


async def _customer(session: AsyncSession, slug: str) -> Kund:
    kund = Kund(name=slug, slug=slug, available_modules=["dd"])
    session.add(kund)
    await session.flush()
    return kund


def _need(
    need_id: str,
    *source_types: str,
    question: str = "Vad gäller skattesatsen?",
) -> ResearchNeed:
    return ResearchNeed(
        id=need_id,
        question=question,
        why_needed="behövs för bedömning",
        requested_by=["legal"],
        source_types=list(source_types),  # type: ignore[arg-type]
    )


class RecordingSource:
    def __init__(
        self,
        source_type: str,
        *,
        excerpt: str = "skattesats 32%",
        public: bool = False,
        locator: str = "p1",
    ) -> None:
        self.source_type = source_type
        self.provider_id = "fake"
        self.excerpt = excerpt
        self.public = public
        self.locator = locator
        self.calls = 0

    async def research(self, need: ResearchNeed, context):
        del context
        self.calls += 1
        metadata: dict[str, object] = {
            "document_id": "doc-brief",
            "version": "3",
        }
        if self.public:
            metadata["public"] = True
        return [
            research_evidence(
                research_need_id=need.id,
                source_type=self.source_type,  # type: ignore[arg-type]
                status="found",
                title="Kommunens skattesats",
                excerpt=self.excerpt,
                locator=self.locator,
                source_id="doc-brief",
                source_url="https://example.test/brief.pdf",
                provider="fake",
                retrieved_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
                metadata=metadata,
            )
        ]


def _router(*sources: RecordingSource) -> tuple[ResearchRouter, list[RecordingSource]]:
    registry = ResearchSourceRegistry()
    for source in sources:
        registry.register(source)
    return ResearchRouter(registry), list(sources)


async def _created_attempt(
    session: AsyncSession,
    *,
    slug: str,
    customer: Kund | None = None,
    case_id: str = "case-1",
    module: str = "dd",
):
    kund = customer or await _customer(session, slug)
    run = await create_run(
        session,
        customer_id=kund.id,
        module=module,
        title="Skattesats",
        context={"case_id": case_id},
    )
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={"model": "config-a"},
        input_snapshot={"question": "Vad gäller skattesatsen?"},
    )
    return kund, run, attempt


def test_equivalent_runtime_questions_share_identity_key():
    left = knowledge_question_identity_key("Vad gäller skattesatsen?")
    right = knowledge_question_identity_key("  vad   gäller SKATTESATSEN?  ")
    assert left == right
    assert identity_from_text("Vad gäller skattesatsen?").identity_key == left


def test_evidence_visibility_is_public_only_when_provenance_says_so():
    assert evidence_visibility({"public": True}) == "public"
    assert evidence_visibility({"visibility": "public"}) == "public"
    assert evidence_visibility({"source_type": "swedish_law"}) == "tenant"
    assert evidence_visibility({}) == "tenant"


def test_v1_reuse_gate_never_skips_providers():
    need = _need("research_1", "case_knowledge")
    fresh = research_evidence(
        research_need_id="research_1",
        source_type="case_knowledge",
        status="found",
        excerpt="current",
        metadata={"reuse": {"origin": "persistent_knowledge", "freshness": "fresh"}},
    )
    assert should_skip_providers(need, [fresh]) is False
    assert should_skip_providers(need, []) is False


def test_freshness_unknown_when_max_age_is_absent():
    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    observed = now - timedelta(seconds=10)
    assert classify_freshness(observed_at=observed, retrieved_at=observed, now=now) == "unknown"
    assert (
        classify_freshness(
            observed_at=observed,
            retrieved_at=observed,
            now=now,
            max_age_seconds=60,
        )
        == "fresh"
    )
    assert (
        classify_freshness(
            observed_at=observed - timedelta(hours=2),
            retrieved_at=None,
            now=now,
            max_age_seconds=60,
        )
        == "stale"
    )


@pytest.mark.asyncio
async def test_later_attempt_reuses_candidates_without_duplicate_edges(db, monkeypatch):
    monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 86_400)
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, run, first = await _created_attempt(session, slug="reuse-co")
    source = RecordingSource("case_knowledge")
    router, _ = _router(source)
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])

    first_result = await execute_attempt_research(
        session,
        attempt_id=first.id,
        research_plan=plan,
        router=router,
        question_graph=graph,
    )
    second = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={"model": "config-a"},
        input_snapshot={"question": "Vad gäller skattesatsen?"},
    )
    second_result = await execute_attempt_research(
        session,
        attempt_id=second.id,
        research_plan=plan,
        router=router,
        question_graph=graph,
    )

    identity = identity_from_text("Vad gäller skattesatsen?")
    tenant_q = await graph.match_question(session, identity, tenant_question_scope(customer.id))
    assert tenant_q is not None
    links = await graph.lookup_answers(session, question=tenant_q, limit=10)
    first_items = await list_evidence_items(session, first_result.evidence_set_id)
    second_items = await list_evidence_items(session, second_result.evidence_set_id)

    assert first_result.status == second_result.status == "ready"
    assert source.calls == 2
    assert len(graph.questions()) == 1
    assert len(links) == 1
    assert first_items[0].locator == "p1"
    assert {item.provenance["reuse"]["origin"] for item in second_items} == {"fresh_retrieval"}
    assert second_items[0].locator == first_items[0].locator
    assert second_items[0].provenance["version"] == "3"
    assert second_items[0].provenance["document_id"] == "doc-brief"


@pytest.mark.asyncio
async def test_stale_reused_evidence_still_calls_providers(db, monkeypatch):
    monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 1)
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    identity = identity_from_text("Vad gäller skattesatsen?")
    customer, _run, attempt = await _created_attempt(session, slug="stale-co")
    question = await graph.upsert_question(session, identity, tenant_question_scope(customer.id))
    await graph.upsert_answer(
        session,
        QuestionEvidenceLink(
            question_id=question.id,
            evidence_ref="old-ref",
            excerpt="old excerpt",
            locator="p-old",
            source_id="doc-old",
            source_type="case_knowledge",
            provider="fake",
            retrieved_at=datetime(2020, 1, 1, tzinfo=UTC),
            observed_at=datetime(2020, 1, 1, tzinfo=UTC),
            freshness="stale",
            visibility="tenant",
        ),
    )
    source = RecordingSource("case_knowledge", excerpt="live hit")
    router, _ = _router(source)
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=router,
        question_graph=graph,
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    origins = {item.provenance.get("reuse", {}).get("origin") for item in items}
    excerpts = {item.excerpt for item in items}
    assert source.calls == 1
    assert origins == {"fresh_retrieval"}
    assert excerpts == {"live hit"}


@pytest.mark.asyncio
async def test_private_tenant_evidence_cannot_cross_customers(db, monkeypatch):
    monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 86_400)
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    first_customer, _run, first = await _created_attempt(session, slug="acme")
    source_a = RecordingSource("case_knowledge", excerpt="acme secret")
    await execute_attempt_research(
        session,
        attempt_id=first.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(source_a)[0],
        question_graph=graph,
    )
    second_customer, _run_b, second = await _created_attempt(session, slug="beta")
    source_b = RecordingSource("case_knowledge", excerpt="beta live")
    result = await execute_attempt_research(
        session,
        attempt_id=second.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(source_b)[0],
        question_graph=graph,
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    tenant_a = await graph.match_question(
        session,
        identity_from_text("Vad gäller skattesatsen?"),
        tenant_question_scope(first_customer.id),
    )
    tenant_b = await graph.match_question(
        session,
        identity_from_text("Vad gäller skattesatsen?"),
        tenant_question_scope(second_customer.id),
    )
    assert tenant_a is not None and tenant_b is not None
    assert tenant_a.id != tenant_b.id
    assert [item.excerpt for item in items] == ["beta live"]
    assert source_b.calls == 1
    assert all("acme secret" not in (item.excerpt or "") for item in items)


@pytest.mark.asyncio
async def test_public_evidence_is_reusable_across_customers(db, monkeypatch):
    monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 86_400)
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    _first_customer, _run, first = await _created_attempt(session, slug="pub-a")
    await execute_attempt_research(
        session,
        attempt_id=first.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "swedish_law")]),
        router=_router(RecordingSource("swedish_law", public=True, excerpt="SFS text"))[0],
        question_graph=graph,
    )
    _second, _run_b, second = await _created_attempt(session, slug="pub-b")
    source_b = RecordingSource("swedish_law", public=True, excerpt="should not run")
    result = await execute_attempt_research(
        session,
        attempt_id=second.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "swedish_law")]),
        router=_router(source_b)[0],
        question_graph=graph,
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    public_q = await graph.match_question(
        session,
        identity_from_text("Vad gäller skattesatsen?"),
        public_question_scope(),
    )
    assert public_q is not None
    assert public_q.scope.visibility == "public"
    assert source_b.calls == 1
    excerpts = {item.excerpt for item in items}
    assert excerpts == {"SFS text", "should not run"}
    origins = {item.provenance["reuse"]["origin"] for item in items}
    assert origins == {"fresh_retrieval", "persistent_knowledge"}


@pytest.mark.asyncio
async def test_graph_outage_falls_back_to_provider_retrieval(db):
    session, _factory = db
    _customer_row, _run, attempt = await _created_attempt(session, slug="outage-co")
    source = RecordingSource("case_knowledge")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(source)[0],
        question_graph=GraphitiQuestionEvidenceGraph(UnavailableGraphitiClient()),
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    assert result.status == "ready"
    assert source.calls == 1
    assert items[0].status == "found"
    assert items[0].provenance["reuse"]["origin"] == "fresh_retrieval"


@pytest.mark.asyncio
async def test_graphiti_round_trip_keeps_locator_and_provenance():
    client = InMemoryGraphitiClient()
    graph = GraphitiQuestionEvidenceGraph(client)
    identity = identity_from_text("Vad gäller skattesatsen?")
    question = await graph.upsert_question(
        None,  # type: ignore[arg-type]
        identity,
        tenant_question_scope(9),
    )
    ref = stable_evidence_ref(
        provider="fake",
        source_id="doc-brief",
        locator="§ 4",
        excerpt="excerpt",
    )
    stored = await graph.upsert_answer(
        None,  # type: ignore[arg-type]
        QuestionEvidenceLink(
            question_id=question.id,
            evidence_ref=ref,
            excerpt="excerpt",
            locator="§ 4",
            source_id="doc-brief",
            source_url="https://example.test/brief.pdf",
            source_type="case_knowledge",
            provider="fake",
            provenance={"document_id": "doc-brief", "version": "3"},
            retrieved_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
            observed_at=datetime(2026, 4, 1, 12, 1, tzinfo=UTC),
            freshness="fresh",
            version="3",
            visibility="tenant",
        ),
    )
    again = await graph.upsert_answer(
        None,  # type: ignore[arg-type]
        QuestionEvidenceLink(
            question_id=question.id,
            evidence_ref=ref,
            excerpt="excerpt",
            locator="§ 4",
            source_id="doc-brief",
            provider="fake",
            provenance={"document_id": "doc-brief", "version": "3"},
            freshness="fresh",
            visibility="tenant",
        ),
    )
    links = await graph.lookup_answers(None, question=question, limit=5)  # type: ignore[arg-type]
    edge = link_to_graphiti_edge(stored)
    restored = link_from_graphiti_edge(edge)
    assert stored.evidence_ref == again.evidence_ref == ref
    assert len(links) == 1
    assert links[0].locator == "§ 4"
    assert links[0].provenance["version"] == "3"
    assert links[0].relation == ANSWERED_BY
    assert restored.locator == "§ 4"
    assert restored.provenance["document_id"] == "doc-brief"


@pytest.mark.asyncio
async def test_retry_upsert_is_idempotent(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    _customer_row, _run, attempt = await _created_attempt(session, slug="retry-id")
    source = RecordingSource("case_knowledge")
    router, _ = _router(source)
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    first = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=plan,
        router=router,
        question_graph=graph,
    )
    ready = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=plan,
        router=router,
        question_graph=graph,
    )
    identity = identity_from_text("Vad gäller skattesatsen?")
    question = await graph.match_question(
        session, identity, tenant_question_scope(_customer_row.id)
    )
    assert question is not None
    links = await graph.lookup_answers(session, question=question, limit=10)
    items = await list_evidence_items(session, first.evidence_set_id)
    assert first.status == ready.status == "ready"
    assert first.evidence_set_id == ready.evidence_set_id
    assert source.calls == 1
    assert len(links) == 1
    assert len(items) == 1


@pytest.mark.asyncio
async def test_existing_runtime_contracts_keep_reuse_lineage_only(db):
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    _customer_row, _run, attempt = await _created_attempt(session, slug="contract-co")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge"))[0],
        question_graph=graph,
    )
    reloaded = await get_attempt(session, attempt.id)
    runtime = await list_runtime_needs(session, attempt.id)
    executions = await list_need_executions(session, attempt.id)
    items = await list_evidence_items(session, result.evidence_set_id)
    assert result.status == "ready"
    assert reloaded.status == "ready"
    assert [row.research_need_id for row in runtime] == ["research_1"]
    assert runtime[0].question == "Vad gäller skattesatsen?"
    assert {row.status for row in executions} == {"completed"}
    assert items[0].provenance["reuse"]["origin"] == "fresh_retrieval"
    assert items[0].provenance["reuse"]["relation"] == ANSWERED_BY
    assert items[0].locator == "p1"


@pytest.mark.asyncio
async def test_unavailable_graphiti_client_raises_graph_error():
    client = UnavailableGraphitiClient()
    with pytest.raises(QuestionEvidenceGraphError):
        await client.find_nodes(labels=("KnowledgeQuestion",), attributes={}, limit=1)


@pytest.mark.asyncio
async def test_sql_graph_reuses_across_attempts(db, monkeypatch):
    monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 86_400)
    session, _factory = db
    graph = SqlQuestionEvidenceGraph()
    _customer_row, run, first = await _created_attempt(session, slug="sql-reuse")
    source = RecordingSource("case_knowledge")
    router, _ = _router(source)
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    await execute_attempt_research(
        session,
        attempt_id=first.id,
        research_plan=plan,
        router=router,
        question_graph=graph,
    )
    second = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={"model": "config-a"},
        input_snapshot={"question": "Vad gäller skattesatsen?"},
    )
    result = await execute_attempt_research(
        session,
        attempt_id=second.id,
        research_plan=plan,
        router=router,
        question_graph=graph,
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    identity = identity_from_text("Vad gäller skattesatsen?")
    question = await graph.match_question(
        session, identity, tenant_question_scope(_customer_row.id)
    )
    assert question is not None
    links = await graph.lookup_answers(session, question=question, limit=10)
    assert result.status == "ready"
    assert source.calls == 2
    assert len(links) == 1
    assert items[0].provenance["reuse"]["origin"] == "fresh_retrieval"


class _FailingWriteGraph(InMemoryQuestionEvidenceGraph):
    async def upsert_answer(self, session, link):
        raise SQLAlchemyError("unique constraint")


@pytest.mark.asyncio
async def test_reused_web_hit_does_not_satisfy_swedish_law_need(db, monkeypatch):
    monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 86_400)
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    _customer, run, first = await _created_attempt(session, slug="src-filter")
    await execute_attempt_research(
        session,
        attempt_id=first.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "web")]),
        router=_router(RecordingSource("web", excerpt="web hit"))[0],
        question_graph=graph,
    )
    second = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={"model": "config-a"},
        input_snapshot={"question": "Vad gäller skattesatsen?"},
    )
    law = RecordingSource("swedish_law", excerpt="SFS live")
    result = await execute_attempt_research(
        session,
        attempt_id=second.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "swedish_law")]),
        router=_router(law)[0],
        question_graph=graph,
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    assert law.calls == 1
    assert [item.excerpt for item in items] == ["SFS live"]
    assert items[0].source_type == "swedish_law"


@pytest.mark.asyncio
async def test_case_knowledge_does_not_reuse_across_cases(db, monkeypatch):
    monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 86_400)
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    customer, _run, first = await _created_attempt(session, slug="case-scope", case_id="case-a")
    await execute_attempt_research(
        session,
        attempt_id=first.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge", excerpt="case a secret"))[0],
        question_graph=graph,
    )
    _same, _run_b, second = await _created_attempt(
        session, slug="case-b", customer=customer, case_id="case-b"
    )
    live = RecordingSource("case_knowledge", excerpt="case b live")
    result = await execute_attempt_research(
        session,
        attempt_id=second.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(live)[0],
        question_graph=graph,
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    assert live.calls == 1
    assert [item.excerpt for item in items] == ["case b live"]


@pytest.mark.asyncio
async def test_reused_hit_does_not_refresh_edge_timestamps(db, monkeypatch):
    monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 86_400)
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    _customer, run, first = await _created_attempt(session, slug="fresh-stamp")
    need = _need("research_1", "case_knowledge")
    await execute_attempt_research(
        session,
        attempt_id=first.id,
        research_plan=ResearchPlan(needs=[need]),
        router=_router(RecordingSource("case_knowledge"))[0],
        question_graph=graph,
    )
    before = graph.links()[0]
    reused = research_evidence(
        research_need_id="research_1",
        source_type="case_knowledge",
        status="found",
        excerpt="skattesats 32%",
        locator="p1",
        source_id="doc-brief",
        provider="fake",
        metadata={
            "reuse": {
                "origin": "persistent_knowledge",
                "evidence_ref": before.evidence_ref,
                "freshness": "fresh",
            }
        },
    )
    await upsert_persisted_evidence(
        session,
        graph=graph,
        need=need,
        context=research_context_from_run(run),
        evidence=[reused],
        source_attempt_id=first.id,
    )
    after = graph.links()[0]
    assert len(graph.links()) == 1
    assert after.observed_at == before.observed_at
    assert after.retrieved_at == before.retrieved_at
    assert after.freshness == before.freshness


class _InsufficientAssessor:
    async def assess(self, plan, evidence):
        return ResearchAssessmentDraft(
            result="insufficient",
            rationale="configured policy rejects thin reused excerpt",
            need_assessments=[
                ResearchNeedAssessment(
                    research_need_id=plan.needs[0].id,
                    sufficient=False,
                    missing_or_weak="reused excerpt is insufficient",
                    further_information=plan.needs[0].question,
                )
            ],
            gaps=["thin reuse"],
            considered_evidence_ids=[item.evidence_id for item in evidence],
        )


@pytest.mark.asyncio
async def test_insufficient_assessor_does_not_let_fresh_reuse_skip_providers(db, monkeypatch):
    monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 86_400)
    session, _factory = db
    graph = InMemoryQuestionEvidenceGraph()
    _customer, run, first = await _created_attempt(session, slug="no-skip-policy")
    await execute_attempt_research(
        session,
        attempt_id=first.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(RecordingSource("case_knowledge", excerpt="thin cache"))[0],
        question_graph=graph,
    )
    second = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={"model": "config-a"},
        input_snapshot={"question": "Vad gäller skattesatsen?"},
    )
    live = RecordingSource("case_knowledge", excerpt="live retrieval")
    result = await execute_attempt_research(
        session,
        attempt_id=second.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(live)[0],
        question_graph=graph,
        assessor=_InsufficientAssessor(),
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    excerpts = {item.excerpt for item in items}
    assert live.calls == 1
    assert "live retrieval" in excerpts
    assert "thin cache" in excerpts


@pytest.mark.asyncio
async def test_failed_graph_write_does_not_fail_ready_attempt(db):
    session, _factory = db
    _customer, _run, attempt = await _created_attempt(session, slug="write-fail")
    source = RecordingSource("case_knowledge")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=_router(source)[0],
        question_graph=_FailingWriteGraph(),
    )
    items = await list_evidence_items(session, result.evidence_set_id)
    assert result.status == "ready"
    assert source.calls == 1
    assert items[0].status == "found"


@pytest.mark.parametrize("current", [False, True])
async def test_question_reuse_requires_current_legal_interpretation_version(current):
    from types import SimpleNamespace

    from app.services.legal_research_result import LEGAL_RESULT_SCHEMA_VERSION
    from app.services.research.question_reuse import lookup_reusable_evidence
    from tests.test_legal_research_result import _result
    from tests.test_research import _context

    result = _result()
    record = SimpleNamespace(domain="legal", schema_version=LEGAL_RESULT_SCHEMA_VERSION if current else LEGAL_RESULT_SCHEMA_VERSION - 1,
                             result=result.model_dump(exclude={"raw_text"}), raw_source=SimpleNamespace(raw_text=result.raw_text))

    class Session:
        async def get(self, model, key):
            return record

    session = Session()
    graph = InMemoryQuestionEvidenceGraph()
    need = _need("n1", "swedish_law")
    question = await graph.upsert_question(session, identity_from_text(need.question), tenant_question_scope(7))
    await graph.upsert_answer(session, QuestionEvidenceLink(question_id=question.id, evidence_ref="e1", source_type="swedish_law", excerpt="fordran preskriberas", provenance={"domain_result_id": "d1"}))
    reused = await lookup_reusable_evidence(session, graph=graph, need=need, context=_context())
    assert bool(reused) == current
