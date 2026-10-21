"""Purging one customer's documents must not touch anyone else's data."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from app.database.document_ingest_batches import DocumentIngestBatch, DocumentIngestBatchItem
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentKnowledgeItem,
    DocumentVersionRecord,
    Job,
    KnowledgeClaimTextUnit,
    KnowledgeDocumentRecord,
    KnowledgeGraphEventRecord,
    Kund,
    StoredObject,
)
from app.services import kund_dokument
from tests.text_unit_fakes import persisted_text_unit
from app.services.document_knowledge import DOCUMENT_INGEST_JOB_KIND
from app.services.knowledge.units import hash_text
from app.services.object_storage import ObjectStorageError, get_object_storage
from app.services.research.composition import set_knowledge_vector_store_factory
from tests.conftest import ADMIN_USER_ID, TEST_CUSTOMER_ID


class RecordingVectorStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_document(self, document_id: str) -> None:
        self.deleted.append(document_id)


class _Seed:
    def __init__(self, customer_id: int, prefix: str) -> None:
        self.customer_id = customer_id
        self.prefix = prefix
        self.scope_key = f"customer:{customer_id}"
        self.bucket = "bolag-demo" if customer_id != TEST_CUSTOMER_ID else "devbrains"
        self.object_id = f"{prefix}-obj"
        self.object_key = f"expertgranskning/underlag/{self.object_id}/avtal.txt"

    @property
    def scope(self) -> dict[str, object]:
        return {
            "scope_type": "customer",
            "scope_key": self.scope_key,
            "customer_id": self.customer_id,
        }


def _seed_graph_claim_and_link(seed: _Seed) -> None:
    """The graph is authoritative: claim, entity and the linking edge live in OverGraph."""
    from app.services.graph_v2.types import NodeInput
    from app.services.knowledge.scope import require_persist_scope
    from app.services.overgraph.catalogs import require_knowledge
    from app.services.overgraph.labels import CLAIM, LINKED, scope_label
    from app.services.overgraph.write import upsert_entity

    catalog = require_knowledge()
    scope = require_persist_scope(scope_type="customer", customer_id=seed.customer_id)
    claim_id = catalog.upsert_node(
        [CLAIM, scope_label(seed.scope_key)],
        f"{seed.prefix}-claim",
        props={"scope_key": seed.scope_key, "predicate": "har", "value_json": "{}"},
    )
    entity = upsert_entity(catalog, NodeInput(
        node_type="knowledge.entity.company",
        name="Acme",
        scope=scope,
        identifier_namespace="knowledge.entity",
        identifier=f"{seed.prefix}-acme",
    ))
    catalog.upsert_edge(
        claim_id, entity.engine_id, LINKED,
        props={
            "relation": "ABOUT",
            "extra": {},
            "from_kind": "claim",
            "to_kind": "entity",
        },
    )


def _stored_object(seed: _Seed) -> StoredObject:
    return StoredObject(
        id=seed.object_id,
        customer_id=seed.customer_id,
        module="expertgranskning",
        kind="underlag",
        bucket=seed.bucket,
        object_key=seed.object_key,
        filename="avtal.txt",
        content_type="text/plain",
        size_bytes=4,
        extraction_status="ok",
        knowledge_status="ready",
        extracted_text="Hemlig text.",
    )


async def _seed_customer_documents(factory, customer_id: int, prefix: str) -> _Seed:
    seed = _Seed(customer_id, prefix)
    text = f"Hemlig text for kund {customer_id}."
    digest = hash_text(text)
    async with factory() as session:
        session.add(_stored_object(seed))
        session.add(
            CanonicalDocumentRecord(
                id=seed.object_id,
                source_object_id=seed.object_id,
                source_type="uploaded_file",
                canonical_uri=f"stored-object:{seed.object_id}",
                title="Avtal",
                **seed.scope,
            )
        )
        session.add(
            DocumentVersionRecord(
                id=f"{seed.prefix}-ver",
                document_id=seed.object_id,
                content_hash=digest,
                mime_type="text/plain",
                version="1",
                **seed.scope,
            )
        )
        await persisted_text_unit(
            session,
            id=f"{seed.prefix}-unit",
            document_id=seed.object_id,
            document_version_id=f"{seed.prefix}-ver",
            ordinal=0,
            locator="page:1",
            text="Hemlig text.",
            **seed.scope,
        )
        session.add(
            DocumentKnowledgeItem(
                id=f"{seed.prefix}-item",
                source_object_id=seed.object_id,
                customer_id=customer_id,
                kind="fact",
                origin="manual",
                status="active",
                title="Fakta",
            )
        )
        session.add(
            KnowledgeClaimTextUnit(
                claim_id=f"{seed.prefix}-claim",
                text_unit_id=f"{seed.prefix}-unit",
                relation="SUPPORTED_BY",
            )
        )
        _seed_graph_claim_and_link(seed)
        session.add(
            KnowledgeGraphEventRecord(
                id=f"{seed.prefix}-event",
                event_type="CLAIM_ADDED",
                node_kind="claim",
                node_id=f"{seed.prefix}-claim",
                payload={},
                **seed.scope,
            )
        )
        session.add(
            KnowledgeDocumentRecord(
                document_id=f"{seed.prefix}-kdoc",
                provider="supabase",
                external_id=f"ext:{seed.prefix}",
                customer_id=customer_id,
                source_object_id=seed.object_id,
                title="Avtal",
                mime_type="text/plain",
                extra={},
            )
        )
        # The graph is authoritative: seed the tenant's nodes and fact in OverGraph.
        from app.services.graph_v2.types import FactInput, NodeInput
        from app.services.knowledge.scope import require_persist_scope
        from app.services.overgraph.catalogs import require_knowledge
        from app.services.overgraph.write import upsert_entity, write_fact

        catalog = require_knowledge()
        scope = require_persist_scope(customer_id=customer_id, scope_type="customer")
        node_a = upsert_entity(catalog, NodeInput(
            node_type="core.company", name="Acme", scope=scope,
            identifier_namespace="test.entity", identifier=f"{seed.prefix}-a",
        ))
        node_b = upsert_entity(catalog, NodeInput(
            node_type="core.company", name="Beta", scope=scope,
            identifier_namespace="test.entity", identifier=f"{seed.prefix}-b",
        ))
        write_fact(catalog, FactInput(
            source_id=node_a.key, target_id=node_b.key, scope=scope,
            predicate="core.agerar", fact_text="Acme agerar.",
            sources=(), occurrence_key=f"{seed.prefix}-fact",
        ))
        session.add(
            DocumentIngestBatch(
                id=f"{seed.prefix}-batch",
                customer_id=customer_id,
                voice_workspace_id="workspace-1",
                owner_user_id=ADMIN_USER_ID,
                status="completed",
            )
        )
        session.add(
            DocumentIngestBatchItem(
                id=f"{seed.prefix}-batch-item",
                batch_id=f"{seed.prefix}-batch",
                client_key=f"{seed.prefix}-client",
                filename="avtal.txt",
                stored_object_id=seed.object_id,
            )
        )
        await session.commit()
    storage = get_object_storage()
    storage.put_object(seed.bucket, seed.object_key, b"data", "text/plain")
    return seed


async def _count_for(factory, model, customer_id: int) -> int:
    async with factory() as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(model).where(model.customer_id == customer_id)
            )
            or 0
        )


async def _purge_snapshot(factory, customer_id: int) -> dict[str, int]:
    async with factory() as session:
        summary = await kund_dokument.load_kund_document_summary(session, customer_id)
        await session.rollback()
        return summary.counts.as_dict()


def _use_vector_store(store: RecordingVectorStore) -> None:
    set_knowledge_vector_store_factory(lambda: store)


@pytest.fixture(autouse=True)
def _reset_vector_store():
    yield
    set_knowledge_vector_store_factory(None)


_EMPTY_COUNTS = {
    "files": 0,
    "knowledge_documents": 0,
    "canonical_documents": 0,
    "text_units": 0,
    "document_knowledge_items": 0,
    "claims": 0,
    "entities": 0,
    "relationships": 0,
    "graph_events": 0,
    "graph_facts": 0,
    "graph_nodes": 0,
    "ingest_batches": 0,
}


def _graph_fact_present(prefix: str) -> bool:
    from app.services.overgraph.catalogs import require_knowledge
    from app.services.overgraph.labels import FACT

    catalog = require_knowledge()
    facts, _ = catalog.query_nodes(label_filter={"labels": [FACT], "mode": "all"}, limit=500)
    return any(
        str(node.props.get("occurrence_key") or "") == f"{prefix}-fact" for node in facts
    )


async def _assert_seed_intact(factory, seed: _Seed) -> None:
    counts = await _purge_snapshot(factory, seed.customer_id)
    assert counts["files"] == 1
    assert counts["canonical_documents"] == 1
    assert counts["text_units"] == 1
    assert counts["claims"] == 1
    assert counts["graph_facts"] == 1


async def _assert_seed_removed(factory, seed: _Seed) -> None:
    from app.services.overgraph.catalogs import require_knowledge
    from app.services.overgraph.labels import FACT

    catalog = require_knowledge()
    facts, _ = catalog.query_nodes(label_filter={"labels": [FACT], "mode": "all"}, limit=500)
    assert not any(
        str(node.props.get("occurrence_key") or "") == f"{seed.prefix}-fact" for node in facts
    )
    async with factory() as session:
        assert await session.get(DocumentIngestBatch, f"{seed.prefix}-batch") is None
        assert await session.get(DocumentIngestBatchItem, f"{seed.prefix}-batch-item") is None
        assert await session.get(KnowledgeDocumentRecord, f"{seed.prefix}-kdoc") is None
        assert await session.get(DocumentKnowledgeItem, f"{seed.prefix}-item") is None
        assert await session.get(KnowledgeGraphEventRecord, f"{seed.prefix}-event") is None


async def test_purge_removes_only_target_kund_documents(client, client_db):
    _client, factory = client_db
    target = await _seed_customer_documents(factory, TEST_CUSTOMER_ID, "target")
    other = await _seed_customer_documents(factory, 2, "other")
    store = RecordingVectorStore()
    _use_vector_store(store)

    summary = await client.get(f"/kunder/{TEST_CUSTOMER_ID}/dokument")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["kund_slug"] == "devbrains"
    assert body["blocked_reason"] is None
    assert body["counts"]["files"] == 1
    assert body["counts"]["canonical_documents"] == 1
    assert body["counts"]["graph_facts"] == 1
    assert body["counts"]["ingest_batches"] == 1

    deleted = await client.delete(
        f"/kunder/{TEST_CUSTOMER_ID}/dokument", params={"confirm": "devbrains"}
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"]["files"] == 1
    assert deleted.json()["stored_objects"] == 1
    assert deleted.json()["vector_documents"] == 3

    assert await _purge_snapshot(factory, TEST_CUSTOMER_ID) == _EMPTY_COUNTS
    await _assert_seed_intact(factory, other)
    await _assert_seed_removed(factory, target)
    async with factory() as session:
        assert await session.get(Kund, TEST_CUSTOMER_ID) is not None
        assert await session.get(CanonicalDocumentRecord, other.object_id) is not None
        assert _graph_fact_present(other.prefix)

    storage = get_object_storage()
    with pytest.raises(ObjectStorageError):
        storage.get_object(target.bucket, target.object_key)
    assert storage.get_object(other.bucket, other.object_key)[0] == b"data"

    assert target.object_id in store.deleted
    assert other.object_id not in store.deleted


async def test_purge_requires_exact_slug(client, client_db):
    _client, factory = client_db
    seed = await _seed_customer_documents(factory, TEST_CUSTOMER_ID, "slug")
    _use_vector_store(RecordingVectorStore())

    response = await client.delete(
        f"/kunder/{TEST_CUSTOMER_ID}/dokument", params={"confirm": "fel-slug"}
    )
    assert response.status_code == 400
    storage = get_object_storage()
    assert storage.get_object(seed.bucket, seed.object_key)[0] == b"data"


async def test_purge_is_blocked_while_document_ingest_runs(client, client_db):
    _client, factory = client_db
    seed = await _seed_customer_documents(factory, TEST_CUSTOMER_ID, "busy")
    _use_vector_store(RecordingVectorStore())
    async with factory() as session:
        session.add(
            Job(
                id="busy-ingest-job",
                customer_id=TEST_CUSTOMER_ID,
                kind=DOCUMENT_INGEST_JOB_KIND,
                status="running",
                label="Dokumentfordjupning",
                request={},
            )
        )
        await session.commit()

    summary = await client.get(f"/kunder/{TEST_CUSTOMER_ID}/dokument")
    assert summary.status_code == 200
    assert summary.json()["blocked_reason"] == "document_ingest_active"
    response = await client.delete(
        f"/kunder/{TEST_CUSTOMER_ID}/dokument", params={"confirm": "devbrains"}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "document_ingest_active"
    storage = get_object_storage()
    assert storage.get_object(seed.bucket, seed.object_key)[0] == b"data"


async def test_purge_releases_database_connection_during_external_calls(
    client, client_db, monkeypatch
):
    _client, factory = client_db
    await _seed_customer_documents(factory, TEST_CUSTOMER_ID, "slow")
    _use_vector_store(RecordingVectorStore())
    reached = asyncio.Event()
    release = asyncio.Event()

    async def blocking_delete(bucket: str, key: str) -> None:
        del bucket, key
        reached.set()
        await release.wait()

    monkeypatch.setattr(kund_dokument, "delete_object", blocking_delete)
    request = asyncio.create_task(
        client.delete(f"/kunder/{TEST_CUSTOMER_ID}/dokument", params={"confirm": "devbrains"})
    )
    try:
        await asyncio.wait_for(reached.wait(), timeout=5)
        async with factory() as other_session:
            assert await asyncio.wait_for(
                other_session.scalar(select(func.count()).select_from(Kund)), timeout=5
            ) == 2
    finally:
        release.set()
    response = await asyncio.wait_for(request, timeout=5)
    assert response.status_code == 200, response.text
