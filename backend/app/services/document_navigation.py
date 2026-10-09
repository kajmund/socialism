"""Read and exact-match helpers on ingest sections and text units.

These sit on the existing document model. They do not build a second index,
parser, or anchor system.
"""

from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    CanonicalDocumentRecord,
    DocumentSectionRecord,
    DocumentVersionRecord,
    StoredObject,
    TextUnitRecord,
)
from app.database.workspace_models import VoiceWorkspace, WorkspaceSource
from app.services.workspace.service import require_source
from app.services.workspace.sources import citation, reference_out, source_version
from app.services.workspace.tool_arguments import ReadArguments

_TEXT_LIMIT = 8000
_PARAGRAPH = re.compile(r"\n\s*\n")


def collapsed(text: str) -> str:
    return " ".join(text.casefold().split())


def window_around(text: str, quote: str, paragraphs: int) -> str | None:
    parts = [part.strip() for part in _PARAGRAPH.split(text) if part.strip()]
    if not parts:
        parts = [line.strip() for line in text.splitlines() if line.strip()]
    needle = collapsed(quote)
    if not needle:
        return None
    index = next((i for i, part in enumerate(parts) if needle in collapsed(part)), None)
    if index is None:
        return None
    start = max(0, index - paragraphs)
    end = min(len(parts), index + paragraphs + 1)
    return "\n\n".join(parts[start:end])


def match_section(
    sections: list[DocumentSectionRecord], query: str
) -> DocumentSectionRecord | None:
    needle = collapsed(query)
    if not needle:
        return None
    titles = [(row, collapsed(row.title or "")) for row in sections]
    exact = [row for row, title in titles if title == needle]
    if len(exact) == 1:
        return exact[0]
    contained = [row for row, title in titles if needle in title]
    if len(contained) == 1:
        return contained[0]
    return None


def section_outline(sections: list[DocumentSectionRecord]) -> list[dict]:
    return [
        {
            "title": row.title,
            "type": row.type,
            "ordinal": row.ordinal,
            "page_start": row.page_start,
            "page_end": row.page_end,
        }
        for row in sections
    ]


def _clip(text: str) -> tuple[str, bool]:
    if len(text) <= _TEXT_LIMIT:
        return text, False
    return text[:_TEXT_LIMIT], True


def _current_versions():
    return (
        select(DocumentVersionRecord.id)
        .join(
            CanonicalDocumentRecord,
            CanonicalDocumentRecord.id == DocumentVersionRecord.document_id,
        )
        .where(DocumentVersionRecord.superseded_at.is_(None))
    )


async def _sections(session: AsyncSession, source_id: str) -> list[DocumentSectionRecord]:
    version_ids = _current_versions().where(CanonicalDocumentRecord.source_object_id == source_id)
    rows = await session.scalars(
        select(DocumentSectionRecord)
        .where(DocumentSectionRecord.document_version_id.in_(version_ids))
        .order_by(DocumentSectionRecord.ordinal)
    )
    return list(rows.all())


async def _units(session: AsyncSession, source_id: str) -> list[TextUnitRecord]:
    version_ids = _current_versions().where(CanonicalDocumentRecord.source_object_id == source_id)
    rows = await session.scalars(
        select(TextUnitRecord)
        .where(TextUnitRecord.document_version_id.in_(version_ids))
        .order_by(TextUnitRecord.ordinal)
    )
    return list(rows.all())


def unit_on_page(
    *, page_start: int | None, page_end: int | None, locator: str | None, page: int
) -> bool:
    start = page_start
    end = page_end if page_end is not None else page_start
    if start is not None and end is not None:
        return start <= page <= end
    if locator and locator.startswith("page:"):
        raw = locator.split(":", 1)[1].split("-", 1)[0]
        return raw.isdigit() and int(raw) == page
    return False


def _unit_page(unit: TextUnitRecord) -> int | None:
    if unit.page_start:
        return unit.page_start
    locator = unit.locator or ""
    if not locator.startswith("page:"):
        return None
    raw = locator.split(":", 1)[1].split("-", 1)[0]
    return int(raw) if raw.isdigit() else None


async def read_document_part(
    session: AsyncSession, source: StoredObject, args: ReadArguments
) -> dict:
    if args.page is not None:
        return await _read_page(session, source, args.page)
    sections = await _sections(session, source.id)
    if args.outline:
        return {"status": "completed", "source_id": source.id, "sections": section_outline(sections)}
    if args.section is not None:
        return await _read_section(session, source, sections, args.section)
    return await _read_around(session, source, args.quote or "", args.paragraphs)


