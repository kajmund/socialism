"""ExecutionRun → ExecutionAttempt → EvidenceSet (generic, not simulation Run)."""

from __future__ import annotations

import ast
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import ExecutionAttempt, ExecutionRun, Kund, Run
from app.services.execution import (
    ATTEMPT_STATUSES,
    ExecutionFrozenError,
    ExecutionImmutableError,
    ExecutionNotFoundError,
    ExecutionScopeError,
    ExecutionStatusError,
    add_evidence_items,
    attach_evidence_set,
    clone_attempt,
    complete_attempt,
    compute_content_hash,
    create_attempt,
    create_evidence_set,
    create_run,
    fail_attempt,
    freeze_evidence_set,
    get_attempt,
    get_evidence_set,
    get_run,
    list_evidence_items,
    mark_ready,
    mark_researching,
    set_attempt_snapshots,
    start_attempt,
)
from app.services.research.models import research_evidence

EXECUTION_ROOT = Path(__file__).resolve().parents[1] / "app" / "services" / "execution"

_FORBIDDEN_IMPORT_PREFIXES = (
    "app.services.panel",
    "app.services.rattsunderlag",
    "app.services.expertgranskning",
    "app.llm",
    "app.services.dd.research",
    "app.api",
)


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _customer(session: AsyncSession, slug: str) -> Kund:
    kund = Kund(name=slug, slug=slug, available_modules=["dd"])
    session.add(kund)
    await session.flush()
    return kund


def _evidence(*, need: str, excerpt: str, locator: str) -> object:
    return research_evidence(
        research_need_id=need,
        source_type="case_knowledge",
        status="found",
        title="Kommunens skattesats",
        excerpt=excerpt,
        locator=locator,
        source_id="doc-brief",
        source_url="https://example.test/brief.pdf",
        provider="supabase",
        score=0.91,
        retrieved_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        metadata={"document_id": "doc-brief", "version": "3", "locator": locator},
    )


async def _acceptance_setup(session: AsyncSession):
    customer_a = await _customer(session, "acme")
    run = await create_run(
        session,
        customer_id=customer_a.id,
        module="dd",
        title="Skattesats",
        context={"matter": "kommunalskatt"},
    )
    evidence_set = await create_evidence_set(session, run_id=run.id)
    first = _evidence(need="research_1", excerpt="skattesats 32%", locator="p1")
    second = _evidence(need="research_2", excerpt="jämförelse 2024", locator="p4")
    items = await add_evidence_items(
        session, evidence_set_id=evidence_set.id, items=[first, second]
    )
    frozen = await freeze_evidence_set(session, evidence_set.id)
    attempt_a = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={"model": "config-a", "temperature": 0.1},
        input_snapshot={"question": "Vad gäller skattesatsen?"},
        evidence_set_id=frozen.id,
    )
    attempt_a = await start_attempt(session, attempt_a.id)
    attempt_a = await complete_attempt(session, attempt_a.id)
    return customer_a, run, frozen, items, attempt_a, first, second


