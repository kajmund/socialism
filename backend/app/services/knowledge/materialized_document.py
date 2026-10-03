"""Materialize an immutable canonical graph before releasing its SQL transaction."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DocumentSectionRecord, DocumentVersionRecord
from app.services.knowledge.persistence import text_unit_from_record, text_units_for_version
from app.services.knowledge.units import DocumentSection, SegmentedDocument


async def persisted_segment(
    session: AsyncSession,
    segmented: SegmentedDocument,
    version: DocumentVersionRecord,
) -> SegmentedDocument:
    sections = list(await session.scalars(select(DocumentSectionRecord).where(
        DocumentSectionRecord.document_version_id == version.id,
    ).order_by(DocumentSectionRecord.ordinal)))
    units = await text_units_for_version(session, version.id)
    return replace(
        segmented,
        version=replace(
            segmented.version, id=version.id, ingested_at=version.ingested_at,
            superseded_at=version.superseded_at, metadata=dict(version.extra or {}),
        ),
        sections=tuple(DocumentSection(
            id=row.id, document_version_id=row.document_version_id, document_id=row.document_id,
            parent_section_id=row.parent_section_id, ordinal=row.ordinal, type=row.type,
            title=row.title, page_start=row.page_start, page_end=row.page_end,
            metadata=dict(row.extra or {}),
        ) for row in sections),
        text_units=tuple(text_unit_from_record(unit) for unit in units),
    )
