from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import func, select

from app.database.graph_v2 import GraphIngestWork
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentKnowledgeItem,
    DocumentKnowledgeRevision,
    DocumentVersionRecord,
    Job,
    StoredObject,
    TextUnitRecord,
)
from app.services import jobs as jobs_service
from app.services.document_ingest_status import document_text_ready
from app.serializers import utcnow
from app.services.document_qa.kinds import DOCUMENT_CATALOG_WRITE
from app.services.knowledge.models import KnowledgeQuery, KnowledgeScope
from app.services.knowledge.supabase_provider import SupabaseKnowledgeProvider
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.research.composition import set_knowledge_vector_store_factory
from tests.conftest import USER_USER_ID
from tests.knowledge_fakes import FakeEmbeddingProvider
from tests.test_knowledge_ingest import build_text_pdf


async def _upload_without_worker(user_client, filename: str, data: bytes, content_type: str):
    scheduled: list[str] = []
    jobs_service.set_schedule_hook(scheduled.append)
    response = await user_client.post(
        "/underlag",
        params={"module": "expertgranskning"},
        files={"file": (filename, data, content_type)},
    )
    assert response.status_code == 201, response.text
    assert scheduled == [response.json()["knowledge_job_id"]]
    return response.json(), scheduled[0]


def test_document_text_ready_uses_extracted_text_not_card_status():
    assert document_text_ready(SimpleNamespace(extraction_status="ok", extracted_text="Avtal"))
    assert document_text_ready(SimpleNamespace(extraction_status="ok", extracted_text="Avtal"))
    assert not document_text_ready(SimpleNamespace(extraction_status="ok", extracted_text="  "))
    assert not document_text_ready(SimpleNamespace(extraction_status="pending", extracted_text="Avtal"))
    assert not document_text_ready(SimpleNamespace(extraction_status="ok", extracted_text=None))


