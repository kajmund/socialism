"""ExecutionRun → ExecutionAttempt → EvidenceSet (generic, not simulation Run)."""

from __future__ import annotations

import ast
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import EvidenceSet, ExecutionAttempt, ExecutionRun, Kund, Run
from app.services.execution import (
    ATTEMPT_STATUSES,
    ExecutionError,
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
    fail_evidence_set,
    freeze_evidence_set,
    get_attempt,
    get_attempt_result,
    get_evidence_set,
    get_run,
    list_evidence_items,
    mark_ready,
    mark_researching,
    persist_attempt_result,
    set_attempt_snapshots,
    start_attempt,
)
from app.services.execution.snapshots import snapshot_research_evidence
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
        configuration_snapshot={"model": "config-b", "temperature": 0.7},
    )

    assert attempt_b.id != attempt_a.id
    assert attempt_b.run_id == run.id
    assert attempt_b.parent_attempt_id == attempt_a.id
    assert attempt_b.evidence_set_id == frozen.id == attempt_a.evidence_set_id
    assert attempt_b.configuration_snapshot["model"] == "config-b"
    assert attempt_a.configuration_snapshot["model"] == "config-a"
    assert attempt_b.configuration_snapshot != attempt_a.configuration_snapshot
    assert attempt_b.input_snapshot == source_before["input"]
    assert attempt_b.status == "ready"
    assert attempt_b.research_plan_snapshot == attempt_a.research_plan_snapshot

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
    assert by_need["research_1"].original_evidence_id == first.evidence_id
    assert by_need["research_2"].excerpt == second.excerpt
    assert [row.ordinal for row in stored] == [0, 1]
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
async def test_clone_rejects_building_evidence_set(session):
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
    source = await fail_attempt(session, source.id)
    with pytest.raises(ExecutionStatusError, match="frozen"):
        await clone_attempt(session, source.id, configuration_snapshot={"k": 2})
    reloaded = await get_attempt(session, source.id)
    assert reloaded.evidence_set_id == building.id
    assert reloaded.configuration_snapshot == {"k": 1}
    assert reloaded.status == "failed"


@pytest.mark.asyncio
async def test_clone_rejects_failed_evidence_set(session):
    customer = await _customer(session, "failed-set-co")
    run = await create_run(session, customer_id=customer.id, module="dd", title="R")
    evidence_set = await create_evidence_set(session, run_id=run.id)
    source = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="structured_scoring",
        evidence_set_id=evidence_set.id,
        configuration_snapshot={"k": 1},
    )
    await fail_evidence_set(session, evidence_set.id)
    source = await fail_attempt(session, source.id)
    with pytest.raises(ExecutionStatusError, match="frozen"):
        await clone_attempt(session, source.id)
    assert (await get_attempt(session, source.id)).evidence_set_id == evidence_set.id


@pytest.mark.asyncio
async def test_clone_rejects_source_without_evidence(session):
    customer = await _customer(session, "no-evidence-co")
    run = await create_run(session, customer_id=customer.id, module="dd", title="R")
    source = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="structured_scoring",
        configuration_snapshot={"k": 1},
    )
    source = await mark_ready(session, source.id)
    with pytest.raises(ExecutionStatusError, match="no attached EvidenceSet"):
        await clone_attempt(session, source.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("start_status", ["created", "researching", "running"])
async def test_clone_rejects_non_cloneable_status(session, start_status):
    customer = await _customer(session, f"status-{start_status}")
    run = await create_run(session, customer_id=customer.id, module="dd", title="R")
    evidence_set = await create_evidence_set(session, run_id=run.id)
    await freeze_evidence_set(session, evidence_set.id)
    source = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="structured_scoring",
        evidence_set_id=evidence_set.id,
        configuration_snapshot={"k": 1},
    )
    if start_status == "researching":
        source = await mark_researching(session, source.id)
    elif start_status == "running":
        source = await mark_ready(session, source.id)
        source = await start_attempt(session, source.id)
    with pytest.raises(ExecutionStatusError, match="Cannot clone"):
        await clone_attempt(session, source.id)
    assert (await get_attempt(session, source.id)).status == start_status


@pytest.mark.asyncio
async def test_clone_without_config_copies_source_exactly(session):
    _customer_a, _run, frozen, _items, attempt_a, _first, _second = await _acceptance_setup(
        session
    )
    clone = await clone_attempt(session, attempt_a.id)
    assert clone.configuration_snapshot == attempt_a.configuration_snapshot
    assert clone.input_snapshot == attempt_a.input_snapshot
    assert clone.research_plan_snapshot == attempt_a.research_plan_snapshot
    assert clone.attempt_type == attempt_a.attempt_type
    assert clone.evidence_set_id == frozen.id
    assert clone.status == "ready"
    assert await get_attempt_result(session, clone.id) is None


@pytest.mark.asyncio
async def test_clone_replaces_configuration_without_merge(session):
    _customer_a, _run, frozen, _items, attempt_a, _first, _second = await _acceptance_setup(
        session
    )
    clone = await clone_attempt(
        session, attempt_a.id, configuration_snapshot={"model": "config-b"}
    )
    assert clone.configuration_snapshot == {"model": "config-b"}
    assert attempt_a.configuration_snapshot == {"model": "config-a", "temperature": 0.1}
    reloaded = await get_attempt(session, attempt_a.id)
    assert reloaded.configuration_snapshot == {"model": "config-a", "temperature": 0.1}
    assert clone.evidence_set_id == frozen.id


