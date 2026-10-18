"""Manual document marks on uploaded underlag. Ingest does not generate cards."""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Sequence
from typing import Protocol

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.database.transaction_state import has_pending_writes
from app.database.models import (
    DocumentKnowledgeAnchor,
    DocumentKnowledgeItem,
    DocumentKnowledgeItemTextUnit,
    DocumentKnowledgeRevision,
    KnowledgeDocumentRecord,
    StoredObject,
)
from app.serializers import format_date, utcnow
from app.services.knowledge import (
    SUPABASE_PROVIDER_ID,
    OpenAIEmbeddingProvider as OpenAIEmbeddingProvider,
)
from app.services.knowledge.supabase_provider import supabase_external_id
from app.services.research.composition import require_knowledge_vector_store
from app.services.underlag_schemas import (
    DocumentKnowledgeAnchorWrite,
    DocumentKnowledgeItemUpdate,
    DocumentKnowledgeItemWrite,
)

DOCUMENT_INGEST_JOB_KIND = "document_ingest"
DOCUMENT_ITEM_VECTOR_PREFIX = "document-knowledge:"


class DocumentIngestJobRequest(BaseModel):
    object_id: str = Field(min_length=1, max_length=64)
    owner_user_id: str = Field(min_length=1, max_length=64)


def item_vector_document_id(item_id: str) -> str:
    return f"{DOCUMENT_ITEM_VECTOR_PREFIX}{item_id}"


def serialize_document_knowledge_item(item: DocumentKnowledgeItem) -> dict:
    return {
        "id": item.id,
        "source_object_id": item.source_object_id,
        "kind": item.kind,
        "origin": item.origin,
        "status": item.status,
        "title": item.title,
        "question": item.question,
        "content": item.content,
        "retrieval_queries": list(item.retrieval_queries or []),
        "supporting_text_unit_ids": [
            link.text_unit_id
            for link in sorted(item.text_unit_links, key=lambda row: row.ordinal)
        ],
        "anchors": [
            {
                "id": anchor.id,
                "ordinal": anchor.ordinal,
                "anchor_type": anchor.anchor_type,
                "page_number": anchor.page_number,
                "locator": anchor.locator,
                "exact_text": anchor.exact_text,
                "prefix_text": anchor.prefix_text,
                "suffix_text": anchor.suffix_text,
                "rects": list(anchor.rects or []),
                "asset_id": anchor.asset_id,
            }
            for anchor in item.anchors
        ],
        "revision": item.revision,
        "created_by_user_id": item.created_by_user_id,
        "updated_by_user_id": item.updated_by_user_id,
        "created_at": format_date(item.created_at),
        "updated_at": format_date(item.updated_at),
    }


async def list_document_knowledge(
    session: AsyncSession,
    *,
    source_object_id: str,
    include_archived: bool = False,
) -> list[DocumentKnowledgeItem]:
    stmt = (
        select(DocumentKnowledgeItem)
        .options(
            selectinload(DocumentKnowledgeItem.anchors),
            selectinload(DocumentKnowledgeItem.text_unit_links),
        )
        .where(
            DocumentKnowledgeItem.source_object_id == source_object_id,
            DocumentKnowledgeItem.origin != "generated",
        )
    )
    if not include_archived:
        stmt = stmt.where(DocumentKnowledgeItem.status != "archived")
    stmt = stmt.order_by(DocumentKnowledgeItem.created_at.asc(), DocumentKnowledgeItem.id.asc())
    return list((await session.execute(stmt)).scalars().all())


