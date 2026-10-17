"""Leftover document-item vector cleanup. Ingest no longer writes these rows."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeDocumentRecord


async def remove_item(session: AsyncSession, item_id: str) -> None:
    # Circular: document_knowledge archives items by calling this cleanup.
    from app.services import document_knowledge as knowledge

    document_id = knowledge.item_vector_document_id(item_id)
    row = await session.get(KnowledgeDocumentRecord, document_id)
    if row is not None:
        await session.delete(row)
    await session.commit()
    await knowledge.require_knowledge_vector_store().delete_document(document_id)
