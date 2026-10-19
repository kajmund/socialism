"""Map CanonicalDocument.id ↔ StoredObject/source_object_id. Short DB transactions only."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CanonicalDocumentRecord, StoredObject


async def document_ids_for_sources(
    session: AsyncSession, source_ids: Sequence[str],
) -> list[str]:
    if not source_ids:
        return []
    rows = (await session.scalars(
        select(CanonicalDocumentRecord).where(
            CanonicalDocumentRecord.source_object_id.in_(list(source_ids)),
        )
    )).all()
    by_source = {
        str(row.source_object_id): row.id
        for row in rows
        if row.source_object_id
    }
    return [by_source[source_id] for source_id in source_ids if source_id in by_source]


async def source_ids_for_documents(
    session: AsyncSession, document_ids: Sequence[str],
) -> list[str]:
    if not document_ids:
        return []
    rows = (await session.scalars(
        select(CanonicalDocumentRecord).where(
            CanonicalDocumentRecord.id.in_(list(document_ids)),
        )
    )).all()
    by_id = {
        row.id: str(row.source_object_id)
        for row in rows
        if row.source_object_id
    }
    return [by_id[document_id] for document_id in document_ids if document_id in by_id]


async def readable_document_ids(
    session: AsyncSession,
    *,
    customer_id: int,
    workspace_ids: Sequence[str],
) -> set[str]:
    """Documents provably readable: source objects in a readable org workspace.

    Documents without a source object (NULL source_object_id) are excluded:
    their workspace cannot be proven.
    """
    if not workspace_ids:
        return set()
    rows = await session.scalars(
        select(CanonicalDocumentRecord.id)
        .join(StoredObject, StoredObject.id == CanonicalDocumentRecord.source_object_id)
        .where(
            StoredObject.customer_id == customer_id,
            StoredObject.workspace_id.in_(list(workspace_ids)),
        )
    )
    return set(rows.all())


async def readable_source_ids_for_documents(
    session: AsyncSession,
    document_ids: Sequence[str],
    *,
    customer_id: int,
    workspace_ids: Sequence[str],
) -> list[str]:
    """Source ids for documents that still sit in a readable org workspace."""
    if not document_ids or not workspace_ids:
        return []
    rows = (await session.scalars(
        select(CanonicalDocumentRecord)
        .join(StoredObject, StoredObject.id == CanonicalDocumentRecord.source_object_id)
        .where(
            CanonicalDocumentRecord.id.in_(list(document_ids)),
            StoredObject.customer_id == customer_id,
            StoredObject.workspace_id.in_(list(workspace_ids)),
        )
    )).all()
    by_id = {
        row.id: str(row.source_object_id)
        for row in rows
        if row.source_object_id
    }
    return [by_id[document_id] for document_id in document_ids if document_id in by_id]
