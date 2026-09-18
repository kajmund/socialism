from __future__ import annotations

from sqlalchemy import func, select

from app.database.models import DocumentKnowledgeItem, DocumentKnowledgeRevision, Job, StoredObject
from app.llm import set_structured_completer
from app.services import jobs as jobs_service
from app.services.document_knowledge import (
    GeneratedDocumentKnowledge,
    GeneratedDocumentKnowledgeBatch,
)
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


async def test_manual_document_knowledge_is_versioned_and_semantically_indexed(
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
    embeddings = FakeEmbeddingProvider()
    set_knowledge_vector_store_factory(lambda: store)
    monkeypatch.setattr(
        "app.services.document_knowledge.OpenAIEmbeddingProvider.from_settings",
        lambda: embeddings,
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
        assert len(store.chunks) == 1
        assert store.chunks[0].chunk.case_id == uploaded["id"]

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
        assert len(store.chunks) == 1

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


async def test_document_ingest_generates_anchored_items_and_case_knowledge(
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

    async def structured(_messages, response_model):
        assert response_model is GeneratedDocumentKnowledgeBatch
        return GeneratedDocumentKnowledgeBatch(
            items=[
                GeneratedDocumentKnowledge(
                    kind="qa",
                    title="Avtalets startdatum",
                    question="När börjar avtalet att gälla?",
                    content="Avtalet börjar gälla den 1 januari 2027.",
                    locator="page:1",
                    exact_quote="Avtalet galler fran 1 januari 2027.",
                    retrieval_queries=["Vilket datum börjar avtalet gälla?"],
                )
            ]
        )

    set_structured_completer(structured)
    jobs_service.set_schedule_hook(None)
    try:
        await jobs_service._run_job(job_id)

        async with factory() as session:
            source = await session.get(StoredObject, uploaded["id"])
            job = await session.get(Job, job_id)
            assert source is not None
            assert source.extraction_status == "ok"
            assert source.knowledge_status == "ready"
            assert "Avtalet galler" in (source.extracted_text or "")
            assert job is not None and job.status == "succeeded"
            rows = list(
                (
                    await session.execute(
                        select(DocumentKnowledgeItem).where(
                            DocumentKnowledgeItem.source_object_id == source.id,
                            DocumentKnowledgeItem.status == "active",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].origin == "generated"

            provider = SupabaseKnowledgeProvider(
                session,
                vector_store=store,
                embeddings=embeddings,
            )
            hits = await provider.search(
                KnowledgeQuery(
                    query="När börjar avtalet?",
                    scope=KnowledgeScope(
                        customer_id=source.customer_id,
                        case_id=source.id,
                        module=source.module,
                    ),
                )
            )
            assert any(hit.metadata.get("knowledge_kind") == "document_item" for hit in hits)

        listed = await user_client.get(f"/underlag/{uploaded['id']}/knowledge")
        assert listed.status_code == 200
        item = listed.json()[0]
        assert item["kind"] == "qa"
        assert item["anchors"][0]["locator"] == "page:1"
        assert item["anchors"][0]["rects"]
    finally:
        set_structured_completer(None)
        set_knowledge_vector_store_factory(None)
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
            assert job is not None and job.status == "succeeded"
            assert store.chunks == []
    finally:
        set_knowledge_vector_store_factory(None)
        jobs_service.set_schedule_hook(None)
