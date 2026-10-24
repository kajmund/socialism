"""Materialize an immutable canonical graph before releasing its SQL transaction."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DocumentSectionRecord, DocumentVersionRecord
from app.services.knowledge.units import DocumentSection, SegmentedDocument
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.overgraph.owner_writer import load_text_units_via_owner


def _section(row: DocumentSectionRecord) -> DocumentSection:
    return DocumentSection(
        id=row.id, document_version_id=row.document_version_id, document_id=row.document_id,
        parent_section_id=row.parent_section_id, ordinal=row.ordinal, type=row.type,
        title=row.title, page_start=row.page_start, page_end=row.page_end,
        metadata=dict(row.extra or {}),
    )


async def persisted_segment(
    session: AsyncSession,
    segmented: SegmentedDocument,
    version: DocumentVersionRecord,
) -> SegmentedDocument:
    version_id = version.id
    version_fields = {
        "ingested_at": version.ingested_at,
        "superseded_at": version.superseded_at,
        "metadata": dict(version.extra or {}),
    }
    rows = list(await session.scalars(select(DocumentSectionRecord).where(
        DocumentSectionRecord.document_version_id == version_id,
    ).order_by(DocumentSectionRecord.ordinal)))
    sections = tuple(_section(row) for row in rows)
    units = await load_text_units_via_owner(
        get_owner_runtime().require_client(), document_version_id=version_id,
    )
    return replace(
        segmented,
        version=replace(segmented.version, id=version_id, **version_fields),
        sections=sections,
        text_units=tuple(units),
    )
