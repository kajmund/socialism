"""PDF search reads each original once with every external boundary released."""

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import CanonicalDocumentRecord, DocumentKnowledgeAnchor, DocumentKnowledgeItem, DocumentKnowledgeItemTextUnit, DocumentVersionRecord, Kund, StoredObject, UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceReference
from app.services.knowledge.models import KnowledgeHit, KnowledgeQuery, KnowledgeScope
from app.services.knowledge.provider import SUPABASE_PROVIDER_ID
from app.services.knowledge.vector_store import SupabaseVectorBucketStore, VectorBucketRecord
from app.services.workspace import search
from app.services.workspace.service import add_source, create_workspace
from app.services.workspace.tools import execute_workspace_tool
from tests.text_unit_fakes import persisted_text_unit

PASSAGE = "Synthetic parking receipt. Amount 43.50 SEK."


async def seed_source(session, workspace, user, identity, *, attach=True):
    source = StoredObject(id=identity, workspace_id=workspace.workspace_id, customer_id=1, owner_user_id=user.id,
        module="dd", kind="underlag", bucket="synthetic", object_key=f"{identity}.pdf", filename=f"{identity}.pdf",
        content_type="application/pdf", size_bytes=100, extraction_status="ok", extracted_text=PASSAGE,
        knowledge_status="ready")
    session.add(source)
    await session.flush()
    if attach:
        await add_source(session, workspace, identity)
    fields = {"scope_type": "customer", "scope_key": "customer:1", "customer_id": 1}
    document = CanonicalDocumentRecord(id=f"doc-{identity}", **fields, source_object_id=identity,
        source_type="uploaded_file", canonical_uri=f"stored-object:{identity}", title=source.filename,
        extra={"workspace_id": workspace.workspace_id})
    session.add(document)
    await session.flush()
    version = DocumentVersionRecord(id=f"version-{identity}", **fields, document_id=document.id,
        mime_type="application/pdf", content_hash=f"hash-{identity}", ingested_at=datetime.now(UTC))
    session.add(version)
    await session.flush()
    session.add(await persisted_text_unit(session, id=f"unit-{identity}", **fields, document_id=document.id,
        document_version_id=version.id, ordinal=0, text=PASSAGE, locator="page:1", ingested_at=datetime.now(UTC)))


@pytest.fixture
async def pdf_search_db(tmp_path, research_overgraph):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/pdf-search.db", pool_size=1, max_overflow=0, pool_timeout=.3)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=1, name="Synthetic customer", slug="pdf-search-cache", available_modules=["dd"]))
        await session.flush()
        user = UserAccount(id="synthetic-owner", email="synthetic@example.test", role="user", kund_id=1)
        session.add(user)
        await session.flush()
        workspace = await create_workspace(session, user, title="Synthetic receipts", module="dd")
        ids = user.id, workspace.id
        for ordinal in range(2):
            await seed_source(session, workspace, user, f"synthetic-receipt-{ordinal}")
        await session.commit()
    yield factory, ids
    await engine.dispose()


async def another_client(factory):
    async with factory() as session:
        assert await asyncio.wait_for(session.scalar(text("SELECT 1")), timeout=1) == 1


def configure_external_calls(factory, monkeypatch, *, hit_count):
    calls = {"embed": 0, "vector": [], "storage": [], "rects": []}
    class Embeddings:
        dimension = 2
        async def embed(self, _texts):
            await another_client(factory)
            calls["embed"] += 1
            return [[1.0, 0.0]]
    class Vectors:
        async def search(self, query):
            await another_client(factory)
            identity, = query.query.scope.allowed_source_object_ids
            calls["vector"].append(identity)
            hit = KnowledgeHit(document_id=f"doc-{identity}", provider=SUPABASE_PROVIDER_ID, title="Synthetic receipt",
                excerpt=PASSAGE, locator="page:1", score=.9,
                metadata={"text_unit_id": f"unit-{identity}", "document_version_id": f"version-{identity}"})
            return [hit] * hit_count
    async def storage(bucket, key):
        await another_client(factory)
        calls["storage"].append((bucket, key))
        return key.encode(), "application/pdf"
    def rects(data, page, quote):
        calls["rects"].append((data.decode(), page, quote == PASSAGE))
        return [{"x": .1, "y": .2, "width": .3, "height": .04}]
    monkeypatch.setattr(search.OpenAIEmbeddingProvider, "from_settings", Embeddings)
    monkeypatch.setattr(search, "require_knowledge_vector_store", Vectors)
    monkeypatch.setattr(search, "get_object", storage)
    monkeypatch.setattr(search, "_pdf_quote_rects", rects)
    return calls


