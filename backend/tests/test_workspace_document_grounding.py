from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.database.base import Base
from app.database.models import CanonicalDocumentRecord, DocumentKnowledgeItem, DocumentVersionRecord, Kund, StoredObject, UserAccount
from app.serializers import utcnow
from app.services.document_knowledge import create_manual_document_knowledge, supporting_text_unit_ids
from app.services.knowledge.canonical_ingest import ingest_extracted_source
from app.services.knowledge.extractors import ExtractedBlock, ExtractedDocument
from app.services.knowledge.models import KnowledgeDocument, KnowledgeQuery, KnowledgeScope, KnowledgeScopeRequiredError
from app.services.knowledge.persistence import current_text_units, text_unit_from_record
from app.services.knowledge.supabase_provider import SupabaseKnowledgeProvider
from app.services.knowledge.shared_document_grounding import readable_shared_document_passage
from app.services.knowledge.units import hash_text
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.research.composition import set_knowledge_vector_store_factory
from app.services.research.knowledge_source import KnowledgeResearchSource
from app.services.research.models import ResearchContext, ResearchNeed
from app.services.research.workspace_grounding import passages_allowed
from app.services.knowledge.scope import shared_scope
from app.services.underlag_schemas import DocumentKnowledgeItemWrite
from app.services.workspaces import create_client_workspace, ensure_company_workspace
from tests.knowledge_fakes import FakeEmbeddingProvider

SOURCE_TEXT = "Avtalets uppsägningstid är sex månader."


@pytest.fixture
async def documents(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'workspace.db'}", pool_size=1, max_overflow=0, pool_timeout=1)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="Byrån", slug="workspace-test", available_modules=["dd", "expertgranskning"]))
        session.add(UserAccount(id="workspace-user", email="workspace@test.invalid", role="user", kund_id=1))
    async with factory.begin() as session:
        common = await ensure_company_workspace(session, customer_id=1)
        first = await create_client_workspace(session, customer_id=1, user_id="workspace-user", name="Klient A")
        second = await create_client_workspace(session, customer_id=1, user_id="workspace-user", name="Klient B")
        workspace_ids = common.id, first.id, second.id
    store, embeddings = MemoryKnowledgeVectorStore(), FakeEmbeddingProvider()
    for index, workspace_id in enumerate(workspace_ids):
        await _seed_document(factory, store, embeddings, f"source-{index}", workspace_id=workspace_id)
    yield factory, store, embeddings, workspace_ids
    await engine.dispose()


async def _seed_document(factory, store, embeddings, source_id: str, *, workspace_id: str):
    async with factory.begin() as session:
        session.add(StoredObject(
            id=source_id, customer_id=1, workspace_id=workspace_id, owner_user_id="workspace-user",
            module="expertgranskning", kind="underlag", bucket="test", object_key=source_id,
            filename=f"{source_id}.txt", content_type="text/plain", size_bytes=len(SOURCE_TEXT),
        ))
    async with factory() as session:
        return await _ingest(session, store, embeddings, source_id, workspace_id=workspace_id)


async def _ingest(session, store, embeddings, source_id: str, *, workspace_id: str):
    return await ingest_extracted_source(
        session, extracted=ExtractedDocument([ExtractedBlock(SOURCE_TEXT, "line:1")]),
        document=KnowledgeDocument(
            document_id=source_id, provider="supabase", external_id=source_id,
            title=source_id, mime_type="text/plain",
            scope=KnowledgeScope(customer_id=1, workspace_id=workspace_id, module="expertgranskning"),
            metadata={"source_object_id": source_id, "workspace_id": workspace_id},
        ),
        source_type="uploaded_file", canonical_uri=f"stored-object:{source_id}",
        content_hash=hash_text(SOURCE_TEXT), customer_id=1, source_object_id=source_id,
        embeddings=embeddings, vector_store=store,
    )


async def _search(documents, scope: KnowledgeScope, *, filters=None):
    factory, store, embeddings, _workspace_ids = documents
    async with factory() as session:
        provider = SupabaseKnowledgeProvider(session, store, embeddings)
        return await provider.search(KnowledgeQuery("Avtalets uppsägningstid", scope, filters=filters or {}))


