"""Delete one customer's uploaded documents and the knowledge derived from them.

The purge is deliberately narrow: only ``stored_objects`` of kind ``underlag`` and
the customer-scoped knowledge built from documents are removed. Personas, runs,
reports, users and shared knowledge are left untouched.

External work (object storage and vector index) happens with no database
connection checked out; see AGENTS.md "release database connections".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.document_ingest_batches import DocumentIngestBatch, DocumentIngestBatchItem
from app.database.graph_v2 import (
    GraphIngestWork,
)
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentKnowledgeAnchor,
    DocumentKnowledgeItem,
    DocumentKnowledgeItemTextUnit,
    DocumentKnowledgeRevision,
    DocumentSectionRecord,
    DocumentVersionRecord,
    Job,
    KnowledgeDocumentRecord,
    KnowledgeGraphEventRecord,
    Kund,
    RattsunderlagSession,
    StoredObject,
)
from app.database.workspace_models import WorkspaceSource
from app.database.workspaces import WorkspaceChatMessage
from app.services.document_knowledge import DOCUMENT_ITEM_VECTOR_PREFIX, DOCUMENT_INGEST_JOB_KIND
from app.services.knowledge.vector_store import KnowledgeVectorStoreError
from app.services.object_storage import KIND_UNDERLAG, ObjectStorageError, delete_object
from app.services.overgraph.owner_graph import apply_batch
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.overgraph.labels import (
    CLAIM,
    DOCUMENT_VERSION,
    ENTITY,
    FACT,
    KNOWLEDGE_QUESTION,
    TEXT_UNIT,
    VERIFICATION_OBSERVATION,
)
from app.services.research.composition import ResearchCompositionError, require_knowledge_vector_store

ACTIVE_JOB_STATUSES = ("pending", "running")
ACTIVE_GRAPH_STATUSES = ("pending", "processing")


class KundDocumentSlugMismatch(Exception):
    """The caller did not repeat the customer's slug exactly."""


class KundDocumentsBlocked(Exception):
    """Document or graph ingest is still running for the customer."""


class KundDocumentsStorageError(Exception):
    """Object storage or vector index could not be cleaned up."""


@dataclass(frozen=True)
class KundDocumentCounts:
    files: int
    knowledge_documents: int
    canonical_documents: int
    text_units: int
    document_knowledge_items: int
    claims: int
    entities: int
    relationships: int
    graph_events: int
    graph_facts: int
    graph_nodes: int
    ingest_batches: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class KundDocumentSummary:
    kund_id: int
    kund_name: str
    kund_slug: str
    counts: KundDocumentCounts
    blocked_reason: str | None


@dataclass(frozen=True)
class _PurgeSnapshot:
    stored_objects: list[tuple[str, str]]
    vector_document_ids: list[str]


@dataclass(frozen=True)
class KundDocumentPurgeResult:
    kund_id: int
    deleted: KundDocumentCounts
    vector_documents: int
    stored_objects: int


def _count_stmt(model: object, *conditions: object):
    return select(func.count()).select_from(model).where(*conditions)  # type: ignore[arg-type]


async def _count(session: AsyncSession, model: object, *conditions: object) -> int:
    result = await session.scalar(_count_stmt(model, *conditions))
    return int(result or 0)


async def _blocked_reason(session: AsyncSession, customer_id: int) -> str | None:
    active_ingest = await session.scalar(
        select(Job.id)
        .where(
            Job.customer_id == customer_id,
            Job.kind == DOCUMENT_INGEST_JOB_KIND,
            Job.status.in_(ACTIVE_JOB_STATUSES),
        )
        .limit(1)
    )
    if active_ingest is not None:
        return "document_ingest_active"
    active_graph = await session.scalar(
        select(GraphIngestWork.id)
        .where(
            GraphIngestWork.customer_id == customer_id,
            GraphIngestWork.status.in_(ACTIVE_GRAPH_STATUSES),
        )
        .limit(1)
    )
    if active_graph is not None:
        return "graph_ingest_active"
    return None


async def _load_kund(session: AsyncSession, customer_id: int) -> Kund:
    kund = await session.get(Kund, customer_id)
    if kund is None:
        raise LookupError(f"Kund not found: {customer_id}")
    return kund


async def load_kund_document_summary(
    session: AsyncSession, customer_id: int
) -> KundDocumentSummary:
    kund = await _load_kund(session, customer_id)
    counts = KundDocumentCounts(
        files=await _count(session, StoredObject, StoredObject.customer_id == customer_id,
                          StoredObject.kind == KIND_UNDERLAG),
        knowledge_documents=await _count(
            session, KnowledgeDocumentRecord,
            KnowledgeDocumentRecord.customer_id == customer_id),
        canonical_documents=await _count(
            session, CanonicalDocumentRecord,
            CanonicalDocumentRecord.customer_id == customer_id),
        text_units=await _count_text_units(customer_id),
        document_knowledge_items=await _count(
            session, DocumentKnowledgeItem, DocumentKnowledgeItem.customer_id == customer_id),
        claims=await _graph_node_count(CLAIM, customer_id),
        entities=await _graph_node_count(ENTITY, customer_id),
        relationships=await _graph_edge_count(customer_id),
        graph_events=await _count(
            session, KnowledgeGraphEventRecord,
            KnowledgeGraphEventRecord.customer_id == customer_id),
        graph_facts=await _graph_node_count(FACT, customer_id),
        graph_nodes=await _graph_node_count(ENTITY, customer_id),
        ingest_batches=await _count(
            session, DocumentIngestBatch, DocumentIngestBatch.customer_id == customer_id),
    )
    return KundDocumentSummary(
        kund_id=kund.id,
        kund_name=kund.name,
        kund_slug=kund.slug,
        counts=counts,
        blocked_reason=await _blocked_reason(session, customer_id),
    )


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


