"""The worker retries durable graph projection failures without losing research."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.graph_v2 import GraphIngestWork
from app.database.models import (
    CanonicalDocumentRecord, DocumentVersionRecord, Kund,
)
from app.services.graph_v2.outbox import (
    _retry_graph_work,
    _is_permanent_graph_error,
    claim_graph_work,
    enqueue_legal_graph,
    process_graph_work,
)
from app.services.graph_v2.errors import JevMalformedResponseError, PermanentGraphError
import app.services.graph_v2.outbox as graph_outbox
from app.services.knowledge.claims import KnowledgeClaim
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError
from tests.text_unit_fakes import persisted_text_unit


class FakeEmbedder:
    model = "test"
    dimension = 2
    provider_id = "test"
    async def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


async def test_invalid_projection_payload_is_terminal_and_keeps_payload(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/outbox.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
        session.add(GraphIngestWork(
            id="broken", customer_id=1, scope_key="customer:1",
            payload={"claims": [{"bad": "shape"}]}, status="pending", attempts=0,
        ))
    result = await process_graph_work(factory, embedder=FakeEmbedder())
    assert result == {"completed": 0, "failed": 1}
    async with factory() as session:
        work = await session.scalar(select(GraphIngestWork))
        assert work.status == "failed"
        assert work.attempts == 1
        assert work.last_error
        assert work.retry_at is None
        assert work.payload == {"claims": [{"bad": "shape"}]}
    assert await process_graph_work(factory, embedder=FakeEmbedder()) == {
        "completed": 0, "failed": 0,
    }
    await engine.dispose()


def test_graph_error_classification_separates_permanent_from_transient():
    assert _is_permanent_graph_error(PermanentGraphError("invalid invariant"))
    assert not _is_permanent_graph_error(ValueError("provider returned an unusable result"))
    assert _is_permanent_graph_error(DataError("INSERT", {}, Exception("value too long")))
    assert _is_permanent_graph_error(ProgrammingError("schema mismatch", {}, Exception()))
    assert not _is_permanent_graph_error(IntegrityError("concurrent conflict", {}, Exception()))
    assert not _is_permanent_graph_error(JevMalformedResponseError("missing choice"))
    assert not _is_permanent_graph_error(TimeoutError("provider timeout"))
    assert not _is_permanent_graph_error(ConnectionError("provider unavailable"))


async def test_malformed_jev_response_retries_graph_work(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/jev-retry.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
        session.add(GraphIngestWork(
            id="jev-malformed", customer_id=1, scope_key="customer:1", status="pending",
            attempts=0, payload={"module": "dd", "claims": [], "entities": []},
        ))

    async def malformed(*args, **kwargs):
        raise JevMalformedResponseError("semantic fact judge returned an invalid decision")

    monkeypatch.setattr(graph_outbox, "write_legal_facts", malformed)
    assert await process_graph_work(factory, embedder=FakeEmbedder()) == {
        "completed": 0, "failed": 1,
    }
    async with factory() as session:
        work = await session.get(GraphIngestWork, "jev-malformed")
        assert work.status == "pending"
        assert work.attempts == 1
        assert work.retry_at is not None
    await engine.dispose()


async def test_payload_without_source_entity_is_terminal(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/missing-source.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
        session.add(GraphIngestWork(
            id="missing-source", customer_id=1, scope_key="customer:1", status="pending",
            attempts=0, payload={
                "module": "dd",
                "claims": [{
                    "id": "claim", "predicate": "legal.outcome",
                    "value": {"value": "No adjustment"}, "unit_ids": [],
                }],
                "entities": [],
            },
        ))

    assert await process_graph_work(factory, embedder=FakeEmbedder()) == {
        "completed": 0, "failed": 1,
    }
    async with factory() as session:
        work = await session.get(GraphIngestWork, "missing-source")
        assert work.status == "failed"
        assert work.attempts == 1
        assert work.retry_at is None
    await engine.dispose()


async def test_transient_embedding_failure_stays_retryable(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/transient.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
        session.add(CanonicalDocumentRecord(
            id="doc", scope_type="customer", scope_key="customer:1", customer_id=1,
            source_type="upload", canonical_uri="doc://case-x", title="Case X", extra={},
        ))
        session.add(DocumentVersionRecord(
            id="version", scope_type="customer", scope_key="customer:1", customer_id=1,
            document_id="doc", content_hash="version-hash", mime_type="text/plain", extra={},
        ))
        session.add(await persisted_text_unit(session,
            id="unit", scope_type="customer", scope_key="customer:1", customer_id=1,
            document_version_id="version", document_id="doc", section_id=None,
            ordinal=0, text="No adjustment",
        ))
        session.add(GraphIngestWork(
            id="transient", customer_id=1, scope_key="customer:1", status="pending",
            attempts=0, payload={
                "module": "dd",
                "claims": [{
                    "id": "claim", "predicate": "legal.outcome",
                    "value": {"value": "No adjustment"}, "unit_ids": ["unit"],
                }],
                "entities": [{
                    "id": "source", "entity_type": "legal.source",
                    "key": "https://example.test/case", "name": "Case X", "extra": {},
                }],
            },
        ))

    class OfflineEmbedder(FakeEmbedder):
        async def embed(self, texts):
            raise TimeoutError("embedding provider timeout")

    assert await process_graph_work(factory, embedder=OfflineEmbedder()) == {
        "completed": 0, "failed": 1,
    }
    async with factory() as session:
        work = await session.get(GraphIngestWork, "transient")
        assert work.status == "pending"
        assert work.attempts == 1
        assert work.retry_at is not None
    await engine.dispose()


async def test_outbox_key_distinguishes_new_facts_on_same_research_need(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/outbox-identity.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
        await session.flush()
        first = KnowledgeClaim("first", 1, "legal.outcome", {"value": True}, ("unit",))
        second = KnowledgeClaim("second", 1, "legal.outcome", {"value": False}, ("unit",))
        common = dict(customer_id=1, research_need_id="research_1", entities=(),
                      module="politik")
        first_id = await enqueue_legal_graph(session, claims=[first], **common)
        second_id = await enqueue_legal_graph(session, claims=[second], **common)
        assert first_id != second_id
        assert await enqueue_legal_graph(session, claims=[first], **common) == first_id
        assert await session.scalar(select(func.count()).select_from(GraphIngestWork)) == 2
        assert (await session.get(GraphIngestWork, first_id)).payload["module"] == "politik"
    await engine.dispose()


async def test_expired_worker_cannot_requeue_a_completed_newer_attempt(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/lease.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
        session.add(GraphIngestWork(
            id="race", customer_id=1, scope_key="customer:1",
            payload={}, status="pending", attempts=0,
        ))
    assert await claim_graph_work(factory) == ("race", 1)
    async with factory.begin() as session:
        row = await session.get(GraphIngestWork, "race")
        row.claimed_at = datetime.now(UTC) - timedelta(minutes=6)
    assert await claim_graph_work(factory) == ("race", 2)
    await _retry_graph_work(factory, "race", 1, RuntimeError("late failure"))
    async with factory.begin() as session:
        row = await session.get(GraphIngestWork, "race")
        assert row.status == "processing" and row.attempts == 2
        row.status = "completed"
    await _retry_graph_work(factory, "race", 1, RuntimeError("late failure"))
    async with factory() as session:
        row = await session.get(GraphIngestWork, "race")
        assert row.status == "completed" and row.retry_at is None
    await engine.dispose()


def test_graph_ingest_loop_does_not_process_revalidation():
    import inspect

    from app.services.graph_v2 import worker

    source = inspect.getsource(worker)
    assert "process_graph_work" in source
    assert "revalidation" not in source
    assert "process_question_revalidation_work" not in source


async def test_run_graph_ingest_loop_only_calls_ingest(monkeypatch):
    import asyncio

    from app.services.graph_v2 import worker

    calls: list[int] = []

    async def fake_process(factory, limit=10):
        calls.append(limit)
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "process_graph_work", fake_process)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_graph_ingest_loop(object())
    assert calls == [10]
