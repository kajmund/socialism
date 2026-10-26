"""Durable document_qa_write through the existing graph outbox."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.graph_v2 import GraphIngestWork
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, Kund
from app.services.document_qa import (
    AnalysisContract, AnswerPostWrite, QaWrite, SourceCite, Viewer,
)
from app.services.document_qa.kinds import DOCUMENT_QA_WRITE
from app.services.document_qa.outbox import enqueue_document_qa
from app.services.document_qa.retrieve import exact_reuse
from app.config import settings
from app.services.document_qa.store import load_question
from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.outbox import process_graph_work
from app.main import _start_graph_worker
from app.services.graph_v2.worker import stop_graph_ingest_loop
from app.services.knowledge.units import hash_text

DIM = 8
CONTRACT = AnalysisContract(
    kind="document_chat", method="existing_analysis", model="test", model_version="v1",
)


def _write(**overrides) -> QaWrite:
    values = {
        "question_text": "Vad gäller uppsägning?",
        "document_id": "doc-1",
        "document_version_id": "ver-1",
        "workspace_id": "ws-1",
        "status": "ANSWERED",
        "answer_text": "Svar om uppsägning.",
        "asked_at": "2026-10-11T10:00:00Z",
        "created_at": "2026-10-11T10:00:00Z",
        "embedding": (1.0,) + (0.0,) * 7,
    }
    values.update(overrides)
    return QaWrite(
        question_text=values["question_text"],
        document_id=values["document_id"],
        document_version_id=values["document_version_id"],
        workspace_id=values["workspace_id"],
        contract=CONTRACT,
        status=values["status"],
        answer_text=values["answer_text"],
        posts=(AnswerPostWrite("Huvudpost", (SourceCite("unit-1", "Paragraf 12"),)),),
        asked_at=values["asked_at"],
        created_at=values["created_at"],
        embedding=values["embedding"],
    )


async def _seed(session, *, customer_id=1, document_id="doc-1", version_id="ver-1"):
    if await session.get(Kund, customer_id) is None:
        session.add(Kund(id=customer_id, name=f"C{customer_id}", slug=f"c{customer_id}",
                         available_modules=[]))
        await session.flush()
    session.add(CanonicalDocumentRecord(
        id=document_id, scope_type="customer", scope_key=f"customer:{customer_id}",
        customer_id=customer_id, source_type="upload", canonical_uri=f"doc://{document_id}",
        title="Avtal", extra={},
    ))
    session.add(DocumentVersionRecord(
        id=version_id, scope_type="customer", scope_key=f"customer:{customer_id}",
        customer_id=customer_id, document_id=document_id, content_hash=hash_text("body"),
        mime_type="text/plain", extra={},
    ))


@pytest.fixture
async def catalogs(owner_tenant_catalogs):
    return await owner_tenant_catalogs(dimension=DIM)


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/qa-outbox.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_enqueue_does_not_open_overgraph(factory, tmp_path):
    async with factory.begin() as session:
        await _seed(session)
        work_id = await enqueue_document_qa(session, customer_id=1, write=_write())
    async with factory() as session:
        row = await session.get(GraphIngestWork, work_id)
        assert row.status == "pending"
        assert row.payload["kind"] == DOCUMENT_QA_WRITE
        assert "customer_id" not in row.payload
    assert list((tmp_path / "tenants").glob("*")) == [] if (tmp_path / "tenants").exists() else True
    source = Path(__file__).resolve().parents[1] / "app/services/document_qa/outbox.py"
    text = source.read_text()
    assert "TenantCatalogs" not in text and "open_catalog" not in text


@pytest.mark.asyncio
async def test_vertical_chain_reuse_and_retry_are_idempotent(factory, catalogs):
    async with factory.begin() as session:
        await _seed(session)
        first = await enqueue_document_qa(session, customer_id=1, write=_write())
        second = await enqueue_document_qa(session, customer_id=1, write=_write())
        assert first == second
    result = await process_graph_work(factory, embedder=None)
    assert result == {"completed": 1, "failed": 0}
    viewer = Viewer(
        customer_id=1, workspace_id="ws-1",
        readable_document_ids=frozenset({"doc-1"}),
        readable_version_ids=frozenset({"ver-1"}),
    )
    hit = exact_reuse(
        catalogs.open_for(1), viewer,
        question_text="Vad gäller uppsägning?",
        document_id="doc-1",
        document_version_id="ver-1",
        contract=CONTRACT,
    )
    assert hit is not None and hit.answer.text == "Svar om uppsägning."
    async with factory.begin() as session:
        row = await session.get(GraphIngestWork, first)
        row.status = "pending"
        row.claimed_at = None
        row.processed_at = None
    await process_graph_work(factory)
    loaded = load_question(catalogs.open_for(1), hit.question.key)
    assert loaded is not None and len(loaded.answers) == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(GraphIngestWork)) == 1


@pytest.mark.asyncio
async def test_missing_document_is_rejected(factory):
    async with factory.begin() as session:
        session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
        with pytest.raises(PermanentGraphError, match="missing"):
            await enqueue_document_qa(session, customer_id=1, write=_write())


@pytest.mark.asyncio
async def test_foreign_tenant_document_is_rejected(factory):
    async with factory.begin() as session:
        await _seed(session, customer_id=1)
        session.add(Kund(id=2, name="Two", slug="two", available_modules=[]))
        with pytest.raises(PermanentGraphError, match="verified tenant"):
            await enqueue_document_qa(session, customer_id=2, write=_write())


@pytest.mark.asyncio
async def test_legal_jobs_still_run_without_a_kind(factory, monkeypatch):
    from app.services.overgraph.owner_runtime import get_owner_runtime

    monkeypatch.setattr(get_owner_runtime(), "client", None)
    calls: list[str] = []

    async def fake_legal(session, **kwargs):
        calls.append("legal")
        return []

    monkeypatch.setattr("app.services.graph_v2.outbox.write_legal_facts", fake_legal)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="One", slug="one", available_modules=[]))
        session.add(GraphIngestWork(
            id="legacy-legal", customer_id=1, scope_key="customer:1",
            payload={"module": "dd", "claims": [], "entities": []},
            status="pending", attempts=0,
        ))

    class FakeEmbedder:
        model = "test"
        dimension = 2
        provider_id = "test"

        async def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]

    result = await process_graph_work(factory, embedder=FakeEmbedder())
    assert calls == ["legal"]
    assert result == {"completed": 1, "failed": 0}


@pytest.mark.asyncio
async def test_writeback_releases_the_only_connection(tmp_path, catalogs, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/qa-one.db",
        pool_size=1, max_overflow=0, pool_timeout=0.3,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    started = asyncio.Event()

    async def blocked(client, viewer, write):
        started.set()
        await asyncio.sleep(0.2)
        return await owner_persist(client, viewer, write)

    from app.services.document_qa.owner_qa import persist as owner_persist

    monkeypatch.setattr("app.services.document_qa.apply.persist_owner", blocked)
    async with factory.begin() as session:
        await _seed(session)
        await enqueue_document_qa(session, customer_id=1, write=_write())
    task = asyncio.create_task(process_graph_work(factory))
    await asyncio.wait_for(started.wait(), timeout=2)
    async with factory() as session:
        assert await session.scalar(text("SELECT 1")) == 1
    assert await task == {"completed": 1, "failed": 0}
    await engine.dispose()


@pytest.mark.asyncio
async def test_graph_loop_can_start_without_research_workers(factory, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "research_worker_loop_enabled", False)
    monkeypatch.setattr(settings, "graph_ingest_loop_enabled", False)
    assert _start_graph_worker(False, factory) is None
    monkeypatch.setattr(settings, "graph_ingest_loop_enabled", True)
    task = _start_graph_worker(False, factory)
    assert task is not None
    await stop_graph_ingest_loop(task)


@pytest.mark.asyncio
async def test_owner_mode_qa_write_uses_the_tenant_owner(
    factory, tenant_owners, monkeypatch, research_overgraph,
):
    from app.services.document_qa.owner_qa import load_question
    from app.services.document_qa.owner_qa_retrieve import exact_reuse as owner_reuse

    client = await tenant_owners(1, dimension=DIM)
    async with factory() as session:
        await _seed(session)
        write = _write()
        work_id = await enqueue_document_qa(session, customer_id=1, write=write)
        await session.commit()
    result = await process_graph_work(factory, limit=1)
    assert result == {"completed": 1, "failed": 0}
    async with factory() as session:
        assert (await session.get(GraphIngestWork, work_id)).status == "completed"
    from app.services.document_qa.normalize import question_key, reuse_digest, normalize_question
    loaded = await load_question(
        client, question_key(1, reuse_digest(normalize_question(write.question_text), "ver-1", CONTRACT)),
    )
    assert loaded is not None
    viewer = Viewer(
        customer_id=1, workspace_id="ws-1",
        readable_document_ids=frozenset({"doc-1"}),
        readable_version_ids=frozenset({"ver-1"}),
    )
    hit = await owner_reuse(
        client, viewer, question_text=write.question_text,
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    )
    assert hit is not None
