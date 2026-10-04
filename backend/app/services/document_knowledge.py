"""Mutable document understanding built during underlag ingest."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Literal, Protocol

import pdfplumber
from openai import APITimeoutError
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.config import settings
from app.database.transaction_state import has_pending_writes
from app.database.models import (
    DocumentKnowledgeAnchor,
    DocumentKnowledgeItem,
    DocumentKnowledgeItemTextUnit,
    DocumentKnowledgeRevision,
    KnowledgeDocumentRecord,
    StoredObject,
)
from app.llm import complete_structured_retry
from app.llm.structured_retry import StructuredOutputError
from app.serializers import format_date, utcnow
from app.services.knowledge import (
    SUPABASE_PROVIDER_ID,
    OpenAIEmbeddingProvider as OpenAIEmbeddingProvider,
)
from app.services.knowledge.supabase_provider import supabase_external_id
from app.services.knowledge.units import TextUnit
from app.services.prompt_store import render_prompt
from app.services.research.composition import require_knowledge_vector_store
from app.services.underlag_schemas import (
    DocumentKnowledgeAnchorWrite,
    DocumentKnowledgeItemUpdate,
    DocumentKnowledgeItemWrite,
)

DOCUMENT_INGEST_JOB_KIND = "document_ingest"
DOCUMENT_ITEM_VECTOR_PREFIX = "document-knowledge:"
_BATCH_CHARS = 16_000
_MAX_GENERATED_ITEMS = 80

logger = logging.getLogger(__name__)


class DocumentIngestJobRequest(BaseModel):
    object_id: str = Field(min_length=1, max_length=64)
    owner_user_id: str = Field(min_length=1, max_length=64)


class GeneratedDocumentKnowledge(BaseModel):
    kind: Literal["fact", "qa"]
    title: str = Field(min_length=1, max_length=500)
    question: str | None = Field(default=None, max_length=4000)
    content: str = Field(min_length=1, max_length=12000)
    locator: str = Field(min_length=1, max_length=128)
    exact_quote: str = Field(min_length=1, max_length=4000)
    retrieval_queries: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("title", "question", "content", "locator", "exact_quote", mode="before")
    @classmethod
    def clean_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return " ".join(str(value).split())

    @field_validator("retrieval_queries", mode="before")
    @classmethod
    def clean_queries(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for raw in value:
            query = " ".join(str(raw or "").split())
            if query and query not in out:
                out.append(query[:1000])
        return out[:5]

    @model_validator(mode="after")
    def validate_question(self):
        if self.kind == "qa" and not self.question:
            raise ValueError("qa requires question")
        if self.kind == "fact":
            self.question = None
        return self


class GeneratedDocumentKnowledgeBatch(BaseModel):
    items: list[GeneratedDocumentKnowledge] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True)
class DocumentKnowledgeGenerationResult:
    items: list[GeneratedDocumentKnowledge]
    successful_batches: int
    failed_batches: int

    @property
    def total_batches(self) -> int:
        return self.successful_batches + self.failed_batches


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
        .where(DocumentKnowledgeItem.source_object_id == source_object_id)
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
    await _sync_item_vector(session, source=source, item=item)
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
    await _sync_item_vector(session, source=source, item=item)
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


async def generate_document_knowledge(
    *,
    units: Sequence[TextUnit],
    prompts: dict[str, str],
) -> DocumentKnowledgeGenerationResult:
    batches = _text_unit_batches(units)
    semaphore = asyncio.Semaphore(3)

    async def generate(
        batch_number: int,
        excerpt: str,
    ) -> tuple[list[GeneratedDocumentKnowledge], bool]:
        async with semaphore:
            try:
                response = await complete_structured_retry(
                    [
                        {
                            "role": "system",
                            "content": render_prompt(
                                prompts,
                                "document_knowledge.ingest.system",
                            ),
                        },
                        {
                            "role": "user",
                            "content": render_prompt(
                                prompts,
                                "document_knowledge.ingest.user",
                                document_excerpt=excerpt,
                            ),
                        },
                    ],
                    GeneratedDocumentKnowledgeBatch,
                    retry_instruction=render_prompt(
                        prompts,
                        "document_knowledge.structured_retry",
                    ),
                    max_tokens=settings.document_knowledge_llm_max_tokens,
                    timeout=settings.document_knowledge_llm_timeout_seconds,
                    prompt_key="document_knowledge.ingest.system",
                )
            except (
                TimeoutError,
                APITimeoutError,
                StructuredOutputError,
                ValidationError,
            ) as exc:
                logger.warning(
                    "Document-knowledge generation batch %s/%s failed: %s",
                    batch_number,
                    len(batches),
                    exc.__class__.__name__,
                )
                return [], False
            return response.items, True

    outcomes = await asyncio.gather(
        *(generate(index, batch) for index, batch in enumerate(batches, start=1))
    )
    items = [item for group, _succeeded in outcomes for item in group]
    successful_batches = sum(1 for _group, succeeded in outcomes if succeeded)
    return DocumentKnowledgeGenerationResult(
        items=items[:_MAX_GENERATED_ITEMS],
        successful_batches=successful_batches,
        failed_batches=len(outcomes) - successful_batches,
    )


def _text_unit_batches(units: Sequence[TextUnit]) -> list[str]:
    batches: list[str] = []
    for group in _neighbouring_section_groups(units):
        batches.extend(_pack_rendered_units(group))
    return batches


def _neighbouring_section_groups(units: Sequence[TextUnit]) -> list[list[TextUnit]]:
    grouped: dict[str, list[TextUnit]] = {}
    order: list[str] = []
    for unit in units:
        if not unit.text.strip():
            continue
        key = unit.section_id or unit.id
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(unit)
    return [
        sorted(grouped[key], key=lambda item: (item.ordinal, item.id))
        for key in order
    ]


def _pack_rendered_units(units: Sequence[TextUnit]) -> list[str]:
    batches: list[str] = []
    current: list[str] = []
    size = 0
    for unit in units:
        rendered = _render_text_unit(unit)
        if current and size + len(rendered) > _BATCH_CHARS:
            batches.append("\n\n".join(current))
            current = []
            size = 0
        if len(rendered) <= _BATCH_CHARS:
            current.append(rendered)
            size += len(rendered)
            continue
        if current:
            batches.append("\n\n".join(current))
            current = []
            size = 0
        batches.append(rendered)
    if current:
        batches.append("\n\n".join(current))
    return batches


def _render_text_unit(unit: TextUnit) -> str:
    return (
        f'<text_unit id="{unit.id}" locator="{(unit.locator or "unknown").strip()}">\n'
        f"{unit.text.strip()}\n</text_unit>"
    )


@dataclass(frozen=True)
class AcceptedGeneratedItem:
    item: GeneratedDocumentKnowledge
    rects: list[dict[str, float]]
    text_unit_ids: list[str]


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


def _accepted_generated_items(
    generated: Sequence[GeneratedDocumentKnowledge],
    *,
    units: Sequence[TextUnit],
    pdf_bytes: bytes | None,
) -> list[AcceptedGeneratedItem]:
    seen: set[tuple[str, str]] = set()
    out: list[AcceptedGeneratedItem] = []
    pdf = pdfplumber.open(BytesIO(pdf_bytes)) if pdf_bytes is not None else None
    try:
        for item in generated:
            unit_ids = supporting_text_unit_ids(
                locator=item.locator,
                exact_quote=item.exact_quote,
                units=units,
            )
            if not unit_ids:
                continue
            key = (_normalized(item.title), _normalized(item.content))
            if key in seen:
                continue
            seen.add(key)
            page_number = _page_number(item.locator)
            rects = (
                _quote_rects(pdf, page_number, item.exact_quote)
                if pdf is not None and page_number is not None
                else []
            )
            out.append(AcceptedGeneratedItem(item=item, rects=rects, text_unit_ids=unit_ids))
    finally:
        if pdf is not None:
            pdf.close()
    return out


def _quote_rects(
    pdf: pdfplumber.PDF,
    page_number: int,
    quote: str,
) -> list[dict[str, float]]:
    if page_number < 1 or page_number > len(pdf.pages):
        return []
    page = pdf.pages[page_number - 1]
    words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
    quote_tokens = _word_tokens(quote)
    if not quote_tokens:
        return []
    tokens: list[str] = []
    token_words: list[int] = []
    for index, word in enumerate(words):
        for token in _word_tokens(str(word.get("text") or "")):
            tokens.append(token)
            token_words.append(index)
    start = _subsequence_start(tokens, quote_tokens)
    if start is None:
        return []
    selected = words[token_words[start] : token_words[start + len(quote_tokens) - 1] + 1]
    if not selected or not page.width or not page.height:
        return []
    lines: list[list[dict]] = []
    for word in selected:
        top = float(word["top"])
        line = next(
            (group for group in lines if abs(float(group[0]["top"]) - top) <= 3.0),
            None,
        )
        if line is None:
            line = []
            lines.append(line)
        line.append(word)
    rects: list[dict[str, float]] = []
    for line in lines:
        x0 = min(float(word["x0"]) for word in line)
        x1 = max(float(word["x1"]) for word in line)
        top = min(float(word["top"]) for word in line)
        bottom = max(float(word["bottom"]) for word in line)
        rects.append(
            {
                "x": max(0.0, min(1.0, x0 / float(page.width))),
                "y": max(0.0, min(1.0, top / float(page.height))),
                "width": max(0.0001, min(1.0, (x1 - x0) / float(page.width))),
                "height": max(0.0001, min(1.0, (bottom - top) / float(page.height))),
            }
        )
    return rects


def _subsequence_start(values: Sequence[str], needle: Sequence[str]) -> int | None:
    width = len(needle)
    for index in range(len(values) - width + 1):
        if list(values[index : index + width]) == list(needle):
            return index
    return None


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


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


async def _archive_generated_items(
    session: AsyncSession,
    source: StoredObject,
    *,
    mark_manual_stale: bool,
) -> None:
    rows = await list_document_knowledge(
        session,
        source_object_id=source.id,
        include_archived=False,
    )
    for item in rows:
        if item.origin != "generated":
            if mark_manual_stale and item.status == "active":
                item.status = "needs_review"
                item.revision += 1
                item.updated_at = utcnow()
                session.add(_revision_row(item, changed_by_user_id=None))
            continue
        item.status = "archived"
        item.revision += 1
        item.updated_at = utcnow()
        session.add(_revision_row(item, changed_by_user_id=None))
        record = await session.get(KnowledgeDocumentRecord, item_vector_document_id(item.id))
        if record is not None:
            await session.delete(record)


async def _persist_generated_items(
    session: AsyncSession,
    *,
    source: StoredObject,
    items: Sequence[AcceptedGeneratedItem],
) -> list[DocumentKnowledgeItem]:
    rows: list[DocumentKnowledgeItem] = []
    for accepted in items:
        generated = accepted.item
        rects = accepted.rects
        item = DocumentKnowledgeItem(
            id=secrets.token_hex(16),
            source_object_id=source.id,
            customer_id=source.customer_id,
            kind=generated.kind,
            origin="generated",
            status="active",
            title=generated.title,
            question=generated.question,
            content=generated.content,
            retrieval_queries=generated.retrieval_queries,
            created_by_user_id=None,
            updated_by_user_id=None,
            revision=1,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(item)
        page = _page_number(generated.locator)
        item.anchors.append(
            DocumentKnowledgeAnchor(
                id=secrets.token_hex(16),
                ordinal=0,
                anchor_type="text",
                page_number=page,
                locator=generated.locator,
                exact_text=generated.exact_quote,
                prefix_text=None,
                suffix_text=None,
                rects=rects,
                asset_id=None,
                created_at=utcnow(),
            )
        )
        await session.flush()
        await _replace_text_unit_links(session, item, accepted.text_unit_ids)
        await session.flush()
        session.add(_revision_row(item, changed_by_user_id=None))
        rows.append(item)
    await session.flush()
    return rows


async def _index_generated_items(
    session: AsyncSession,
    *,
    source: StoredObject,
    items: Sequence[DocumentKnowledgeItem],
) -> None:
    from app.services.document_item_index import index_items

    await index_items(session, source=source, items=items)


async def _sync_item_vector(
    session: AsyncSession,
    *,
    source: StoredObject,
    item: DocumentKnowledgeItem,
) -> None:
    from app.services.document_item_index import sync_item

    await sync_item(session, source=source, item=item)


async def _remove_item_vector(session: AsyncSession, item_id: str) -> None:
    from app.services.document_item_index import remove_item

    await remove_item(session, item_id)


def _display_text(item: DocumentKnowledgeItem) -> str:
    parts = [item.title]
    if item.question:
        parts.append(item.question)
    if item.content:
        parts.append(item.content)
    return "\n\n".join(part for part in parts if part.strip())


def _embedding_text(item: DocumentKnowledgeItem) -> str:
    parts = [_display_text(item), *list(item.retrieval_queries or [])]
    return "\n".join(part for part in parts if part.strip())


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