async def _load_snapshot(session: AsyncSession, customer_id: int) -> _PurgeSnapshot:
    stored_objects = [
        (bucket, object_key)
        for bucket, object_key in (
            await session.execute(
                select(StoredObject.bucket, StoredObject.object_key).where(
                    StoredObject.customer_id == customer_id,
                    StoredObject.kind == KIND_UNDERLAG,
                )
            )
        ).all()
    ]
    canonical_ids = list(
        (
            await session.scalars(
                select(CanonicalDocumentRecord.id).where(
                    CanonicalDocumentRecord.customer_id == customer_id
                )
            )
        ).all()
    )
    knowledge_document_ids = list(
        (
            await session.scalars(
                select(KnowledgeDocumentRecord.document_id).where(
                    KnowledgeDocumentRecord.customer_id == customer_id
                )
            )
        ).all()
    )
    item_ids = list(
        (
            await session.scalars(
                select(DocumentKnowledgeItem.id).where(
                    DocumentKnowledgeItem.customer_id == customer_id
                )
            )
        ).all()
    )
    object_ids = list(
        (
            await session.scalars(
                select(StoredObject.id).where(
                    StoredObject.customer_id == customer_id,
                    StoredObject.kind == KIND_UNDERLAG,
                )
            )
        ).all()
    )
    vector_ids = _dedupe(
        canonical_ids
        + knowledge_document_ids
        + object_ids
        + [f"{DOCUMENT_ITEM_VECTOR_PREFIX}{item_id}" for item_id in item_ids]
    )
    return _PurgeSnapshot(stored_objects=stored_objects, vector_document_ids=vector_ids)


async def _delete_external_objects(snapshot: _PurgeSnapshot) -> None:
    try:
        for bucket, object_key in snapshot.stored_objects:
            await delete_object(bucket, object_key)
        if snapshot.vector_document_ids:
            vector_store = require_knowledge_vector_store()
            for document_id in snapshot.vector_document_ids:
                await vector_store.delete_document(document_id)
    except (ObjectStorageError, KnowledgeVectorStoreError, ResearchCompositionError) as exc:
        raise KundDocumentsStorageError(str(exc)) from exc


def _scope_key(customer_id: int) -> str:
    return f"customer:{customer_id}"


async def _graph_edge_count(customer_id: int) -> int:
    """Relationship neighbours owned by this tenant."""
    owner = get_owner_runtime().require_client()
    seen: set[int] = set()
    for label in (ENTITY, CLAIM, TEXT_UNIT, FACT, DOCUMENT_VERSION):
        for row in await _owner_scope_nodes(owner, label, customer_id):
            for neighbour in await owner.neighbors(
                int(row["id"]), direction="outgoing", limit=200,
            ):
                seen.add(int(neighbour["node_id"]))
    return len(seen)


async def _graph_node_count(label: str, customer_id: int) -> int:
    return len(await _owner_scope_nodes(
        get_owner_runtime().require_client(), label, customer_id,
    ))


async def _owner_scope_nodes(owner, label: str, customer_id: int) -> list[dict]:
    rows: list[dict] = []
    cursor: int | None = None
    while True:
        page = await owner.query_nodes(
            label, props={"scope_key": _scope_key(customer_id)},
            limit=1000, after=cursor,
        )
        rows.extend(page["nodes"])
        cursor = page.get("next_cursor")
        if cursor is None:
            break
    return rows


async def _delete_graph_v2(session: AsyncSession, customer_id: int) -> None:
    """Purge this tenant's graph nodes; incident edges and identifiers cascade."""
    for label in (FACT, ENTITY, KNOWLEDGE_QUESTION):
        await _delete_scope_nodes(label, customer_id)


async def _delete_claims(session: AsyncSession, customer_id: int) -> None:
    await _delete_scope_nodes(CLAIM, customer_id)


async def _delete_other_knowledge(session: AsyncSession, customer_id: int) -> None:
    for label in (ENTITY, CLAIM):
        await _delete_scope_nodes(label, customer_id)
    await session.execute(
        delete(KnowledgeGraphEventRecord).where(
            KnowledgeGraphEventRecord.customer_id == customer_id
        )
    )