@pytest.mark.parametrize("hit_count", [2, 80])
async def test_pdf_original_loaded_once_per_source_and_pool_is_free_at_all_external_calls(pdf_search_db, monkeypatch, hit_count):
    factory, ids = pdf_search_db
    calls = configure_external_calls(factory, monkeypatch, hit_count=hit_count)
    async with factory() as session:
        user = await session.get(UserAccount, ids[0])
        result = await execute_workspace_tool(session, workspace_id=ids[1], user=user, tool_name="search_knowledge",
            arguments={"query": "Synthetic parking period"}, idempotency_key="pdf-cache-search")
        await session.commit()
    assert calls["embed"] == 1
    assert set(calls["vector"]) == {"synthetic-receipt-0", "synthetic-receipt-1"}
    assert sorted(calls["storage"]) == [("synthetic", "synthetic-receipt-0.pdf"), ("synthetic", "synthetic-receipt-1.pdf")]
    assert len(calls["rects"]) == hit_count * 2
    assert {key for key, page, matches in calls["rects"] if page == 1 and matches} == {
        "synthetic-receipt-0.pdf", "synthetic-receipt-1.pdf"}
    assert len(result["items"]) == 2
    assert all(item["anchor"]["page_number"] == 1 and len(item["anchor"]["rects"]) == 1 for item in result["items"])


@pytest.mark.parametrize("content_type,hit_count", [("text/plain", 1), ("application/pdf", 0)])
async def test_non_pdf_or_no_hits_does_not_load_original(pdf_search_db, monkeypatch, content_type, hit_count):
    factory, _ids = pdf_search_db
    source = search.SourceInput("synthetic", "dd", "version", PASSAGE, "synthetic.pdf", content_type,
        "synthetic", "synthetic.pdf", ("current-version",))
    class Embeddings:
        dimension = 2
        async def embed(self, _texts):
            await another_client(factory)
            return [[1.0, 0.0]]
    class Vectors:
        async def search(self, _query):
            await another_client(factory)
            return [KnowledgeHit(document_id="synthetic", provider=SUPABASE_PROVIDER_ID, title="Synthetic",
                excerpt=PASSAGE, locator="page:1", score=.9)] * hit_count
    async def forbidden_storage(*_args):
        raise AssertionError("Empty search results or non-PDF hits must not fetch an original")
    monkeypatch.setattr(search.OpenAIEmbeddingProvider, "from_settings", Embeddings)
    monkeypatch.setattr(search, "require_knowledge_vector_store", Vectors)
    monkeypatch.setattr(search, "get_object", forbidden_storage)
    found = await search._external_search([source], KnowledgeQuery(query="Synthetic", scope=KnowledgeScope(customer_id=1)))
    assert len(found) == hit_count
    assert all(candidate[2] is None for candidate in found)


