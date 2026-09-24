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
    TextUnitRecord,
)
from app.serializers import utcnow
from app.services.knowledge.scope import (
    KnowledgeTenantScope,
    persist_scope_fields,
    require_persist_scope,
    scope_from_row,
    visible_to,
)
from app.services.knowledge.units import DocumentSection, SegmentedDocument, TextUnit


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


async def persist_segmented_document(
    session: AsyncSession,
    *,
    segmented: SegmentedDocument,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
    source_object_id: str | None = None,
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
    await _insert_text_units(session, version_row, segmented.text_units, now, resolved)
    return PersistedDocumentGraph(document=row, version=version_row, reused_current=False)


async def current_text_units(
    session: AsyncSession,
    document_id: str,
) -> list[TextUnitRecord]:
    version = await get_current_document_version(session, document_id)
    if version is None:
        return []
    return await text_units_for_version(session, version.id)


async def text_units_for_version(
    session: AsyncSession,
    document_version_id: str,
) -> list[TextUnitRecord]:
    stmt = (
        select(TextUnitRecord)
        .outerjoin(
            DocumentSectionRecord,
            TextUnitRecord.section_id == DocumentSectionRecord.id,
        )
        .where(TextUnitRecord.document_version_id == document_version_id)
        .order_by(
            DocumentSectionRecord.ordinal.asc().nullsfirst(),
            TextUnitRecord.ordinal.asc(),
            TextUnitRecord.id.asc(),
        )
    )
    return list((await session.execute(stmt)).scalars().all())


def text_unit_from_record(row: TextUnitRecord) -> TextUnit:
    return TextUnit(
        id=row.id,
        document_version_id=row.document_version_id,
        document_id=row.document_id,
        section_id=row.section_id,
        ordinal=row.ordinal,
        text=row.text,
        content_hash=row.content_hash,
        locator=row.locator,
        page_start=row.page_start,
        page_end=row.page_end,
        char_start=row.char_start,
        char_end=row.char_end,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        ingested_at=row.ingested_at,
        embedding_id=row.embedding_id,
        metadata=dict(row.extra or {}),
    )


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


async def _insert_text_units(
    session: AsyncSession,
    version: DocumentVersionRecord,
    units: Sequence[TextUnit],
    now,
    scope: KnowledgeTenantScope,
) -> None:
    fields = persist_scope_fields(scope)
    for unit in units:
        session.add(
            TextUnitRecord(
                id=unit.id,
                document_version_id=version.id,
                document_id=version.document_id,
                section_id=unit.section_id,
                ordinal=unit.ordinal,
                text=unit.text,
                content_hash=unit.content_hash,
                locator=unit.locator,
                page_start=unit.page_start,
                page_end=unit.page_end,
                char_start=unit.char_start,
                char_end=unit.char_end,
                valid_from=unit.valid_from,
                valid_to=unit.valid_to,
                ingested_at=now,
                embedding_id=unit.embedding_id or unit.id,
                extra=dict(unit.metadata),
                **fields,
            )
        )
    await session.flush()