@pytest.mark.asyncio
async def test_acceptance_clone_reuses_frozen_evidence_without_mutating_source(session):
    customer_a, run, frozen, items, attempt_a, first, second = await _acceptance_setup(
        session
    )
    source_before = {
        "id": attempt_a.id,
        "status": attempt_a.status,
        "config": deepcopy(attempt_a.configuration_snapshot),
        "input": deepcopy(attempt_a.input_snapshot),
        "evidence_set_id": attempt_a.evidence_set_id,
        "parent_attempt_id": attempt_a.parent_attempt_id,
        "started_at": attempt_a.started_at,
        "completed_at": attempt_a.completed_at,
        "attempt_type": attempt_a.attempt_type,
    }

    attempt_b = await clone_attempt(
        session,
        attempt_a.id,
        configuration_override={"model": "config-b", "temperature": 0.7},
    )

    assert attempt_b.id != attempt_a.id
    assert attempt_b.run_id == run.id
    assert attempt_b.parent_attempt_id == attempt_a.id
    assert attempt_b.evidence_set_id == frozen.id == attempt_a.evidence_set_id
    assert attempt_b.configuration_snapshot["model"] == "config-b"
    assert attempt_a.configuration_snapshot["model"] == "config-a"
    assert attempt_b.configuration_snapshot != attempt_a.configuration_snapshot
    assert attempt_b.input_snapshot == source_before["input"]
    assert attempt_b.status == "created"

    reloaded_a = await get_attempt(session, attempt_a.id)
    assert reloaded_a.status == source_before["status"]
    assert reloaded_a.configuration_snapshot == source_before["config"]
    assert reloaded_a.input_snapshot == source_before["input"]
    assert reloaded_a.evidence_set_id == source_before["evidence_set_id"]
    assert reloaded_a.parent_attempt_id == source_before["parent_attempt_id"]
    assert reloaded_a.started_at == source_before["started_at"]
    assert reloaded_a.completed_at == source_before["completed_at"]
    assert reloaded_a.attempt_type == source_before["attempt_type"]

    with pytest.raises(ExecutionFrozenError):
        await add_evidence_items(
            session,
            evidence_set_id=frozen.id,
            items=[_evidence(need="research_3", excerpt="ny text", locator="p9")],
        )

    customer_b = await _customer(session, "other-co")
    other_run = await create_run(
        session,
        customer_id=customer_b.id,
        module="dd",
        title="Annat ärende",
    )
    with pytest.raises(ExecutionScopeError):
        await create_attempt(
            session,
            run_id=other_run.id,
            attempt_type="generic_panel",
            evidence_set_id=frozen.id,
        )
    other_attempt = await create_attempt(
        session, run_id=other_run.id, attempt_type="generic_panel"
    )
    with pytest.raises(ExecutionScopeError):
        await attach_evidence_set(
            session, attempt_id=other_attempt.id, evidence_set_id=frozen.id
        )

    stored = await list_evidence_items(session, frozen.id)
    assert len(stored) == 2
    by_need = {row.research_need_id: row for row in stored}
    assert by_need["research_1"].excerpt == first.excerpt
    assert by_need["research_1"].locator == first.locator
    assert by_need["research_1"].provenance["version"] == "3"
    assert by_need["research_1"].provenance["research_evidence_id"] == first.evidence_id
    assert by_need["research_2"].excerpt == second.excerpt
    for row in stored:
        assert row.content_hash == compute_content_hash(
            title=row.title,
            excerpt=row.excerpt,
            locator=row.locator,
            source_id=row.source_id,
            source_url=row.source_url,
            provenance=row.provenance,
        )
    assert customer_a.id == run.customer_id
    assert len(items) == 2


@pytest.mark.asyncio
async def test_missing_and_wrong_scope_fail_closed(session):
    with pytest.raises(ExecutionNotFoundError):
        await create_run(
            session, customer_id=999, module="dd", title="Saknas"
        )
    with pytest.raises(ExecutionNotFoundError):
        await get_run(session, "missing-run")
    with pytest.raises(ExecutionNotFoundError):
        await get_attempt(session, "missing-attempt")
    with pytest.raises(ExecutionNotFoundError):
        await create_evidence_set(session, run_id="missing-run")

    customer = await _customer(session, "scope-co")
    run = await create_run(session, customer_id=customer.id, module="dd", title="R")
    other = await create_run(session, customer_id=customer.id, module="dd", title="R2")
    attempt = await create_attempt(
        session, run_id=run.id, attempt_type="generic_panel"
    )
    with pytest.raises(ExecutionScopeError):
        await create_evidence_set(
            session, run_id=other.id, created_from_attempt_id=attempt.id
        )