async def test_manual_document_knowledge_is_versioned_without_vector_index(
    user_client,
    client_db,
    monkeypatch,
):
    (_client, factory) = client_db
    uploaded, _job_id = await _upload_without_worker(
        user_client,
        "agreement.pdf",
        b"%PDF-1.4 fake",
        "application/pdf",
    )
    async with factory() as session:
        source = await session.get(StoredObject, uploaded["id"])
        assert source is not None
        source.extraction_status = "ok"
        source.extracted_text = "Avtalet gäller från 1 januari 2027."
        await session.commit()

    store = MemoryKnowledgeVectorStore()
    set_knowledge_vector_store_factory(lambda: store)
    monkeypatch.setattr(
        "app.services.document_knowledge.OpenAIEmbeddingProvider.from_settings",
        FakeEmbeddingProvider,
    )
    try:
        created = await user_client.post(
            f"/underlag/{uploaded['id']}/knowledge",
            json={
                "kind": "fact",
                "title": "Avtalets startdatum",
                "content": "Avtalet gäller från den 1 januari 2027.",
                "anchors": [
                    {
                        "anchor_type": "text",
                        "page_number": 1,
                        "locator": "page:1",
                        "exact_text": "Avtalet gäller från 1 januari 2027.",
                        "rects": [
                            {"x": 0.1, "y": 0.2, "width": 0.4, "height": 0.03}
                        ],
                    }
                ],
            },
        )
        assert created.status_code == 201, created.text
        item = created.json()
        assert item["origin"] == "manual"
        assert item["revision"] == 1
        assert item["anchors"][0]["page_number"] == 1
        assert store.chunks == []

        listed = await user_client.get(f"/underlag/{uploaded['id']}/knowledge")
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()] == [item["id"]]

        changed = await user_client.put(
            f"/underlag/{uploaded['id']}/knowledge/{item['id']}",
            json={
                "kind": "qa",
                "title": "När börjar avtalet gälla?",
                "question": "När börjar avtalet att gälla?",
                "content": "Den 1 januari 2027.",
                "anchors": item["anchors"],
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["revision"] == 2
        assert changed.json()["kind"] == "qa"
        assert store.chunks == []

        deleted = await user_client.delete(
            f"/underlag/{uploaded['id']}/knowledge/{item['id']}"
        )
        assert deleted.status_code == 204
        assert store.chunks == []
        assert (await user_client.get(f"/underlag/{uploaded['id']}/knowledge")).json() == []

        async with factory() as session:
            revision_count = await session.scalar(
                select(func.count(DocumentKnowledgeRevision.id)).where(
                    DocumentKnowledgeRevision.item_id == item["id"]
                )
            )
            row = await session.get(DocumentKnowledgeItem, item["id"])
            assert revision_count == 3
            assert row is not None and row.status == "archived"
            assert row.created_by_user_id == USER_USER_ID
    finally:
        set_knowledge_vector_store_factory(None)
        jobs_service.set_schedule_hook(None)


async def test_document_ingest_indexes_text_units_without_generated_cards(  # noqa: PLR0915
    user_client,
    client_db,
    monkeypatch,
):
    (_client, factory) = client_db
    pdf = build_text_pdf("Avtalet galler fran 1 januari 2027.")
    uploaded, job_id = await _upload_without_worker(
        user_client,
        "agreement.pdf",
        pdf,
        "application/pdf",
    )
    store = MemoryKnowledgeVectorStore()
    embeddings = FakeEmbeddingProvider()
    set_knowledge_vector_store_factory(lambda: store)
    monkeypatch.setattr(
        "app.services.document_knowledge.OpenAIEmbeddingProvider.from_settings",
        lambda: embeddings,
    )
    jobs_service.set_schedule_hook(None)
    try:
        await jobs_service._run_job(job_id)

        async with factory() as session:
            source = await session.get(StoredObject, uploaded["id"])
            job = await session.get(Job, job_id)
            assert source is not None
            assert source.extraction_status == "ok"
            assert source.knowledge_status == "ready"
            assert document_text_ready(source)
            assert "Avtalet galler" in (source.extracted_text or "")
            assert job is not None and job.status == "succeeded"
            assert (job.result or {}).get("items_created") == 0
            rows = list(
                (
                    await session.execute(
                        select(DocumentKnowledgeItem).where(
                            DocumentKnowledgeItem.source_object_id == source.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert rows == []
            units = list(
                (
                    await session.execute(
                        select(TextUnitRecord).where(TextUnitRecord.document_id == source.id)
                    )
                )
                .scalars()
                .all()
            )
            assert units
            assert any("Avtalet galler" in unit.text for unit in units)
            canonical = await session.get(CanonicalDocumentRecord, source.id)
            assert canonical is not None
            assert canonical.source_type == "uploaded_file"
            assert canonical.canonical_uri == f"stored-object:{source.id}"
            versions = list(
                (
                    await session.execute(
                        select(DocumentVersionRecord).where(
                            DocumentVersionRecord.document_id == source.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(versions) == 1
            assert versions[0].superseded_at is None
            assert all(unit.document_version_id == versions[0].id for unit in units)
            catalog_jobs = list(
                (await session.execute(
                    select(GraphIngestWork).where(
                        GraphIngestWork.customer_id == source.customer_id,
                    )
                )).scalars().all()
            )
            assert len(catalog_jobs) == 1
            assert catalog_jobs[0].payload["kind"] == DOCUMENT_CATALOG_WRITE
            assert catalog_jobs[0].payload["document_id"] == source.id
            assert catalog_jobs[0].payload["document_version_id"] == versions[0].id

            assert store.chunks
            assert all(item.chunk.metadata.get("knowledge_kind") == "document_chunk" for item in store.chunks)
            assert all("document_knowledge_item_id" not in item.chunk.metadata for item in store.chunks)
            provider = SupabaseKnowledgeProvider(
                session,
                vector_store=store,
                embeddings=embeddings,
            )
            hits = await provider.search(
                KnowledgeQuery(
                    query="Avtalet galler fran 1 januari 2027.",
                    scope=KnowledgeScope(
                        customer_id=source.customer_id,
                        case_id=source.id,
                        module=source.module,
                        workspace_id=source.workspace_id,
                        readable_workspace_ids=(source.workspace_id,) if source.workspace_id else None,
                    ),
                )
            )
            assert hits
            assert all(hit.metadata.get("knowledge_kind") == "document_chunk" for hit in hits)
            assert all(hit.metadata.get("discovery_kind") != "document_item" for hit in hits)
            assert all(hit.document_id == uploaded["id"] for hit in hits)
            assert all(hit.metadata.get("document_version_id") for hit in hits)
            assert all("Avtalet galler fran 1 januari 2027." in hit.excerpt for hit in hits)

        listed = await user_client.get(f"/underlag/{uploaded['id']}/knowledge")
        assert listed.status_code == 200
        assert listed.json() == []
    finally:
        set_knowledge_vector_store_factory(None)
        jobs_service.set_schedule_hook(None)


async def test_generated_cards_are_hidden_from_document_knowledge_api(
    user_client,
    client_db,
):
    (_client, factory) = client_db
    uploaded, _job_id = await _upload_without_worker(
        user_client,
        "agreement.pdf",
        b"%PDF-1.4 fake",
        "application/pdf",
    )
    async with factory() as session:
        session.add(
            DocumentKnowledgeItem(
                id="leftover-generated",
                source_object_id=uploaded["id"],
                customer_id=1,
                kind="qa",
                origin="generated",
                status="active",
                title="Genererat kort",
                question="När börjar avtalet?",
                content="1 januari 2027",
                revision=1,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        await session.commit()
    listed = await user_client.get(f"/underlag/{uploaded['id']}/knowledge")
    assert listed.status_code == 200
    assert listed.json() == []
    jobs_service.set_schedule_hook(None)


async def test_document_ingest_marks_scanned_pdf_as_needs_ocr(
    user_client,
    client_db,
    monkeypatch,
):
    (_client, factory) = client_db
    pdf = build_text_pdf("", with_text=False)
    uploaded, job_id = await _upload_without_worker(
        user_client,
        "scan.pdf",
        pdf,
        "application/pdf",
    )
    store = MemoryKnowledgeVectorStore()
    set_knowledge_vector_store_factory(lambda: store)
    monkeypatch.setattr(
        "app.services.document_knowledge.OpenAIEmbeddingProvider.from_settings",
        FakeEmbeddingProvider,
    )
    jobs_service.set_schedule_hook(None)
    try:
        await jobs_service._run_job(job_id)

        async with factory() as session:
            source = await session.get(StoredObject, uploaded["id"])
            job = await session.get(Job, job_id)
            assert source is not None
            assert source.extraction_status == "needs_ocr"
            assert source.knowledge_status == "needs_ocr"
            assert not document_text_ready(source)
            assert job is not None and job.status == "succeeded"
            assert store.chunks == []
    finally:
        set_knowledge_vector_store_factory(None)
        jobs_service.set_schedule_hook(None)