async def test_active_workspace_reads_common_and_active_without_other_client(documents):
    _factory, _store, _embeddings, (common, first, _second) = documents
    hits = await _search(documents, KnowledgeScope(customer_id=1, workspace_id=first, readable_workspace_ids=(common, first), module="dd"))
    assert {hit.document_id for hit in hits} == {"source-0", "source-1"}
    assert {hit.metadata["workspace_id"] for hit in hits} == {common, first}
    assert all(hit.excerpt == SOURCE_TEXT for hit in hits)


async def test_omitted_workspace_only_reads_company(documents):
    hits = await _search(documents, KnowledgeScope(customer_id=1))
    assert [hit.document_id for hit in hits] == ["source-0"]


async def test_orphaned_upload_is_not_reused_as_unattached_private_knowledge(documents):
    factory, _store, _embeddings, (common, first, _second) = documents
    async with factory() as session:
        document = await session.get(CanonicalDocumentRecord, "source-1")
        document.source_object_id = None
        await session.commit()
        units = await current_text_units(session, document.id)
        context = ResearchContext(KnowledgeScope(customer_id=1, workspace_id=first, readable_workspace_ids=(common, first)))
        assert not await passages_allowed(session, units, context)


async def test_selected_source_and_version_are_sql_authoritative(documents):
    factory, _store, embeddings, (common, first, _second) = documents
    async with factory() as session:
        version = await session.scalar(select(DocumentVersionRecord).where(DocumentVersionRecord.document_id == "source-1"))
        version_id = version.id
    scope = KnowledgeScope(customer_id=1, workspace_id=first, readable_workspace_ids=(common, first), allowed_source_object_ids=("source-1",), allowed_document_version_ids=(version_id,))
    hits = await _search(documents, scope)
    assert [hit.document_id for hit in hits] == ["source-1"]
    before = len(embeddings.calls)
    with pytest.raises(KnowledgeScopeRequiredError):
        await _search(documents, replace(scope, allowed_source_object_ids=("source-2",)))
    with pytest.raises(KnowledgeScopeRequiredError):
        await _search(documents, replace(scope, allowed_document_version_ids=("nonexistent-version",)))
    assert len(embeddings.calls) == before


async def test_same_hash_reuses_sql_ids_and_vectors(documents):
    factory, store, embeddings, (_common, first, _second) = documents
    before_ids = {chunk.chunk.chunk_id for chunk in store.chunks if chunk.chunk.document_id == "source-1"}
    before_calls = len(embeddings.calls)
    async with factory() as session:
        result = await _ingest(session, store, embeddings, "source-1", workspace_id=first)
        units = await current_text_units(session, "source-1")
        versions = list(await session.scalars(select(DocumentVersionRecord).where(DocumentVersionRecord.document_id == "source-1")))
    assert result.reused_version
    assert len(versions) == 1
    assert {unit.id for unit in units} == before_ids
    assert {unit.document_version_id for unit in units} == {result.document_version_id}
    assert result.segmented.version.id == result.document_version_id
    assert {unit.id for unit in result.segmented.text_units} == before_ids
    assert len(embeddings.calls) == before_calls


async def _create_qa(documents, monkeypatch):
    factory, store, embeddings, _workspace_ids = documents
    set_knowledge_vector_store_factory(lambda: store)
    monkeypatch.setattr("app.services.document_knowledge.OpenAIEmbeddingProvider.from_settings", lambda: embeddings)
    try:
        async with factory() as session:
            source = await session.get(StoredObject, "source-1")
            item = await create_manual_document_knowledge(
                session, source=source, user_id="workspace-user",
                body=DocumentKnowledgeItemWrite(
                    kind="qa", title="Avtalets uppsägningstid", question="Vad är avtalets uppsägningstid?",
                    content="Sammanfattat svar: sex månader.",
                    anchors=[{"anchor_type": "text", "locator": "line:1", "exact_text": SOURCE_TEXT}],
                ),
            )
            item_id = item.id
            await session.commit()
    finally:
        set_knowledge_vector_store_factory(None)
    return item_id


