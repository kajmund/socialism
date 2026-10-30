"""Persist CanonicalDocument / DocumentVersion / Section / TextUnit graphs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    CanonicalDocumentRecord,
    DocumentSectionRecord,
    DocumentVersionRecord,
)
from app.serializers import utcnow
from app.services.knowledge.scope import (
    KnowledgeTenantScope,
    persist_scope_fields,
    require_persist_scope,
    scope_from_row,
    visible_to,
)
from app.services.knowledge.units import DocumentSection, SegmentedDocument
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.overgraph.owner_writer import (
    delete_document_graph_via_owner,
    evidence_keys_for_version_via_owner,
    text_unit_ids_for_document_via_owner,
    write_text_units_via_owner,
)


@dataclass(frozen=True)
class PersistedDocumentGraph:
    document: CanonicalDocumentRecord
    version: DocumentVersionRecord
    reused_current: bool


async def get_canonical_document_by_identity(
    session: AsyncSession,
    *,
    source_type: str,
    canonical_uri: str,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
) -> CanonicalDocumentRecord | None:
    resolved = require_persist_scope(scope=scope, customer_id=customer_id)
    stmt = select(CanonicalDocumentRecord).where(
        CanonicalDocumentRecord.scope_key == resolved.scope_key,
        CanonicalDocumentRecord.source_type == source_type,
        CanonicalDocumentRecord.canonical_uri == canonical_uri,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_readable_canonical_document_by_identity(
    session: AsyncSession,
    *,
    reader_customer_id: int,
    source_type: str,
    canonical_uri: str,
) -> CanonicalDocumentRecord | None:
    """Customer copy wins. Otherwise shared. Never another customer."""
    owned = await get_canonical_document_by_identity(
        session,
        customer_id=reader_customer_id,
        source_type=source_type,
        canonical_uri=canonical_uri,
    )
    if owned is not None:
        return owned
    shared = await get_canonical_document_by_identity(
        session,
        scope=require_persist_scope(scope_type="shared"),
        source_type=source_type,
        canonical_uri=canonical_uri,
    )
    if shared is None:
        return None
    if not visible_to(owned=scope_from_row(shared), reader_customer_id=reader_customer_id):
        raise RuntimeError("shared canonical document was not readable")
    return shared


async def get_current_document_version(
    session: AsyncSession,
    document_id: str,
) -> DocumentVersionRecord | None:
    stmt = select(DocumentVersionRecord).where(
        DocumentVersionRecord.document_id == document_id,
        DocumentVersionRecord.superseded_at.is_(None),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_document_versions(
    session: AsyncSession,
    document_id: str,
) -> list[DocumentVersionRecord]:
    stmt = (
        select(DocumentVersionRecord)
        .where(DocumentVersionRecord.document_id == document_id)
        .order_by(DocumentVersionRecord.ingested_at.asc(), DocumentVersionRecord.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def write_segmented_document_text_units(
    segmented: SegmentedDocument,
    scope: KnowledgeTenantScope,
) -> None:
    """Materialize TextUnits in the Owner after the SQL transaction commits."""
    client = get_owner_runtime().require_client()
    await write_text_units_via_owner(
        client,
        segmented.text_units,
        scope=scope,
        embeddings=[None for _ in segmented.text_units],
        section_titles={section.id: section.title or "" for section in segmented.sections},
        section_ordinals={section.id: section.ordinal for section in segmented.sections},
    )


async def persist_segmented_document(
    session: AsyncSession,
    *,
    segmented: SegmentedDocument,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
    source_object_id: str | None = None,
    materialize_graph: bool = True,
) -> PersistedDocumentGraph:
    now = utcnow()
    document = segmented.document
    version = segmented.version
    resolved = require_persist_scope(scope=scope, customer_id=customer_id)
    row = await session.get(CanonicalDocumentRecord, document.id)
    if row is not None and scope_from_row(row) != resolved:
        raise ValueError(
            f"Canonical document {document.id} already exists in a different knowledge scope"
        )
    if row is None:
        existing = await get_canonical_document_by_identity(
            session,
            scope=resolved,
            source_type=document.source_type,
            canonical_uri=document.canonical_uri,
        )
        if existing is not None and existing.id != document.id:
            raise ValueError(
                "Canonical source identity already exists as "
                f"{existing.id}; resolve that document_id before persist"
            )
        row = existing
    if row is None:
        row = CanonicalDocumentRecord(
            id=document.id,
            source_object_id=source_object_id,
            source_type=document.source_type,
            canonical_uri=document.canonical_uri,
            title=document.title,
            domain=document.domain,
            jurisdiction=document.jurisdiction,
            created_at=now,
            extra=dict(document.metadata),
            **persist_scope_fields(resolved),
        )
        session.add(row)
        await session.flush()
    current = await get_current_document_version(session, row.id)
    if current is not None and current.content_hash == version.content_hash:
        return PersistedDocumentGraph(
            document=row,
            version=current,
            reused_current=True,
        )
    if current is not None:
        current.superseded_at = now
        await session.flush()
    row.title = document.title
    row.domain = document.domain
    row.jurisdiction = document.jurisdiction
    row.source_object_id = source_object_id
    row.extra = dict(document.metadata)
    version_row = DocumentVersionRecord(
        id=version.id,
        document_id=row.id,
        version=version.version,
        content_hash=version.content_hash,
        mime_type=version.mime_type,
        valid_from=version.valid_from,
        valid_to=version.valid_to,
        ingested_at=now,
        superseded_at=None,
        extra=dict(version.metadata),
        **persist_scope_fields(resolved),
    )
    session.add(version_row)
    await session.flush()
    await _insert_sections(session, version_row, segmented.sections, resolved)
    if materialize_graph:
        await write_segmented_document_text_units(segmented, resolved)
    return PersistedDocumentGraph(document=row, version=version_row, reused_current=False)


async def _insert_sections(
    session: AsyncSession,
    version: DocumentVersionRecord,
    sections: Sequence[DocumentSection],
    scope: KnowledgeTenantScope,
) -> None:
    fields = persist_scope_fields(scope)
    for section in sections:
        session.add(
            DocumentSectionRecord(
                id=section.id,
                document_version_id=version.id,
                document_id=version.document_id,
                parent_section_id=section.parent_section_id,
                ordinal=section.ordinal,
                type=section.type,
                title=section.title,
                page_start=section.page_start,
                page_end=section.page_end,
                extra=dict(section.metadata),
                **fields,
            )
        )
    await session.flush()


async def delete_canonical_document(session: AsyncSession, document_id: str) -> None:
    row = await session.get(CanonicalDocumentRecord, document_id)
    if row is None:
        return
    client = get_owner_runtime().require_client()
    unit_ids = await text_unit_ids_for_document_via_owner(
        client, document_id=document_id,
    )
    version_ids = list(
        (
            await session.execute(
                select(DocumentVersionRecord.id).where(
                    DocumentVersionRecord.document_id == document_id
                )
            )
        ).scalars().all()
    )
    evidence_keys = [
        key
        for version_id in version_ids
        for key in await evidence_keys_for_version_via_owner(
            client, document_version_id=version_id,
        )
    ]
    await delete_document_graph_via_owner(
        client,
        unit_ids=unit_ids,
        evidence_keys=evidence_keys,
        mutation_id=f"delete-document-graph:{document_id}",
    )
    await session.delete(row)
    await session.flush()