async def test_qa_discovery_rectangles_use_original_quote_after_canonical_grounding(pdf_search_db, monkeypatch):
    factory, ids = pdf_search_db
    identity, quote = "synthetic-receipt-0", "Amount 43.50 SEK."
    async with factory() as session:
        item = DocumentKnowledgeItem(id="synthetic-qa", source_object_id=identity, customer_id=1,
            kind="qa", origin="generated", status="active", revision=1, title="Synthetic amount",
            question="What was paid?", content="Generated answer: parking cost forty-three fifty.")
        session.add(item)
        await session.flush()
        session.add_all([
            DocumentKnowledgeAnchor(id="synthetic-qa-anchor", item_id=item.id, ordinal=0,
                anchor_type="text", page_number=1, locator="page:1", exact_text=quote, rects=[]),
            DocumentKnowledgeItemTextUnit(item_id=item.id, text_unit_id=f"unit-{identity}", ordinal=0),
        ])
        await session.commit()
    calls = configure_external_calls(factory, monkeypatch, hit_count=0)
    class QAVectors:
        async def search(self, query):
            await another_client(factory)
            if query.query.scope.allowed_source_object_ids != (identity,):
                return []
            return [KnowledgeHit(document_id="item-vector-synthetic-qa", provider=SUPABASE_PROVIDER_ID,
                title="Generated synthetic answer", excerpt="Generated answer: parking cost forty-three fifty.",
                locator="page:999", score=.9, metadata={"document_knowledge_item_id": "synthetic-qa", "item_revision": 1,
                    "document_version_id": f"version-{identity}", "text_unit_ids": [f"unit-{identity}"],
                    "qa_snapshot": {"anchors": [{"locator": "page:999", "exact_text": "Untrusted generated quote"}]}})]
    quotes = []
    def rects(data, page, exact):
        quotes.append((data, page, exact))
        return [{"x": .1, "y": .2, "width": .3, "height": .04}]
    monkeypatch.setattr(search, "require_knowledge_vector_store", QAVectors)
    monkeypatch.setattr(search, "_pdf_quote_rects", rects)
    async with factory() as session:
        user = await session.get(UserAccount, ids[0])
        result = await execute_workspace_tool(session, workspace_id=ids[1], user=user, tool_name="search_knowledge",
            arguments={"query": "Synthetic amount"}, idempotency_key="qa-original-quote")
    assert calls["storage"] == [("synthetic", f"{identity}.pdf")]
    assert quotes == [(f"{identity}.pdf".encode(), 1, quote)]
    cited, = result["items"]
    assert cited["anchor"]["exact_text"] == quote and cited["excerpt"] == quote
    assert cited["anchor"]["page_number"] == 1 and cited["anchor"]["locator"] == "page:1"
    assert cited["snapshot"]["qa_snapshot"]["content"] == "Generated answer: parking cost forty-three fifty."


async def test_source_changed_during_pdf_load_is_rejected_after_external_work(pdf_search_db, monkeypatch):
    factory, ids = pdf_search_db
    calls = configure_external_calls(factory, monkeypatch, hit_count=1)
    original_storage = search.get_object
    changed = False
    async def storage(bucket, key):
        nonlocal changed
        value = await original_storage(bucket, key)
        if not changed:
            async with factory() as session:
                source = await session.get(StoredObject, "synthetic-receipt-0")
                source.extracted_text = "Changed synthetic source"
                await session.commit()
            changed = True
        return value
    monkeypatch.setattr(search, "get_object", storage)
    async with factory() as session:
        user = await session.get(UserAccount, ids[0])
        with pytest.raises(HTTPException) as caught:
            await execute_workspace_tool(session, workspace_id=ids[1], user=user, tool_name="search_knowledge",
                arguments={"query": "Synthetic amount"}, idempotency_key="source-changed-during-storage")
        assert (caught.value.status_code, caught.value.detail) == (409, "workspace_source_changed_during_search")
    assert calls["rects"] == []


def vector_record(identity, workspace_id, *, ordinal=0, score=.9):
    return VectorBucketRecord(document_id=f"doc-{identity}", chunk_id=f"candidate-{identity}-{ordinal}",
        text=PASSAGE, title="Synthetic receipt", score=score, locator="page:1", provider=SUPABASE_PROVIDER_ID,
        metadata={"scope_type": "customer", "customer_id": 1, "case_id": identity, "module": "dd",
            "workspace_id": workspace_id, "source_object_id": identity, "text_unit_id": f"unit-{identity}",
            "document_version_id": f"version-{identity}"})


