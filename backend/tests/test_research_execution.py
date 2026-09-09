"""Attempt → ResearchPlan → ResearchRouter → EvidenceSet → ready."""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import EvidenceSet, ExecutionAttempt, Kund
from app.services.execution import (
    ExecutionFrozenError,
    ExecutionStatusError,
    add_evidence_items,
    attach_evidence_set,
    claim_attempt_researching,
    create_attempt,
    create_evidence_set,
    create_run,
    fail_attempt,
    get_attempt,
    get_evidence_set,
    list_evidence_items,
    mark_researching,
    start_attempt,
)
from app.services.research import (
    InvalidResearchPlanError,
    ResearchContext,
    ResearchExecutionError,
    ResearchNeed,
    ResearchPlan,
    ResearchRouter,
    ResearchSourceRegistry,
    execute_attempt_research,
    research_context_from_run,
    research_evidence,
    research_plan_from_snapshot,
)
from app.services.research.models import research_evidence as build_evidence

EXECUTION_PY = (
    Path(__file__).resolve().parents[1] / "app" / "services" / "research" / "execution.py"
)
PLAN_PY = Path(__file__).resolve().parents[1] / "app" / "services" / "research" / "plan.py"

_FORBIDDEN_IMPORT_PREFIXES = (
    "app.services.panel",
    "app.services.rattsunderlag",
    "app.services.expertgranskning",
    "app.llm",
    "app.api",
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
        mode: str = "found",
        excerpt: str = "skattesats 32%",
        error: Exception | None = None,
    ) -> None:
        self.source_type = source_type
        self.provider_id = "fake"
        self.mode = mode
        self.excerpt = excerpt
        self.error = error
        self.calls = 0
        self.contexts: list[ResearchContext] = []

    async def research(self, need: ResearchNeed, context: ResearchContext):
        self.calls += 1
        self.contexts.append(context)
        if self.error is not None:
            raise self.error
        if self.mode == "empty":
            return []
        return [
            research_evidence(
                research_need_id=need.id,
                source_type=self.source_type,  # type: ignore[arg-type]
                status="found",
                title="Kommunens skattesats",
                excerpt=self.excerpt,
                locator="p1",
                source_id="doc-brief",
                source_url="https://example.test/brief.pdf",
                provider="fake",
                score=0.91,
                retrieved_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
                metadata={
                    "document_id": "doc-brief",
                    "version": "3",
                    "content_hash": f"seen-{need.id}",
                },
            )
        ]


class RaisingRouter:
    async def execute_need(self, need: ResearchNeed, context: ResearchContext):
        raise RuntimeError("router exploded")


class GuardRouter:
    async def execute_need(self, need: ResearchNeed, context: ResearchContext):
        raise AssertionError("empty plan must not call the router")


def _router(*sources: RecordingSource) -> tuple[ResearchRouter, list[RecordingSource]]:
    registry = ResearchSourceRegistry()
    for source in sources:
        registry.register(source)
    return ResearchRouter(registry), list(sources)


async def _created_attempt(session: AsyncSession, *, slug: str = "acme", **context):
    customer = await _customer(session, slug)
    run = await create_run(
        session,
        customer_id=customer.id,
        module="dd",
        title="Skattesats",
        context={"case_id": "case-1", **context},
    )
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={"model": "config-a"},
        input_snapshot={"question": "Vad gäller skattesatsen?"},
    )
    return customer, run, attempt


@pytest.mark.asyncio
async def test_acceptance_found_and_not_found_reach_ready(db):
    session, _factory = db
    customer, run, attempt = await _created_attempt(session)
    found = RecordingSource("case_knowledge", excerpt="skattesats 32%")
    missing = RecordingSource("customer_knowledge", mode="empty")
    router, _ = _router(found, missing)
    plan = ResearchPlan(
        needs=[
            _need("research_1", "case_knowledge"),
            _need("research_2", "customer_knowledge", question="Finns kundpolicy?"),
        ]
    )

    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=plan,
        router=router,
    )

    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, reloaded.evidence_set_id)
    items = await list_evidence_items(session, evidence_set.id)
    items_by_need = {row.research_need_id: row for row in items}

    assert result.status == "ready"
    assert result.found_count == 1
    assert result.not_found_count == 1
    assert result.error_count == 0
    assert result.evidence_set_id == reloaded.evidence_set_id
    assert reloaded.status == "ready"
    assert reloaded.research_plan_snapshot == {
        "needs": [
            {
                "id": "research_1",
                "question": "Vad gäller skattesatsen?",
                "why_needed": "behövs för bedömning",
                "requested_by": ["legal"],
                "source_types": ["case_knowledge"],
            },
            {
                "id": "research_2",
                "question": "Finns kundpolicy?",
                "why_needed": "behövs för bedömning",
                "requested_by": ["legal"],
                "source_types": ["customer_knowledge"],
            },
        ]
    }
    assert research_plan_from_snapshot(reloaded.research_plan_snapshot).needs[0].id == (
        "research_1"
    )
    assert evidence_set.status == "frozen"
    assert evidence_set.created_from_attempt_id == attempt.id
    assert evidence_set.run_id == run.id
    assert [row.ordinal for row in sorted(items, key=lambda row: row.ordinal)] == [0, 1]
    assert items_by_need["research_1"].status == "found"
    assert items_by_need["research_1"].excerpt == "skattesats 32%"
    assert items_by_need["research_1"].locator == "p1"
    assert items_by_need["research_1"].original_evidence_id
    assert items_by_need["research_1"].content_hash == "seen-research_1"
    assert items_by_need["research_1"].provenance["version"] == "3"
    assert items_by_need["research_1"].provenance["document_id"] == "doc-brief"
    assert items_by_need["research_2"].status == "not_found"
    assert found.contexts[0].scope.customer_id == customer.id
    assert found.contexts[0].scope.module == "dd"
    assert found.contexts[0].scope.case_id == "case-1"
    assert customer.id == run.customer_id