async def test_qa_discovery_returns_original_passage_and_frozen_revision(documents, monkeypatch):
    item_id = await _create_qa(documents, monkeypatch)
    _factory, _store, _embeddings, (_common, first, _second) = documents
    hits = await _search(documents, KnowledgeScope(customer_id=1, workspace_id=first), filters={"knowledge_kind": "document_item"})
    assert len(hits) == 1
    hit = hits[0]
    assert hit.document_id == "source-1"
    assert hit.excerpt == SOURCE_TEXT
    assert hit.metadata["document_knowledge_item_id"] == item_id
    assert hit.metadata["item_revision"] == 1
    assert hit.metadata["qa_snapshot"]["content"] == "Sammanfattat svar: sex månader."
    assert hit.metadata["document_version_id"]
    assert hit.metadata["text_unit_ids"] == [hit.metadata["text_unit_id"]]


async def test_qa_card_filter_preserves_selected_snapshot_when_cards_share_passage(documents, monkeypatch):
    first_item = await _create_qa(documents, monkeypatch)
    second_item = await _create_qa(documents, monkeypatch)
    _factory, _store, _embeddings, (_common, first, _second) = documents
    scope = KnowledgeScope(customer_id=1, workspace_id=first)
    unselected = await _search(documents, scope, filters={"knowledge_kind": "document_item"})
    assert len(unselected) == 1
    assert first_item != second_item
    for selected_item in (first_item, second_item):
        hits = await _search(documents, scope, filters={
            "knowledge_kind": "document_item", "item_kind": "qa",
            "document_knowledge_item_id": selected_item,
        })
        assert len(hits) == 1
        assert hits[0].metadata["document_knowledge_item_id"] == selected_item
        assert hits[0].excerpt == SOURCE_TEXT


@pytest.mark.parametrize("change", ["needs_review", "revision", "fabricated_quote"])
async def test_stale_or_ungrounded_qa_vectors_are_rejected(documents, monkeypatch, change):
    item_id = await _create_qa(documents, monkeypatch)
    factory, _store, _embeddings, (_common, first, _second) = documents
    async with factory.begin() as session:
        item = await session.scalar(select(DocumentKnowledgeItem).options(selectinload(DocumentKnowledgeItem.anchors)).where(DocumentKnowledgeItem.id == item_id))
        if change == "revision":
            item.revision += 1
        elif change == "needs_review":
            item.status = "needs_review"
        else:
            item.anchors[0].exact_text = "Avtalets uppsägningstid är tre månader."
    assert await _search(documents, KnowledgeScope(customer_id=1, workspace_id=first), filters={"knowledge_kind": "document_item"}) == []


async def test_locator_cannot_validate_fabricated_quote(documents):
    factory, _store, _embeddings, _workspace_ids = documents
    async with factory() as session:
        units = [text_unit_from_record(unit) for unit in await current_text_units(session, "source-1")]
    assert supporting_text_unit_ids(locator="line:1", exact_quote=SOURCE_TEXT, units=units)
    assert supporting_text_unit_ids(locator="line:1", exact_quote="Avtalets uppsägningstid är tre månader.", units=units) == []
    assert supporting_text_unit_ids(locator="wrong", exact_quote=SOURCE_TEXT, units=units) == []


async def test_connection_released_while_retrieval_embedding_is_pending(documents):
    factory, store, _embeddings, (_common, first, _second) = documents
    started, release = asyncio.Event(), asyncio.Event()

    class PendingEmbedding(FakeEmbeddingProvider):
        async def embed(self, texts):
            started.set()
            await release.wait()
            return await super().embed(texts)

    async with factory() as inputs:
        await inputs.get(StoredObject, "source-1")
        provider = SupabaseKnowledgeProvider(inputs, store, PendingEmbedding())
        task = asyncio.create_task(provider.search(KnowledgeQuery("Avtalets", KnowledgeScope(customer_id=1, workspace_id=first))))
        await asyncio.wait_for(started.wait(), 1)
        try:
            async with factory() as other:
                assert await asyncio.wait_for(other.scalar(text("SELECT 1")), 1) == 1
        finally:
            release.set()
            await task


