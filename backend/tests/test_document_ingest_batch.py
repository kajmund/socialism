"""Batch ingest: one job per file, measured progress, searchable after OverGraph."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.database.document_ingest_batches import DocumentIngestBatchItem
from app.database.graph_v2 import GraphIngestWork
from app.database.models import CanonicalDocumentRecord, DocumentKnowledgeItem, DocumentVersionRecord, Job, StoredObject
from app.serializers import utcnow
from app.services.document_ingest_batch.stages import ingest_percent
from app.services.document_ingest_job import run_document_ingest_job
from app.services.document_ingest_status import document_text_ready
from app.services.document_qa.kinds import DOCUMENT_CATALOG_WRITE
from app.services import jobs as jobs_service
from app.services.object_storage import UNDERLAG_DOCX_TYPE
from app.services.research.composition import set_knowledge_vector_store_factory
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.knowledge.scope import customer_scope, persist_scope_fields
from app.services.workspace.service import new_id
from app.services.workspace.source_content import file_sha256
from tests.knowledge_fakes import FakeEmbeddingProvider

PROGRESS = Path(__file__).resolve().parents[1] / "app/services/document_ingest_batch/progress.py"


@pytest.fixture(autouse=True)
def hold_jobs(monkeypatch):
    monkeypatch.setattr(jobs_service, "enqueue_job", lambda _job_id: None)


def test_ingest_bar_is_not_full_before_searchable():
    assert ingest_percent(unit_done=0, unit_total=10, searchable=False) == 0
    assert ingest_percent(unit_done=7, unit_total=10, searchable=False) == 70
    assert ingest_percent(unit_done=10, unit_total=10, searchable=False) == 99
    assert ingest_percent(unit_done=10, unit_total=10, searchable=True) == 100


def test_progress_module_never_opens_overgraph():
    source = PROGRESS.read_text()
    assert "TenantCatalogs" not in source
    assert "open_catalog" not in source
    assert "ingest_document_units" not in source


async def _workspace(client):
    response = await client.post(
        "/voice-workspaces?customer_id=1", json={"title": "Avtal", "idempotency_key": new_id()},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _batch(client, workspace_id: str):
    response = await client.post(f"/voice-workspaces/{workspace_id}/ingest-batches")
    assert response.status_code == 201, response.text
    return response.json()


async def _upload(client, workspace_id: str, batch_id: str, *, name: str, text: str, key: str):
    response = await client.post(
        f"/voice-workspaces/{workspace_id}/ingest-batches/{batch_id}/files",
        data={"idempotency_key": key, "client_key": key},
        files={"file": (name, text.encode(), "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_batch_keeps_independent_file_jobs(client_db):
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    first = await _upload(client, workspace["id"], batch["id"], name="a.txt", text="Ett", key="file-a")
    second = await _upload(client, workspace["id"], batch["id"], name="b.txt", text="Två", key="file-b")
    assert first["id"] == second["id"]
    assert len(second["items"]) == 2
    assert {item["filename"] for item in second["items"]} == {"a.txt", "b.txt"}
    assert all(item["upload_progress"] == 100 for item in second["items"])
    assert all(item["ingest_progress"] == 0 for item in second["items"])
    assert all(item["stage"] == "extracting" for item in second["items"])
    assert all(item["searchable"] is False for item in second["items"])
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Job).where(Job.kind == "document_ingest")) == 2
        assert await session.scalar(select(func.count()).select_from(DocumentIngestBatchItem)) == 2


@pytest.mark.asyncio
async def test_failed_file_can_be_retried_without_rewinding_the_batch(client_db):
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    await _upload(client, workspace["id"], batch["id"], name="ok.txt", text="Ok", key="ok")
    failed = await _upload(client, workspace["id"], batch["id"], name="fail.txt", text="Fail", key="fail")
    broken = next(item for item in failed["items"] if item["filename"] == "fail.txt")
    async with factory() as session:
        item = await session.get(DocumentIngestBatchItem, broken["id"])
        job = await session.get(Job, item.job_id)
        stored = await session.get(StoredObject, item.stored_object_id)
        item.stage = "failed"
        item.status = "failed"
        job.status = "failed"
        stored.knowledge_status = "failed"
        await session.commit()
    retried = await client.post(
        f"/voice-workspaces/{workspace['id']}/ingest-batches/{batch['id']}/items/{broken['id']}/retry",
    )
    assert retried.status_code == 200, retried.text
    body = retried.json()
    ok = next(item for item in body["items"] if item["filename"] == "ok.txt")
    again = next(item for item in body["items"] if item["filename"] == "fail.txt")
    assert ok["job_id"]
    assert again["stage"] == "extracting"
    assert again["job_id"] != broken["job_id"]
    listed = await client.get(f"/voice-workspaces/{workspace['id']}/ingest-batches")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == batch["id"]


@pytest.mark.asyncio
async def test_graph_completion_makes_the_item_searchable(client_db):
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    uploaded = await _upload(client, workspace["id"], batch["id"], name="avtal.txt", text="Avtal", key="avtal")
    item = uploaded["items"][0]
    async with factory() as session:
        row = await session.get(DocumentIngestBatchItem, item["id"])
        row.graph_work_id = "work-avtal"
        row.stage = "indexing"
        row.status = "processing"
        row.unit_total = 4
        session.add(GraphIngestWork(
            id="work-avtal",
            customer_id=1,
            scope_key="customer:1",
            payload={"kind": DOCUMENT_CATALOG_WRITE},
            status="completed",
            attempts=1,
        ))
        await session.commit()
    shown = await client.get(f"/voice-workspaces/{workspace['id']}/ingest-batches/{batch['id']}")
    assert shown.status_code == 200, shown.text
    ready = shown.json()["items"][0]
    assert ready["searchable"] is True
    assert ready["ingest_progress"] == 100
    assert ready["stage"] == "ready"
    assert shown.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_batch_keeps_docx_bytes_and_does_not_convert(client_db):
    ingest = (Path(__file__).resolve().parents[1] / "app/services/workspace/ingest.py").read_text()
    assert "convert_docx" not in ingest
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    uploaded = await client.post(
        f"/voice-workspaces/{workspace['id']}/ingest-batches/{batch['id']}/files",
        data={"idempotency_key": "word-one", "client_key": "word-one"},
        files={"file": ("avtal.docx", b"PK\x03\x04word", UNDERLAG_DOCX_TYPE)},
    )
    assert uploaded.status_code == 201, uploaded.text
    item = uploaded.json()["items"][0]
    assert item["filename"] == "avtal.docx"
    assert item["stage"] == "extracting"
    assert item["upload_progress"] == 100
    async with factory() as session:
        stored = await session.get(StoredObject, item["stored_object_id"])
        assert stored.content_type == UNDERLAG_DOCX_TYPE
        assert stored.filename == "avtal.docx"


@pytest.mark.asyncio
async def test_batch_file_failure_is_an_item_not_a_500(client_db, monkeypatch):
    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("object_store_unavailable")

    monkeypatch.setattr("app.services.workspace.ingest.put_object", unavailable)
    client, _factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    uploaded = await client.post(
        f"/voice-workspaces/{workspace['id']}/ingest-batches/{batch['id']}/files",
        data={"idempotency_key": "broken", "client_key": "broken"},
        files={"file": ("avtal.txt", b"Avtal", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    item = uploaded.json()["items"][0]
    assert item["stage"] == "failed"
    assert item["status"] == "failed"
    assert item["error"] == "object_store_unavailable"


def _fake_knowledge(monkeypatch):
    store = MemoryKnowledgeVectorStore()
    set_knowledge_vector_store_factory(lambda: store)
    monkeypatch.setattr(
        "app.services.document_knowledge.OpenAIEmbeddingProvider.from_settings",
        FakeEmbeddingProvider,
    )
    return store


@pytest.mark.asyncio
async def test_ingest_finishes_without_generated_knowledge_cards(client_db, monkeypatch):
    _fake_knowledge(monkeypatch)
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    uploaded = await _upload(client, workspace["id"], batch["id"], name="avtal.txt", text="Avtal", key="avtal")
    try:
        result = await run_document_ingest_job(factory, job_id=uploaded["items"][0]["job_id"])
        assert result["status"] == "ready"
        assert result["items_created"] == 0
        async with factory() as session:
            source = await session.get(StoredObject, uploaded["items"][0]["stored_object_id"])
            assert source is not None
            assert source.knowledge_status == "ready"
            assert document_text_ready(source)
            items = list(
                await session.scalars(
                    select(DocumentKnowledgeItem).where(
                        DocumentKnowledgeItem.source_object_id == source.id,
                    )
                )
            )
            assert items == []
    finally:
        set_knowledge_vector_store_factory(None)


@pytest.mark.asyncio
async def test_two_files_ingest_without_waiting_for_generated_cards(client_db, monkeypatch):
    _fake_knowledge(monkeypatch)
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    first = await _upload(client, workspace["id"], batch["id"], name="a.txt", text="Ett", key="file-a")
    second = await _upload(client, workspace["id"], batch["id"], name="b.txt", text="Två", key="file-b")
    job_a = next(item["job_id"] for item in first["items"] if item["filename"] == "a.txt")
    job_b = next(item["job_id"] for item in second["items"] if item["filename"] == "b.txt")
    try:
        results = await asyncio.gather(
            run_document_ingest_job(factory, job_id=job_a),
            run_document_ingest_job(factory, job_id=job_b),
        )
        assert {result["status"] for result in results} == {"ready"}
        assert all(result["items_created"] == 0 for result in results)
    finally:
        set_knowledge_vector_store_factory(None)


@pytest.mark.asyncio
async def test_failed_job_is_shown_as_failed_on_get(client_db):
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    uploaded = await _upload(client, workspace["id"], batch["id"], name="avtal.txt", text="Avtal", key="fail-job")
    item = uploaded["items"][0]
    async with factory() as session:
        job = await session.get(Job, item["job_id"])
        job.status = "failed"
        job.error = "extract hung"
        await session.commit()
    shown = await client.get(f"/voice-workspaces/{workspace['id']}/ingest-batches/{batch['id']}")
    body = shown.json()["items"][0]
    assert body["stage"] == "failed"
    assert body["status"] == "failed"
    assert body["error"] == "extract hung"


@pytest.mark.asyncio
async def test_succeeded_extracting_job_is_reconciled_to_ready(client_db):
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    uploaded = await _upload(client, workspace["id"], batch["id"], name="avtal.txt", text="Avtal", key="done-job")
    item = uploaded["items"][0]
    async with factory() as session:
        job = await session.get(Job, item["job_id"])
        job.status = "succeeded"
        job.result = {
            "status": "running",
            "object_id": item["stored_object_id"],
            "document_version_id": "ver-1",
            "graph_work_id": "work-done",
            "chunks_indexed": 2,
        }
        session.add(GraphIngestWork(
            id="work-done",
            customer_id=1,
            scope_key="customer:1",
            payload={"kind": DOCUMENT_CATALOG_WRITE},
            status="completed",
            attempts=1,
        ))
        await session.commit()
    shown = await client.get(f"/voice-workspaces/{workspace['id']}/ingest-batches/{batch['id']}")
    body = shown.json()["items"][0]
    assert body["stage"] == "ready"
    assert body["searchable"] is True
    assert body["ingest_progress"] == 100


@pytest.mark.asyncio
async def test_dokumentforstaelse_finishes_without_waiting_for_embeddings(client_db, monkeypatch):
    store = _fake_knowledge(monkeypatch)
    started = asyncio.Event()
    release = asyncio.Event()

    class Slow(FakeEmbeddingProvider):
        async def embed(self, texts):
            started.set()
            await release.wait()
            return await super().embed(texts)

    monkeypatch.setattr(
        "app.services.document_knowledge.OpenAIEmbeddingProvider.from_settings",
        Slow,
    )
    original_replace = store.replace_document_chunks

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("document ingest must upsert, not replace the vector index")

    store.replace_document_chunks = forbidden
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    uploaded = await _upload(client, workspace["id"], batch["id"], name="avtal.txt", text="Avtal", key="index-after")
    job_id = uploaded["items"][0]["job_id"]
    try:
        task = asyncio.create_task(jobs_service._run_job(job_id))
        await asyncio.wait_for(started.wait(), timeout=5)
        async with factory() as session:
            job = await session.get(Job, job_id)
            source = await session.get(StoredObject, uploaded["items"][0]["stored_object_id"])
            item = await session.get(DocumentIngestBatchItem, uploaded["items"][0]["id"])
            assert job is not None and job.status == "succeeded"
            assert source is not None and document_text_ready(source)
            assert item is not None and item.stage == "indexing"
            assert store.chunks == []
        release.set()
        await task
        assert store.chunks
        assert all(item.chunk.metadata.get("knowledge_kind") == "document_chunk" for item in store.chunks)
    finally:
        release.set()
        store.replace_document_chunks = original_replace
        set_knowledge_vector_store_factory(None)


@pytest.mark.asyncio
async def test_embed_failure_keeps_extracted_text(client_db, monkeypatch):
    _fake_knowledge(monkeypatch)

    class Boom(FakeEmbeddingProvider):
        async def embed(self, texts):
            raise RuntimeError("vector_put_failed")

    monkeypatch.setattr(
        "app.services.document_knowledge.OpenAIEmbeddingProvider.from_settings",
        Boom,
    )
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    uploaded = await _upload(client, workspace["id"], batch["id"], name="avtal.txt", text="Avtal", key="boom")
    try:
        await jobs_service._run_job(uploaded["items"][0]["job_id"])
        async with factory() as session:
            job = await session.get(Job, uploaded["items"][0]["job_id"])
            source = await session.get(StoredObject, uploaded["items"][0]["stored_object_id"])
            assert job is not None and job.status == "succeeded"
            assert source is not None
            assert document_text_ready(source)
            assert source.knowledge_status == "partial"
    finally:
        set_knowledge_vector_store_factory(None)


@pytest.mark.asyncio
async def test_abandoned_upload_is_failed_on_get(client_db):
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    uploaded = await _upload(client, workspace["id"], batch["id"], name="ok.txt", text="Ok", key="ok")
    async with factory() as session:
        session.add(DocumentIngestBatchItem(
            id=new_id(),
            batch_id=batch["id"],
            client_key="ghost",
            filename="Avtal_98_Samboavtal.docx",
            content_type=UNDERLAG_DOCX_TYPE,
            size_bytes=12,
            stage="uploading",
            status="processing",
            created_at=utcnow() - timedelta(minutes=5),
            updated_at=utcnow() - timedelta(minutes=5),
        ))
        await session.commit()
    shown = await client.get(f"/voice-workspaces/{workspace['id']}/ingest-batches/{batch['id']}")
    ghost = next(item for item in shown.json()["items"] if item["filename"] == "Avtal_98_Samboavtal.docx")
    ok = next(item for item in shown.json()["items"] if item["filename"] == "ok.txt")
    assert ghost["stage"] == "failed"
    assert ghost["status"] == "failed"
    assert ghost["error"] == "upload_abandoned"
    assert ok["job_id"] == uploaded["items"][0]["job_id"]


@pytest.mark.asyncio
async def test_same_bytes_in_workspace_are_skipped(client_db):
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    first = await _upload(client, workspace["id"], batch["id"], name="avtal.txt", text="Samma", key="one")
    second = await _upload(client, workspace["id"], batch["id"], name="kopia.txt", text="Samma", key="two")
    original = next(item for item in first["items"] if item["filename"] == "avtal.txt")
    copy = next(item for item in second["items"] if item["filename"] == "kopia.txt")
    assert original["stage"] == "extracting"
    assert original["job_id"]
    assert copy["stage"] == "skipped"
    assert copy["status"] == "skipped"
    assert copy["job_id"] is None
    assert copy["stored_object_id"] == original["stored_object_id"]
    again = await _batch(client, workspace["id"])
    third = await _upload(client, workspace["id"], again["id"], name="igen.txt", text="Samma", key="three")
    skipped = third["items"][0]
    assert skipped["stage"] == "skipped"
    assert skipped["stored_object_id"] == original["stored_object_id"]
    other = await _workspace(client)
    other_batch = await _batch(client, other["id"])
    foreign = await _upload(client, other["id"], other_batch["id"], name="avtal.txt", text="Samma", key="other")
    assert foreign["items"][0]["stage"] == "extracting"
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(Job).where(Job.kind == "document_ingest")) == 2


@pytest.mark.asyncio
async def test_skip_uses_version_hash_when_object_hash_is_missing(client_db):
    client, factory = client_db
    workspace = await _workspace(client)
    batch = await _batch(client, workspace["id"])
    first = await _upload(client, workspace["id"], batch["id"], name="avtal.txt", text="Samma", key="hashless")
    source_id = first["items"][0]["stored_object_id"]
    digest = file_sha256(b"Samma")
    async with factory() as session:
        source = await session.get(StoredObject, source_id)
        source.content_sha256 = None
        scope = persist_scope_fields(customer_scope(source.customer_id))
        session.add(CanonicalDocumentRecord(
            id=source.id,
            source_object_id=source.id,
            source_type="uploaded_file",
            canonical_uri=f"stored-object:{source.id}",
            title=source.filename,
            extra={},
            **scope,
        ))
        session.add(DocumentVersionRecord(
            id=new_id(),
            document_id=source.id,
            content_hash=digest,
            mime_type="text/plain",
            extra={},
            **scope,
        ))
        await session.commit()
    later = await _batch(client, workspace["id"])
    second = await _upload(client, workspace["id"], later["id"], name="kopia.txt", text="Samma", key="hashless-2")
    skipped = second["items"][0]
    assert skipped["stage"] == "skipped"
    assert skipped["stored_object_id"] == source_id