@pytest.mark.asyncio
async def test_empty_plan_freezes_empty_set_and_is_ready(db):
    session, _factory = db
    _customer_row, _run, attempt = await _created_attempt(session, slug="empty-co")
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(),
        router=GuardRouter(),  # type: ignore[arg-type]
    )
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, reloaded.evidence_set_id)
    assert result.status == "ready"
    assert result.found_count == result.not_found_count == result.error_count == 0
    assert reloaded.status == "ready"
    assert reloaded.research_plan_snapshot == {"needs": []}
    assert evidence_set.status == "frozen"
    assert await list_evidence_items(session, evidence_set.id) == []


@pytest.mark.asyncio
async def test_source_error_is_stored_and_attempt_is_ready(db):
    session, _factory = db
    _customer_row, _run, attempt = await _created_attempt(session, slug="err-co")
    boom = RecordingSource("swedish_law", error=RuntimeError("lagen down"))
    router, _ = _router(boom)
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "swedish_law")]),
        router=router,
    )
    evidence_set = await get_evidence_set(session, result.evidence_set_id)
    items = await list_evidence_items(session, evidence_set.id)
    assert result.status == "ready"
    assert result.error_count == 1
    assert result.found_count == 0
    assert evidence_set.status == "frozen"
    assert items[0].status == "error"
    assert items[0].source_type == "swedish_law"


@pytest.mark.asyncio
async def test_fatal_orchestration_marks_attempt_and_set_failed(db):
    session, _factory = db
    _customer_row, _run, attempt = await _created_attempt(session, slug="fatal-co")
    with pytest.raises(ResearchExecutionError, match="research failed"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=RaisingRouter(),  # type: ignore[arg-type]
        )
    reloaded = await get_attempt(session, attempt.id)
    evidence_set = await get_evidence_set(session, reloaded.evidence_set_id)
    assert reloaded.status == "failed"
    assert evidence_set.status == "failed"
    assert evidence_set.frozen_at is None


@pytest.mark.asyncio
async def test_failed_transition_allows_non_frozen_evidence(db):
    session, _factory = db
    _customer_row, run, attempt = await _created_attempt(session, slug="fail-ok")
    building = await create_evidence_set(session, run_id=run.id)
    await attach_evidence_set(session, attempt_id=attempt.id, evidence_set_id=building.id)
    await mark_researching(session, attempt.id)
    failed = await fail_attempt(session, attempt.id)
    assert failed.status == "failed"
    reloaded = await get_evidence_set(session, building.id)
    assert reloaded.status == "building"


@pytest.mark.asyncio
async def test_ready_second_execution_is_idempotent(db):
    session, _factory = db
    _customer_row, _run, attempt = await _created_attempt(session, slug="idemp-co")
    source = RecordingSource("case_knowledge")
    router, _ = _router(source)
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    first = await execute_attempt_research(
        session, attempt_id=attempt.id, research_plan=plan, router=router
    )
    second = await execute_attempt_research(
        session, attempt_id=attempt.id, research_plan=plan, router=router
    )
    assert source.calls == 1
    assert first.evidence_set_id == second.evidence_set_id
    assert first.status == second.status == "ready"
    items = await list_evidence_items(session, first.evidence_set_id)
    assert len(items) == 1