async def _delete_document_graph(session: AsyncSession, customer_id: int) -> None:
    canonical_ids = select(CanonicalDocumentRecord.id).where(
        CanonicalDocumentRecord.customer_id == customer_id
    )
    item_ids = select(DocumentKnowledgeItem.id).where(
        DocumentKnowledgeItem.customer_id == customer_id
    )
    await session.execute(
        delete(DocumentKnowledgeAnchor).where(DocumentKnowledgeAnchor.item_id.in_(item_ids))
    )
    await session.execute(
        delete(DocumentKnowledgeRevision).where(DocumentKnowledgeRevision.item_id.in_(item_ids))
    )
    await session.execute(
        delete(DocumentKnowledgeItemTextUnit).where(
            DocumentKnowledgeItemTextUnit.item_id.in_(item_ids)
        )
    )
    await _delete_scope_nodes(TEXT_UNIT, customer_id)
    await _delete_scope_nodes(VERIFICATION_OBSERVATION, customer_id)
    await _delete_scope_nodes(CLAIM, customer_id)
    await session.execute(
        delete(DocumentSectionRecord).where(DocumentSectionRecord.document_id.in_(canonical_ids))
    )
    await session.execute(
        delete(DocumentVersionRecord).where(DocumentVersionRecord.document_id.in_(canonical_ids))
    )
    await session.execute(
        delete(CanonicalDocumentRecord).where(
            CanonicalDocumentRecord.customer_id == customer_id
        )
    )
    await session.execute(
        delete(KnowledgeDocumentRecord).where(
            KnowledgeDocumentRecord.customer_id == customer_id
        )
    )


async def _delete_ingest_batches(session: AsyncSession, customer_id: int) -> None:
    batch_ids = select(DocumentIngestBatch.id).where(
        DocumentIngestBatch.customer_id == customer_id
    )
    await session.execute(
        delete(DocumentIngestBatchItem).where(DocumentIngestBatchItem.batch_id.in_(batch_ids))
    )
    await session.execute(
        delete(DocumentIngestBatch).where(DocumentIngestBatch.customer_id == customer_id)
    )


async def _delete_stored_documents(session: AsyncSession, customer_id: int) -> None:
    object_ids = select(StoredObject.id).where(
        StoredObject.customer_id == customer_id,
        StoredObject.kind == KIND_UNDERLAG,
    )
    await session.execute(
        delete(DocumentKnowledgeItem).where(
            DocumentKnowledgeItem.customer_id == customer_id
        )
    )
    await session.execute(delete(WorkspaceSource).where(WorkspaceSource.source_id.in_(object_ids)))
    await session.execute(
        update(WorkspaceChatMessage)
        .where(WorkspaceChatMessage.attachment_object_id.in_(object_ids))
        .values(attachment_object_id=None)
    )
    await session.execute(
        update(RattsunderlagSession)
        .where(RattsunderlagSession.underlag_id.in_(object_ids))
        .values(underlag_id=None)
    )
    await session.execute(
        delete(StoredObject).where(
            StoredObject.customer_id == customer_id,
            StoredObject.kind == KIND_UNDERLAG,
        )
    )



async def _count_text_units(customer_id: int) -> int:
    return await _graph_node_count(TEXT_UNIT, customer_id)


async def _delete_scope_nodes(label: str, customer_id: int) -> None:
    owner = get_owner_runtime().require_client()
    rows = await _owner_scope_nodes(owner, label, customer_id)
    keys = [str(row["key"]) for row in rows]
    for start in range(0, len(keys), 500):
        await apply_batch(
            owner, f"purge:{label}",
            nodes=[], edges=[],
            deletes=[{"label": label, "key": key} for key in keys[start:start + 500]],
        )




async def _delete_customer_rows(session: AsyncSession, customer_id: int) -> None:
    await _delete_graph_v2(session, customer_id)
    await _delete_claims(session, customer_id)
    await _delete_other_knowledge(session, customer_id)
    await _delete_document_graph(session, customer_id)
    # Owner deletes append search-ledger nodes labelled ENTITY; remove those
    # tenant-scoped change records after the graph purge itself is done.
    await _delete_scope_nodes(ENTITY, customer_id)
    await _delete_ingest_batches(session, customer_id)
    await _delete_stored_documents(session, customer_id)
    await session.commit()


async def purge_kund_documents(
    session: AsyncSession, *, customer_id: int, confirm_slug: str
) -> KundDocumentPurgeResult:
    """Permanently remove one customer's documents and derived knowledge."""
    kund = await _load_kund(session, customer_id)
    if confirm_slug.strip() != kund.slug:
        raise KundDocumentSlugMismatch("confirm must repeat the kund slug")
    summary = await load_kund_document_summary(session, customer_id)
    snapshot = await _load_snapshot(session, customer_id)
    await session.rollback()
    if summary.blocked_reason is not None:
        raise KundDocumentsBlocked(summary.blocked_reason)
    await _delete_external_objects(snapshot)
    try:
        await _delete_customer_rows(session, customer_id)
    except Exception:
        await session.rollback()
        raise
    return KundDocumentPurgeResult(
        kund_id=customer_id,
        deleted=summary.counts,
        vector_documents=len(snapshot.vector_document_ids),
        stored_objects=len(snapshot.stored_objects),
    )