async def get_document_knowledge_item(
    session: AsyncSession,
    *,
    source_object_id: str,
    item_id: str,
) -> DocumentKnowledgeItem | None:
    stmt = (
        select(DocumentKnowledgeItem)
        .options(
            selectinload(DocumentKnowledgeItem.anchors),
            selectinload(DocumentKnowledgeItem.text_unit_links),
        )
        .where(
            DocumentKnowledgeItem.id == item_id,
            DocumentKnowledgeItem.source_object_id == source_object_id,
            DocumentKnowledgeItem.origin != "generated",
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_manual_document_knowledge(
    session: AsyncSession,
    *,
    source: StoredObject,
    user_id: str,
    body: DocumentKnowledgeItemWrite,
) -> DocumentKnowledgeItem:
    item = DocumentKnowledgeItem(
        id=secrets.token_hex(16),
        source_object_id=source.id,
        customer_id=source.customer_id,
        kind=body.kind,
        origin="manual",
        status="active",
        title=body.title,
        question=body.question,
        content=body.content,
        retrieval_queries=[],
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
        revision=1,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(item)
    _replace_anchors(item, body.anchors)
    await _replace_text_unit_links(session, item, list(body.supporting_text_unit_ids))
    await session.flush()
    session.add(_revision_row(item, changed_by_user_id=user_id))
    await session.flush()
    return item


async def update_document_knowledge(
    session: AsyncSession,
    *,
    source: StoredObject,
    item: DocumentKnowledgeItem,
    user_id: str,
    body: DocumentKnowledgeItemUpdate,
) -> DocumentKnowledgeItem:
    item.kind = body.kind
    item.title = body.title
    item.question = body.question
    item.content = body.content
    item.updated_by_user_id = user_id
    item.revision += 1
    item.updated_at = utcnow()
    for anchor in list(item.anchors):
        await session.delete(anchor)
    await session.flush()
    item.anchors.clear()
    _replace_anchors(item, body.anchors)
    await _replace_text_unit_links(session, item, list(body.supporting_text_unit_ids))
    await session.flush()
    session.add(_revision_row(item, changed_by_user_id=user_id))
    await session.flush()
    return item


async def archive_document_knowledge(
    session: AsyncSession,
    *,
    item: DocumentKnowledgeItem,
    user_id: str,
) -> None:
    item.status = "archived"
    item.updated_by_user_id = user_id
    item.revision += 1
    item.updated_at = utcnow()
    session.add(_revision_row(item, changed_by_user_id=user_id))
    await _remove_item_vector(session, item.id)
    await session.flush()


async def delete_document_vectors(session: AsyncSession, source_object_id: str) -> None:
    rows = list(
        (
            await session.execute(
                select(KnowledgeDocumentRecord).where(
                    KnowledgeDocumentRecord.source_object_id == source_object_id
                )
            )
        )
        .scalars()
        .all()
    )
    indexed_rows = [
        row.document_id
        for row in rows
        if row.version is not None or row.document_id.startswith(DOCUMENT_ITEM_VECTOR_PREFIX)
    ]
    if has_pending_writes(session):
        raise RuntimeError("Vector deletion requires a clean input transaction")
    await session.rollback()
    if not indexed_rows:
        return
    vector_store = require_knowledge_vector_store()
    for document_id in indexed_rows:
        await vector_store.delete_document(document_id)


async def run_document_ingest_job(
    factory: async_sessionmaker[AsyncSession],
    *,
    job_id: str,
) -> dict[str, object]:
    from app.services.document_ingest_job import run_document_ingest_job as run_job

    return await run_job(factory, job_id=job_id)


class _Passage(Protocol):
    id: str
    locator: str | None
    text: str


def supporting_text_unit_ids(
    *,
    locator: str | None,
    exact_quote: str | None,
    units: Sequence[_Passage],
) -> list[str]:
    quote = " ".join((exact_quote or "").split())
    matches = [unit for unit in units if quote and quote in " ".join(unit.text.split())]
    if locator:
        located = [unit for unit in matches if unit.locator == locator]
        if located:
            matches = located
        else:
            matches = []
    return [unit.id for unit in matches]


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def _page_number(locator: str | None) -> int | None:
    if not locator or not locator.startswith("page:"):
        return None
    raw = locator.split(":", 1)[1].split("-", 1)[0]
    return int(raw) if raw.isdigit() else None


async def _upsert_raw_document_record(
    session: AsyncSession,
    source: StoredObject,
) -> KnowledgeDocumentRecord:
    record = await session.get(KnowledgeDocumentRecord, source.id)
    if record is None:
        record = KnowledgeDocumentRecord(
            document_id=source.id,
            provider=SUPABASE_PROVIDER_ID,
            external_id=supabase_external_id(source.bucket, source.object_key),
            customer_id=source.customer_id,
            source_object_id=source.id,
            case_id=source.id,
            module=source.module,
            title=source.filename,
            mime_type=source.content_type,
            storage_bucket=source.bucket,
            storage_key=source.object_key,
            version=None,
            extra={
                "knowledge_kind": "document_chunk",
                "source_object_id": source.id,
                "filename": source.filename,
                "workspace_id": source.workspace_id,
            },
        )
        session.add(record)
    else:
        record.source_object_id = source.id
        record.case_id = source.id
        record.module = source.module
        record.title = source.filename
        record.mime_type = source.content_type
        record.storage_bucket = source.bucket
        record.storage_key = source.object_key
    await session.flush()
    return record


async def _remove_item_vector(session: AsyncSession, item_id: str) -> None:
    from app.services.document_item_index import remove_item

    await remove_item(session, item_id)


async def _replace_text_unit_links(
    session: AsyncSession,
    item: DocumentKnowledgeItem,
    unit_ids: Sequence[str],
) -> None:
    from app.services.document_item_grounding import validated_unit_ids

    ids = await validated_unit_ids(session, item, unit_ids)
    if item.id:
        await session.execute(
            delete(DocumentKnowledgeItemTextUnit).where(
                DocumentKnowledgeItemTextUnit.item_id == item.id
            )
        )
        await session.flush()
    set_committed_value(item, "text_unit_links", [])
    seen: set[str] = set()
    ordinal = 0
    for unit_id in ids:
        if unit_id in seen:
            continue
        seen.add(unit_id)
        item.text_unit_links.append(
            DocumentKnowledgeItemTextUnit(
                item_id=item.id,
                text_unit_id=unit_id,
                ordinal=ordinal,
            )
        )
        ordinal += 1


def _replace_anchors(
    item: DocumentKnowledgeItem,
    anchors: Iterable[DocumentKnowledgeAnchorWrite],
) -> None:
    item.anchors.clear()
    for ordinal, anchor in enumerate(anchors):
        item.anchors.append(
            DocumentKnowledgeAnchor(
                id=secrets.token_hex(16),
                ordinal=ordinal,
                anchor_type=anchor.anchor_type,
                page_number=anchor.page_number,
                locator=anchor.locator,
                exact_text=anchor.exact_text,
                prefix_text=anchor.prefix_text,
                suffix_text=anchor.suffix_text,
                rects=[rect.model_dump(mode="json") for rect in anchor.rects],
                asset_id=anchor.asset_id,
                created_at=utcnow(),
            )
        )


def _revision_row(
    item: DocumentKnowledgeItem,
    *,
    changed_by_user_id: str | None,
) -> DocumentKnowledgeRevision:
    return DocumentKnowledgeRevision(
        item_id=item.id,
        revision=item.revision,
        snapshot={
            "kind": item.kind,
            "origin": item.origin,
            "status": item.status,
            "title": item.title,
            "question": item.question,
            "content": item.content,
            "retrieval_queries": list(item.retrieval_queries or []),
            "supporting_text_unit_ids": [
                link.text_unit_id
                for link in sorted(item.text_unit_links, key=lambda row: row.ordinal)
            ],
            "anchors": [
                {
                    "anchor_type": anchor.anchor_type,
                    "page_number": anchor.page_number,
                    "locator": anchor.locator,
                    "exact_text": anchor.exact_text,
                    "prefix_text": anchor.prefix_text,
                    "suffix_text": anchor.suffix_text,
                    "rects": list(anchor.rects or []),
                    "asset_id": anchor.asset_id,
                }
                for anchor in item.anchors
            ],
        },
        changed_by_user_id=changed_by_user_id,
        created_at=utcnow(),
    )


def _extraction_status(status: str) -> str:
    if status == "indexed":
        return "ok"
    return status


def _extracted_text(extracted) -> str | None:
    if extracted is None:
        return None
    text = "\n\n".join(block.text.strip() for block in extracted.blocks if block.text.strip())
    return text or None
