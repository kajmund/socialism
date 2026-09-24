"""Persist CanonicalDocument / Section / TextUnit graphs. Domain-neutral."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    CanonicalDocumentRecord,
    DocumentSectionRecord,
    TextUnitRecord,
)
from app.serializers import utcnow
from app.services.knowledge.units import CanonicalDocument, DocumentSection, SegmentedDocument, TextUnit


async def persist_segmented_document(
    session: AsyncSession,
    *,
    customer_id: int,
    segmented: SegmentedDocument,
    source_object_id: str | None = None,
) -> CanonicalDocumentRecord:
    now = utcnow()
    document = segmented.document
    row = await session.get(CanonicalDocumentRecord, document.id)
    if row is None:
        row = CanonicalDocumentRecord(
            id=document.id,
            customer_id=customer_id,
            source_object_id=source_object_id,
            source_type=document.source_type,
            canonical_uri=document.canonical_uri,
            title=document.title,
            version=document.version,
            content_hash=document.content_hash,
            mime_type=document.mime_type,
            domain=document.domain,
            jurisdiction=document.jurisdiction,
            valid_from=document.valid_from,
            valid_to=document.valid_to,
            ingested_at=now,
            superseded_at=None,
            extra=dict(document.metadata),
        )
        session.add(row)
    else:
        row.source_object_id = source_object_id
        row.source_type = document.source_type
        row.canonical_uri = document.canonical_uri
        row.title = document.title
        row.version = document.version
        row.content_hash = document.content_hash
        row.mime_type = document.mime_type
        row.domain = document.domain
        row.jurisdiction = document.jurisdiction
        row.valid_from = document.valid_from
        row.valid_to = document.valid_to
        row.ingested_at = now
        row.superseded_at = None
        row.extra = dict(document.metadata)
    await session.flush()
    await _replace_sections(session, document.id, segmented.sections, now)
    await _replace_text_units(session, document.id, segmented.text_units, now)
    return row


async def current_text_units(
    session: AsyncSession,
    document_id: str,
) -> list[TextUnitRecord]:
    stmt = (
        select(TextUnitRecord)
        .where(
            TextUnitRecord.document_id == document_id,
            TextUnitRecord.superseded_at.is_(None),
        )
        .order_by(TextUnitRecord.ordinal.asc(), TextUnitRecord.id.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def _replace_sections(
    session: AsyncSession,
    document_id: str,
    sections: Sequence[DocumentSection],
    now,
) -> None:
    existing = {
        row.id: row
        for row in (
            await session.execute(
                select(DocumentSectionRecord).where(DocumentSectionRecord.document_id == document_id)
            )
        )
        .scalars()
        .all()
    }
    keep = {section.id for section in sections}
    for section_id, row in existing.items():
        if section_id not in keep and row.superseded_at is None:
            row.superseded_at = now
    for section in sections:
        row = existing.get(section.id)
        if row is None:
            session.add(
                DocumentSectionRecord(
                    id=section.id,
                    document_id=document_id,
                    parent_section_id=section.parent_section_id,
                    ordinal=section.ordinal,
                    type=section.type,
                    title=section.title,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    extra=dict(section.metadata),
                    superseded_at=None,
                )
            )
            continue
        row.parent_section_id = section.parent_section_id
        row.ordinal = section.ordinal
        row.type = section.type
        row.title = section.title
        row.page_start = section.page_start
        row.page_end = section.page_end
        row.extra = dict(section.metadata)
        row.superseded_at = None
    await session.flush()


async def _replace_text_units(
    session: AsyncSession,
    document_id: str,
    units: Sequence[TextUnit],
    now,
) -> None:
    existing = {
        row.id: row
        for row in (
            await session.execute(select(TextUnitRecord).where(TextUnitRecord.document_id == document_id))
        )
        .scalars()
        .all()
    }
    keep = {unit.id for unit in units}
    for unit_id, row in existing.items():
        if unit_id not in keep and row.superseded_at is None:
            row.superseded_at = now
    for unit in units:
        row = existing.get(unit.id)
        if row is None:
            session.add(
                TextUnitRecord(
                    id=unit.id,
                    document_id=document_id,
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
                    superseded_at=None,
                    embedding_id=unit.embedding_id or unit.id,
                    extra=dict(unit.metadata),
                )
            )
            continue
        row.section_id = unit.section_id
        row.ordinal = unit.ordinal
        row.text = unit.text
        row.content_hash = unit.content_hash
        row.locator = unit.locator
        row.page_start = unit.page_start
        row.page_end = unit.page_end
        row.char_start = unit.char_start
        row.char_end = unit.char_end
        row.valid_from = unit.valid_from
        row.valid_to = unit.valid_to
        row.ingested_at = now
        row.superseded_at = None
        row.embedding_id = unit.embedding_id or unit.id
        row.extra = dict(unit.metadata)
    await session.flush()
