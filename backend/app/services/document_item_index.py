"""Q&A discovery projections. Persist source references before external indexing."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DocumentKnowledgeItem, KnowledgeDocumentRecord, StoredObject, TextUnitRecord
from app.services.knowledge.models import EmbeddedKnowledgeChunk, KnowledgeChunk


async def index_items(session: AsyncSession, *, source: StoredObject, items: Sequence[DocumentKnowledgeItem]) -> None:
    from app.services import document_knowledge as knowledge

    searchable = [item for item in items if item.status == "active" and item.kind in {"fact", "qa"}]
    projections = []
    texts = []
    for item in searchable:
        metadata = await _metadata(session, source, item)
        await _upsert_record(session, source, item, metadata)
        projections.append(_chunk(source, item, metadata))
        texts.append(knowledge._embedding_text(item))
    await session.commit()
    if not projections:
        return
    vectors = await knowledge.OpenAIEmbeddingProvider.from_settings().embed(texts)
    if len(vectors) != len(projections):
        raise RuntimeError("EmbeddingProvider returned an unexpected document item count")
    store = knowledge.require_knowledge_vector_store()
    for chunk, vector in zip(projections, vectors, strict=True):
        await store.replace_document_chunks(chunk.document_id, [
            EmbeddedKnowledgeChunk(chunk=chunk, embedding=vector),
        ])


async def sync_item(session: AsyncSession, *, source: StoredObject, item: DocumentKnowledgeItem) -> None:
    if item.status == "active" and item.kind in {"fact", "qa"}:
        await index_items(session, source=source, items=[item])
    else:
        await remove_item(session, item.id)


async def remove_item(session: AsyncSession, item_id: str) -> None:
    from app.services import document_knowledge as knowledge

    document_id = knowledge.item_vector_document_id(item_id)
    row = await session.get(KnowledgeDocumentRecord, document_id)
    if row is not None:
        await session.delete(row)
    await session.commit()
    await knowledge.require_knowledge_vector_store().delete_document(document_id)


async def _metadata(session: AsyncSession, source: StoredObject, item: DocumentKnowledgeItem) -> dict[str, object]:
    ids = [link.text_unit_id for link in item.text_unit_links]
    units = list(await session.scalars(select(TextUnitRecord).where(TextUnitRecord.id.in_(ids)))) if ids else []
    versions = {unit.document_version_id for unit in units}
    anchor = item.anchors[0] if item.anchors else None
    return {
        "knowledge_kind": "document_item", "document_knowledge_item_id": item.id,
        "source_document_id": source.id, "source_object_id": source.id,
        "workspace_id": source.workspace_id, "item_kind": item.kind,
        "origin": item.origin, "item_revision": item.revision,
        "document_version_id": next(iter(versions)) if len(versions) == 1 else None,
        "text_unit_ids": ids, "page_number": anchor.page_number if anchor else None,
        "anchor_type": anchor.anchor_type if anchor else None,
    }


async def _upsert_record(session: AsyncSession, source: StoredObject, item: DocumentKnowledgeItem, metadata: dict[str, object]) -> None:
    from app.services import document_knowledge as knowledge

    document_id = knowledge.item_vector_document_id(item.id)
    row = await session.get(KnowledgeDocumentRecord, document_id)
    if row is None:
        row = KnowledgeDocumentRecord(
            document_id=document_id, provider=knowledge.SUPABASE_PROVIDER_ID,
            external_id=f"document-knowledge-item:{item.id}", customer_id=source.customer_id,
            source_object_id=source.id, case_id=source.id, module=source.module,
            title=item.title, mime_type="application/vnd.socialism.document-knowledge+json",
            storage_bucket=source.bucket, storage_key=source.object_key,
            version=str(item.revision), extra=metadata,
        )
        session.add(row)
    else:
        row.title, row.version, row.extra = item.title, str(item.revision), metadata
    await session.flush()


def _chunk(source: StoredObject, item: DocumentKnowledgeItem, metadata: dict[str, object]) -> KnowledgeChunk:
    from app.services import document_knowledge as knowledge

    anchor = item.anchors[0] if item.anchors else None
    return KnowledgeChunk(
        document_id=knowledge.item_vector_document_id(item.id), chunk_id=f"revision:{item.revision}",
        text=knowledge._display_text(item), customer_id=source.customer_id,
        case_id=source.id, module=source.module, title=item.title,
        locator=anchor.locator if anchor else None, provider=knowledge.SUPABASE_PROVIDER_ID,
        version=str(item.revision), metadata=metadata,
    )