async def test_retrieval_does_not_commit_unrelated_pending_writes(documents):
    factory, store, embeddings, (_common, first, _second) = documents
    async with factory() as session:
        source = await session.get(StoredObject, "source-1")
        source.filename = "unrelated-change.txt"
        provider = SupabaseKnowledgeProvider(session, store, embeddings)
        with pytest.raises(RuntimeError, match="clean input transaction"):
            await provider.search(KnowledgeQuery("Avtalets", KnowledgeScope(customer_id=1, workspace_id=first)))
    async with factory() as session:
        assert (await session.get(StoredObject, "source-1")).filename == "source-1.txt"


async def test_retrieval_preserves_unrelated_flushed_write_transaction(documents):
    factory, store, embeddings, (_common, first, _second) = documents
    async with factory() as session:
        source = await session.get(StoredObject, "source-1")
        source.filename = "flushed-unrelated-change.txt"
        await session.flush()
        provider = SupabaseKnowledgeProvider(session, store, embeddings)
        with pytest.raises(RuntimeError, match="clean input transaction"):
            await provider.search(KnowledgeQuery("Avtalets", KnowledgeScope(customer_id=1, workspace_id=first)))
        assert session.in_transaction()
        assert source.filename == "flushed-unrelated-change.txt"
        await session.rollback()
    async with factory() as session:
        assert (await session.get(StoredObject, "source-1")).filename == "source-1.txt"


async def test_canonical_ids_are_durable_while_ingest_embedding_is_pending(documents):
    factory, store, _embeddings, (_common, first, _second) = documents
    started, release = asyncio.Event(), asyncio.Event()

    class PendingEmbedding(FakeEmbeddingProvider):
        async def embed(self, texts):
            started.set()
            await release.wait()
            return await super().embed(texts)

    task = asyncio.create_task(_seed_document(factory, store, PendingEmbedding(), "source-pending", workspace_id=first))
    await asyncio.wait_for(started.wait(), 1)
    try:
        async with factory() as other:
            units = await asyncio.wait_for(current_text_units(other, "source-pending"), 1)
            assert units
            persisted_ids = {unit.id for unit in units}
    finally:
        release.set()
        result = await task
    assert {unit.id for unit in result.segmented.text_units} == persisted_ids
    assert {item.chunk.chunk_id for item in store.chunks if item.chunk.document_id == "source-pending"} == persisted_ids


async def test_upload_releases_connection_while_object_storage_is_pending(documents, monkeypatch):
    from app.services.document_upload import UnderlagUpload, upload_document

    factory, _store, _embeddings, (_common, first, _second) = documents
    started, release = asyncio.Event(), asyncio.Event()

    async def pending_bucket(_bucket):
        started.set()
        await release.wait()

    monkeypatch.setattr("app.services.document_upload.ensure_bucket", pending_bucket)
    async with factory() as inputs:
        await inputs.get(StoredObject, "source-1")
        task = asyncio.create_task(upload_document(inputs, UnderlagUpload(
            customer_id=1, owner_user_id="workspace-user", module="dd",
            filename="avtal.md", content_type="text/markdown", data=SOURCE_TEXT.encode(), workspace_id=first,
        )))
        await asyncio.wait_for(started.wait(), 1)
        try:
            async with factory() as other:
                assert await asyncio.wait_for(other.scalar(text("SELECT 1")), 1) == 1
        finally:
            release.set()
            uploaded = await task
        assert uploaded.workspace_id == first
        await inputs.commit()