@pytest.mark.asyncio
async def test_researching_and_terminal_starts_are_rejected(db):
    session, _factory = db
    _customer_row, _run, in_progress = await _created_attempt(session, slug="prog-co")
    await mark_researching(session, in_progress.id)
    router, _ = _router(RecordingSource("case_knowledge"))
    plan = ResearchPlan(needs=[_need("research_1", "case_knowledge")])
    with pytest.raises(ExecutionStatusError, match="already in progress"):
        await execute_attempt_research(
            session, attempt_id=in_progress.id, research_plan=plan, router=router
        )

    _c2, _r2, ready_then_run = await _created_attempt(session, slug="run-co")
    await execute_attempt_research(
        session,
        attempt_id=ready_then_run.id,
        research_plan=ResearchPlan(),
        router=GuardRouter(),  # type: ignore[arg-type]
    )
    running = await start_attempt(session, ready_then_run.id)
    with pytest.raises(ExecutionStatusError, match="status=running"):
        await execute_attempt_research(
            session, attempt_id=running.id, research_plan=plan, router=router
        )

    _c3, _r3, failed = await _created_attempt(session, slug="rej-fail")
    await fail_attempt(session, failed.id)
    with pytest.raises(ExecutionStatusError, match="status=failed"):
        await execute_attempt_research(
            session, attempt_id=failed.id, research_plan=plan, router=router
        )


@pytest.mark.asyncio
async def test_double_claim_is_rejected(db):
    session, _factory = db
    _customer_row, _run, attempt = await _created_attempt(session, slug="claim-co")
    first = await claim_attempt_researching(
        session, attempt.id, research_plan_snapshot={"needs": []}
    )
    assert first.status == "researching"
    with pytest.raises(ExecutionStatusError, match="already in progress"):
        await claim_attempt_researching(
            session, attempt.id, research_plan_snapshot={"needs": []}
        )


@pytest.mark.asyncio
async def test_tx1_commits_before_router_runs(db):
    session, factory = db
    _customer_row, _run, attempt = await _created_attempt(session, slug="tx-co")
    attempt_id = attempt.id

    class InspectingSource(RecordingSource):
        seen_status = None
        seen_set_status = None

        async def research(self, need: ResearchNeed, context: ResearchContext):
            async with factory() as other:
                row = await other.get(ExecutionAttempt, attempt_id)
                self.seen_status = row.status if row is not None else None
                if row is not None and row.evidence_set_id:
                    evidence_set = await other.get(EvidenceSet, row.evidence_set_id)
                    self.seen_set_status = (
                        evidence_set.status if evidence_set is not None else None
                    )
            return await super().research(need, context)

    source = InspectingSource("case_knowledge")
    router, _ = _router(source)
    await execute_attempt_research(
        session,
        attempt_id=attempt_id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=router,
    )
    assert source.seen_status == "researching"
    assert source.seen_set_status == "building"


@pytest.mark.asyncio
async def test_duplicate_need_ids_and_invalid_plan_leave_attempt_created(db):
    session, _factory = db
    _customer_row, _run, attempt = await _created_attempt(session, slug="dup-co")
    router, _ = _router(RecordingSource("case_knowledge"))
    with pytest.raises(InvalidResearchPlanError, match="Duplicate"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(
                needs=[
                    _need("research_1", "case_knowledge"),
                    _need("research_1", "customer_knowledge"),
                ]
            ),
            router=router,
        )
    with pytest.raises(InvalidResearchPlanError, match="question"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(
                needs=[_need("research_1", "case_knowledge", question="  ")]
            ),
            router=router,
        )
    with pytest.raises(InvalidResearchPlanError, match="unknown source_type"):
        await execute_attempt_research(
            session,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(needs=[_need("research_1", "not_a_source")]),
            router=router,
        )
    reloaded = await get_attempt(session, attempt.id)
    assert reloaded.status == "created"
    assert reloaded.evidence_set_id is None
    assert reloaded.research_plan_snapshot is None


@pytest.mark.asyncio
async def test_scope_always_derives_from_run(db):
    session, _factory = db
    customer, run, attempt = await _created_attempt(session, slug="scope-co")
    source = RecordingSource("case_knowledge")
    router, _ = _router(source)
    await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=router,
    )
    context = research_context_from_run(run)
    assert source.contexts[0].scope.customer_id == customer.id == run.customer_id
    assert source.contexts[0].scope.module == run.module
    assert source.contexts[0].scope.case_id == "case-1"
    assert context.scope.customer_id == run.customer_id
    signature = inspect.signature(execute_attempt_research)
    assert "customer_id" not in signature.parameters
    assert "scope" not in signature.parameters


@pytest.mark.asyncio
async def test_frozen_set_rejects_item_mutation(db):
    session, _factory = db
    _customer_row, _run, attempt = await _created_attempt(session, slug="freeze-co")
    router, _ = _router(RecordingSource("case_knowledge"))
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=router,
    )
    with pytest.raises(ExecutionFrozenError):
        await add_evidence_items(
            session,
            evidence_set_id=result.evidence_set_id,
            items=[
                build_evidence(
                    research_need_id="research_9",
                    source_type="case_knowledge",
                    status="found",
                    excerpt="ny text",
                )
            ],
        )


def test_execute_attempt_research_has_no_panel_or_ui_imports():
    for path in (EXECUTION_PY, PLAN_PY):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                for prefix in _FORBIDDEN_IMPORT_PREFIXES:
                    assert name != prefix and not name.startswith(prefix + "."), (
                        f"{path} imports {name}"
                    )