@pytest.mark.asyncio
async def test_attempt_status_and_snapshot_immutability(session):
    customer = await _customer(session, "status-co")
    run = await create_run(session, customer_id=customer.id, module="dd", title="R")
    building = await create_evidence_set(session, run_id=run.id)
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="word_review",
        configuration_snapshot={"prompt": "v1"},
        input_snapshot={
            "document_id": "doc-1",
            "document_version": "4",
            "content_hash": "abc123",
        },
        evidence_set_id=building.id,
    )
    assert attempt.status == "created"
    assert set(ATTEMPT_STATUSES) == {
        "created",
        "researching",
        "ready",
        "running",
        "completed",
        "failed",
    }

    attempt = await mark_researching(session, attempt.id)
    assert attempt.status == "researching"
    await set_attempt_snapshots(
        session, attempt_id=attempt.id, configuration_snapshot={"prompt": "v2"}
    )

    with pytest.raises(ExecutionStatusError):
        await mark_ready(session, attempt.id)

    await freeze_evidence_set(session, building.id)
    attempt = await mark_ready(session, attempt.id)
    assert attempt.status == "ready"

    with pytest.raises(ExecutionImmutableError):
        await set_attempt_snapshots(
            session, attempt_id=attempt.id, configuration_snapshot={"prompt": "v3"}
        )
    with pytest.raises(ExecutionImmutableError):
        await attach_evidence_set(
            session, attempt_id=attempt.id, evidence_set_id=building.id
        )

    reloaded = await get_attempt(session, attempt.id)
    assert reloaded.configuration_snapshot == {"prompt": "v2"}
    assert reloaded.input_snapshot["document_id"] == "doc-1"

    attempt = await start_attempt(session, attempt.id)
    assert attempt.status == "running"
    assert attempt.started_at is not None
    attempt = await complete_attempt(session, attempt.id)
    assert attempt.status == "completed"
    assert attempt.completed_at is not None

    with pytest.raises(ExecutionStatusError):
        await start_attempt(session, attempt.id)
    with pytest.raises(ExecutionStatusError):
        await fail_attempt(session, attempt.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("start_status", ["created", "researching"])
async def test_fail_attempt_allows_building_evidence_set(session, start_status):
    customer = await _customer(session, f"fail-{start_status}")
    run = await create_run(session, customer_id=customer.id, module="dd", title="R")
    building = await create_evidence_set(session, run_id=run.id)
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        evidence_set_id=building.id,
    )
    if start_status == "researching":
        attempt = await mark_researching(session, attempt.id)
    assert attempt.status == start_status
    assert building.status == "building"

    attempt = await fail_attempt(session, attempt.id)

    assert attempt.status == "failed"
    reloaded_set = await get_evidence_set(session, building.id)
    assert reloaded_set.status == "building"
    assert reloaded_set.frozen_at is None


@pytest.mark.asyncio
async def test_clone_does_not_reuse_building_evidence_set(session):
    customer = await _customer(session, "building-co")
    run = await create_run(session, customer_id=customer.id, module="dd", title="R")
    building = await create_evidence_set(session, run_id=run.id)
    source = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="structured_scoring",
        evidence_set_id=building.id,
        configuration_snapshot={"k": 1},
    )
    clone = await clone_attempt(session, source.id, configuration_override={"k": 2})
    assert clone.evidence_set_id is None
    assert clone.parent_attempt_id == source.id
    assert (await get_attempt(session, source.id)).evidence_set_id == building.id


@pytest.mark.asyncio
async def test_execution_run_is_not_simulation_run():
    assert ExecutionAttempt.__tablename__ == "execution_attempts"
    assert Run.__tablename__ == "runs"
    assert ExecutionRun.__tablename__ == "execution_runs"
    assert ExecutionRun.__tablename__ != Run.__tablename__


def test_execution_package_has_no_panel_word_or_api_imports():
    for path in sorted(EXECUTION_ROOT.rglob("*.py")):
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