async def _read_page(session: AsyncSession, source: StoredObject, page: int) -> dict:
    units = [
        unit
        for unit in await _units(session, source.id)
        if unit_on_page(
            page_start=unit.page_start,
            page_end=unit.page_end,
            locator=unit.locator,
            page=page,
        )
    ]
    body = "\n\n".join(unit.text.strip() for unit in units if unit.text.strip())
    text, truncated = _clip(body)
    return {
        "status": "completed",
        "source_id": source.id,
        "match": "page" if text else "none",
        "page": page,
        "text": text,
        "truncated": truncated,
    }


async def _read_section(
    session: AsyncSession,
    source: StoredObject,
    sections: list[DocumentSectionRecord],
    query: str,
) -> dict:
    outline = section_outline(sections)
    matched = match_section(sections, query)
    if matched is None:
        kind = "ambiguous" if any(collapsed(query) in collapsed(row.title or "") for row in sections) else "none"
        return {"status": "completed", "source_id": source.id, "match": kind, "sections": outline}
    units = [unit for unit in await _units(session, source.id) if unit.section_id == matched.id]
    body = "\n\n".join(unit.text.strip() for unit in units if unit.text.strip())
    text, truncated = _clip(body)
    return {
        "status": "completed",
        "source_id": source.id,
        "match": "section",
        "section": {
            "title": matched.title,
            "page_start": matched.page_start,
            "page_end": matched.page_end,
        },
        "text": text,
        "truncated": truncated,
    }


async def _read_around(
    session: AsyncSession, source: StoredObject, quote: str, paragraphs: int
) -> dict:
    units = await _units(session, source.id)
    needle = collapsed(quote)
    index = next((i for i, unit in enumerate(units) if needle and needle in collapsed(unit.text)), None)
    if index is not None:
        start = max(0, index - paragraphs)
        end = min(len(units), index + paragraphs + 1)
        body = "\n\n".join(unit.text.strip() for unit in units[start:end] if unit.text.strip())
        text, truncated = _clip(body)
        return {
            "status": "completed",
            "source_id": source.id,
            "match": "around",
            "page": _unit_page(units[index]),
            "text": text,
            "truncated": truncated,
        }
    window = window_around(source.extracted_text or "", quote, paragraphs)
    if window is None:
        return {"status": "completed", "source_id": source.id, "match": "none", "text": ""}
    text, truncated = _clip(window)
    return {"status": "completed", "source_id": source.id, "match": "around", "text": text, "truncated": truncated}


async def exact_workspace_search(
    session: AsyncSession,
    workspace: VoiceWorkspace,
    query: str,
    *,
    limit: int,
    source_id: str | None,
) -> dict:
    members = list(
        (await session.scalars(select(WorkspaceSource).where(WorkspaceSource.workspace_id == workspace.id))).all()
    )
    member_ids = {member.source_id for member in members}
    if source_id is not None and source_id not in member_ids:
        raise HTTPException(status_code=404, detail="workspace_source_not_found")
    chosen = [member.source_id for member in members if source_id is None or member.source_id == source_id]
    items: list[dict] = []
    gaps: list[dict] = []
    for member_id in chosen:
        if len(items) >= limit:
            break
        source = await require_source(session, workspace, member_id)
        if source.knowledge_status != "ready" or not (source.extracted_text or "").strip():
            gaps.append({"source_id": source.id, "status": source.knowledge_status, "detail": source.knowledge_error})
            continue
        hits = await _exact_hits(session, workspace, source, query, limit=limit - len(items))
        items.extend(hits)
    return {"items": items, "gaps": gaps}


async def _exact_hits(
    session: AsyncSession,
    workspace: VoiceWorkspace,
    source: StoredObject,
    query: str,
    *,
    limit: int,
) -> list[dict]:
    needle = collapsed(query)
    units = [unit for unit in await _units(session, source.id) if needle in collapsed(unit.text)][:limit]
    if units:
        refs = [await _unit_citation(session, workspace, source, unit) for unit in units]
        return [reference_out(ref) for ref in refs]
    if collapsed(query) not in collapsed(source.extracted_text or ""):
        return []
    window = window_around(source.extracted_text or "", query, 1) or query
    ref = await citation(
        session,
        workspace,
        kind="underlag",
        source_id=source.id,
        version=source_version(source),
        anchor={"anchor_type": "text", "page_number": None, "locator": "document", "exact_text": query, "rects": []},
        snapshot={"title": source.filename, "excerpt": window[:500], "kind": "exact_text"},
    )
    return [reference_out(ref)]


async def _unit_citation(session, workspace, source: StoredObject, unit: TextUnitRecord):
    quote = unit.text.strip()
    return await citation(
        session,
        workspace,
        kind="underlag",
        source_id=source.id,
        version=source_version(source),
        anchor={
            "anchor_type": "text",
            "page_number": _unit_page(unit),
            "locator": unit.locator or "document",
            "exact_text": quote[:500],
            "rects": [],
        },
        snapshot={"title": source.filename, "excerpt": quote[:500], "kind": "exact_text"},
    )