async def test_global_document_knowledge_stays_shared_and_private_sources_stay_private(documents):
    factory, store, embeddings, (common, first, _second) = documents
    async with factory() as session:
        result = await ingest_extracted_source(
            session, extracted=ExtractedDocument([ExtractedBlock("Allmän avtalspolicy för avtalsgranskning.", "line:1")]),
            document=KnowledgeDocument(
                document_id="global-reference", provider="supabase", external_id="global-reference",
                title="Global avtalskunskap", mime_type="text/plain",
                scope=KnowledgeScope(customer_id=None, scope_type="shared"),
            ),
            source_type="shared_reference", canonical_uri="shared-reference:workspace-test",
            content_hash=hash_text("Allmän avtalspolicy för avtalsgranskning."), scope=shared_scope(),
            embeddings=embeddings, vector_store=store,
        )
        provider = SupabaseKnowledgeProvider(session, store, embeddings)
        domain = KnowledgeResearchSource(provider, source_type="domain_knowledge")
        context = ResearchContext(KnowledgeScope(customer_id=1, workspace_id=first, readable_workspace_ids=(common, first), allowed_source_object_ids=("source-1",)))
        need = ResearchNeed("general", "avtalspolicy avtalets uppsägningstid", "Bedöm avtalet")
        global_hits = await domain.research(need, context)
        private = KnowledgeResearchSource(provider, source_type="case_knowledge")
        private_hits = await private.research(need, context)
    assert [hit.source_id for hit in global_hits] == ["global-reference"]
    assert global_hits[0].metadata["scope_type"] == "shared"
    assert global_hits[0].metadata["workspace_id"] is None
    assert global_hits[0].metadata["document_version_id"] == result.document_version_id
    assert {hit.source_id for hit in private_hits} == {"source-1"}
    assert all(hit.metadata["scope_type"] == "customer" for hit in private_hits)
    async with factory() as session:
        provider = SupabaseKnowledgeProvider(session, store, embeddings)
        another_customer = await provider.search(KnowledgeQuery("avtalspolicy", KnowledgeScope(customer_id=999), filters={"scope_type": "shared"}))
    assert [hit.document_id for hit in another_customer] == ["global-reference"]
    async with factory.begin() as session:
        shared_document = await session.get(CanonicalDocumentRecord, "global-reference")
        shared_document.source_object_id = "source-1"
    async with factory() as session:
        provider = SupabaseKnowledgeProvider(session, store, embeddings)
        inconsistent_hits = await provider.search(KnowledgeQuery("avtalspolicy", KnowledgeScope(customer_id=999), filters={"scope_type": "shared"}))
    assert inconsistent_hits == []
    async with factory.begin() as session:
        document = await session.get(CanonicalDocumentRecord, "global-reference")
        document.source_object_id = None
        version = await session.get(DocumentVersionRecord, result.document_version_id)
        version.superseded_at = utcnow()
    async with factory() as session:
        unit = (await current_text_units(session, "global-reference"))
        assert unit == []
        from app.database.models import TextUnitRecord
        original = await session.scalar(select(TextUnitRecord).where(TextUnitRecord.document_version_id == result.document_version_id))
        assert await readable_shared_document_passage(session, original) is None
        historical = await readable_shared_document_passage(session, original, allow_superseded=True)
        assert historical is not None and historical[1].id == result.document_version_id


async def test_customer_stored_object_cannot_be_ingested_as_global_knowledge(documents):
    factory, store, embeddings, _workspace_ids = documents
    before = len(embeddings.calls)
    async with factory() as session:
        with pytest.raises(ValueError, match="cannot be ingested as global"):
            await ingest_extracted_source(
                session, extracted=ExtractedDocument([ExtractedBlock(SOURCE_TEXT, "line:1")]),
                document=KnowledgeDocument(document_id="invalid-global", provider="supabase", external_id="source-1", title="Avtal", mime_type="text/plain", scope=KnowledgeScope(customer_id=None, scope_type="shared")),
                source_type="shared_reference", canonical_uri="stored-object:source-1",
                content_hash=hash_text(SOURCE_TEXT), scope=shared_scope(), source_object_id="source-1",
                embeddings=embeddings, vector_store=store,
            )
        assert await session.get(CanonicalDocumentRecord, "invalid-global") is None
    assert len(embeddings.calls) == before