@pytest.mark.asyncio
async def test_clone_twice_creates_distinct_children_sharing_evidence(session):
    _customer_a, run, frozen, _items, attempt_a, _first, _second = await _acceptance_setup(
        session
    )
    first = await clone_attempt(session, attempt_a.id)
    second = await clone_attempt(session, attempt_a.id)
    assert first.id != second.id
    assert first.id != attempt_a.id
    assert first.parent_attempt_id == second.parent_attempt_id == attempt_a.id
    assert first.evidence_set_id == second.evidence_set_id == frozen.id
    sets = (
        await session.execute(
            select(func.count()).select_from(EvidenceSet).where(EvidenceSet.run_id == run.id)
        )
    ).scalar()
    assert sets == 1


@pytest.mark.asyncio
async def test_clone_from_ready_and_failed_with_frozen_set(session):
    customer = await _customer(session, "ready-fail-co")
    run = await create_run(session, customer_id=customer.id, module="dd", title="R")
    evidence_set = await create_evidence_set(session, run_id=run.id)
    frozen = await freeze_evidence_set(session, evidence_set.id)
    ready = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="structured_scoring",
        evidence_set_id=frozen.id,
        configuration_snapshot={"k": 1},
        input_snapshot={"q": "x"},
    )
    ready = await mark_ready(session, ready.id)
    from_ready = await clone_attempt(session, ready.id)
    assert from_ready.status == "ready"
    assert from_ready.parent_attempt_id == ready.id
    assert from_ready.evidence_set_id == frozen.id

    failed = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="structured_scoring",
        evidence_set_id=frozen.id,
        configuration_snapshot={"k": 2},
    )
    failed = await mark_ready(session, failed.id)
    failed = await start_attempt(session, failed.id)
    failed = await fail_attempt(session, failed.id)
    from_failed = await clone_attempt(session, failed.id)
    assert from_failed.status == "ready"
    assert from_failed.parent_attempt_id == failed.id
    assert from_failed.evidence_set_id == frozen.id
    assert (await get_attempt(session, failed.id)).status == "failed"


@pytest.mark.asyncio
async def test_clone_does_not_copy_result_and_locks_snapshots(session):
    customer = await _customer(session, "result-co")
    run = await create_run(session, customer_id=customer.id, module="dd", title="R")
    evidence_set = await create_evidence_set(session, run_id=run.id)
    frozen = await freeze_evidence_set(session, evidence_set.id)
    attempt_a = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={"model": "config-a"},
        input_snapshot={"question": "x"},
        evidence_set_id=frozen.id,
    )
    attempt_a = await mark_ready(session, attempt_a.id)
    attempt_a = await start_attempt(session, attempt_a.id)
    stored = await persist_attempt_result(
        session,
        attempt_id=attempt_a.id,
        result_type="generic_panel",
        schema_version="1",
        payload={"schema_version": "1", "protocol": "generic_panel", "summary": "A"},
    )
    attempt_a = await complete_attempt(session, attempt_a.id)
    clone = await clone_attempt(session, attempt_a.id)
    assert await get_attempt_result(session, clone.id) is None
    source_result = await get_attempt_result(session, attempt_a.id)
    assert source_result is not None
    assert source_result.id == stored.id
    with pytest.raises(ExecutionImmutableError):
        await set_attempt_snapshots(
            session, attempt_id=clone.id, configuration_snapshot={"k": 9}
        )
    assert clone.evidence_set_id == frozen.id


@pytest.mark.asyncio
async def test_execution_run_is_not_simulation_run():
    assert ExecutionAttempt.__tablename__ == "execution_attempts"
    assert Run.__tablename__ == "runs"
    assert ExecutionRun.__tablename__ == "execution_runs"
    assert ExecutionRun.__tablename__ != Run.__tablename__


@pytest.mark.asyncio
async def test_mixed_explicit_ordinals_do_not_collide(session):
    customer = await _customer(session, "ordinal-co")
    run = await create_run(session, customer_id=customer.id, module="dd", title="R")
    evidence_set = await create_evidence_set(session, run_id=run.id)
    first = snapshot_research_evidence(
        _evidence(need="research_1", excerpt="first", locator="p1"),
        ordinal=1,
    )
    second = _evidence(need="research_2", excerpt="second", locator="p2")
    stored = await add_evidence_items(
        session, evidence_set_id=evidence_set.id, items=[first, second]
    )
    assert [row.ordinal for row in stored] == [1, 2]
    listed = await list_evidence_items(session, evidence_set.id)
    assert [row.research_need_id for row in listed] == ["research_1", "research_2"]
    with pytest.raises(ExecutionError, match="duplicate evidence ordinal"):
        await add_evidence_items(
            session,
            evidence_set_id=evidence_set.id,
            items=[
                snapshot_research_evidence(
                    _evidence(need="research_3", excerpt="dup", locator="p3"),
                    ordinal=1,
                )
            ],
        )


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