@pytest.mark.parametrize("forge_selected_source", [False, True])
async def test_caller_source_filter_precedes_ranking_but_canonical_sql_still_authorizes(pdf_search_db, monkeypatch,
                                                                                      forge_selected_source):
    factory, ids = pdf_search_db
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, ids[1])
        user = await session.get(UserAccount, ids[0])
        await seed_source(session, workspace, user, "synthetic-unattached", attach=False)
        parent = workspace.workspace_id
        await session.commit()
    unrelated = [vector_record("synthetic-unattached", parent, ordinal=number, score=1.0) for number in range(80)]
    inventory = [*unrelated, *(vector_record(f"synthetic-receipt-{number}", parent) for number in range(2))]
    calls = configure_external_calls(factory, monkeypatch, hit_count=0)
    filters_seen = []
    class RankedClient:
        async def query(self, *, vector, filters, limit):
            await another_client(factory)
            filters_seen.append(filters)
            if forge_selected_source:
                forged = vector_record("synthetic-unattached", parent, score=1.0)
                forged.metadata["source_object_id"] = filters.get("source_object_id")
                return [forged]
            selected = [record for record in inventory if all(
                record.metadata.get(key) in value["$in"] if isinstance(value, dict) else record.metadata.get(key) == value
                for key, value in filters.items())]
            return sorted(selected, key=lambda record: record.score, reverse=True)[:limit]
    monkeypatch.setattr(search, "require_knowledge_vector_store", lambda: SupabaseVectorBucketStore(RankedClient()))
    async with factory() as session:
        user = await session.get(UserAccount, ids[0])
        result = await execute_workspace_tool(session, workspace_id=ids[1], user=user, tool_name="search_knowledge",
            arguments={"query": "Synthetic amount"}, idempotency_key="rank-selected-source")
    assert {filters["source_object_id"] for filters in filters_seen} == {"synthetic-receipt-0", "synthetic-receipt-1"}
    assert len(calls["storage"]) == 2
    assert {item["source_id"] for item in result["items"]} == (
        set() if forge_selected_source else {"synthetic-receipt-0", "synthetic-receipt-1"})
    if forge_selected_source:
        assert calls["rects"] == []


async def revoke_during_wait(factory, ids, change):
    await another_client(factory)
    async with factory.begin() as session:
        actor = await session.get(UserAccount, ids[0])
        if change == "deleted_actor":
            await session.execute(delete(UserAccount).where(UserAccount.id == ids[0]))
        elif change == "changed_owner":
            session.add(UserAccount(id="replacement-owner", email="replacement@example.test", role="user", kund_id=1))
            canvas = await session.get(VoiceWorkspace, ids[1])
            canvas.owner_user_id = "replacement-owner"
        elif change == "revoked_role":
            actor.role = "user"
        else:
            actor.kund_id = None


@pytest.mark.parametrize("scope", ["workspace", "general"])
@pytest.mark.parametrize("change", ["revoked_customer", "revoked_role", "deleted_actor", "changed_owner"])
async def test_search_reauthorizes_current_actor_and_canvas_after_external_wait(pdf_search_db, monkeypatch, scope, change):
    from tests.test_research_graph_v2_reuse import Embeddings, seed_fact
    factory, ids = pdf_search_db
    calls = configure_external_calls(factory, monkeypatch, hit_count=1)
    async with factory.begin() as session:
        if change == "revoked_role":
            actor = await session.get(UserAccount, ids[0])
            actor.role, actor.kund_id = "admin", None
        if scope == "general":
            canvas = await session.get(VoiceWorkspace, ids[1])
            canvas.state = {**canvas.state, "knowledge_scope": "general"}
            await seed_fact(session, scope="shared")
    class RevokingEmbeddings(Embeddings):
        async def embed(self, texts):
            await revoke_during_wait(factory, ids, change)
            return await super().embed(texts)
    monkeypatch.setattr(search.OpenAIEmbeddingProvider, "from_settings", RevokingEmbeddings)
    async with factory() as session:
        user = await session.get(UserAccount, ids[0])
        with pytest.raises(HTTPException) as caught:
            await execute_workspace_tool(session, workspace_id=ids[1], user=user, tool_name="search_knowledge",
                arguments={"query": "36 § avtalslagen senare lagändringar"}, idempotency_key="revoked-search")
        assert caught.value.status_code == 404
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceReference)) == 0
    assert calls["rects"] == []
