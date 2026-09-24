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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import (
    DocumentKnowledgeAnchor,
    DocumentKnowledgeItem,
    DocumentKnowledgeItemTextUnit,
    DocumentKnowledgeRevision,
    Job,
    KnowledgeDocumentRecord,
    StoredObject,
)
from app.llm import complete_structured_retry
from app.llm.structured_retry import StructuredOutputError
from app.serializers import format_date, utcnow
from app.services.knowledge import (
    SUPABASE_PROVIDER_ID,
    EmbeddedKnowledgeChunk,
    KnowledgeChunk,
    KnowledgeIngestService,
    KnowledgeScope,
    OpenAIEmbeddingProvider,
    SupabaseKnowledgeProvider,
)
from app.services.knowledge.persistence import current_text_units, persist_segmented_document
from app.services.knowledge.supabase_provider import supabase_external_id
from app.services.knowledge.units import TextUnit
from app.services.object_storage import KIND_UNDERLAG
from app.services.prompt_store import render_prompt, require_active_prompts
from app.services.research.composition import require_knowledge_vector_store
from app.services.stored_objects import read_stored_bytes
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
        row
        for row in rows
        if row.version is not None or row.document_id.startswith(DOCUMENT_ITEM_VECTOR_PREFIX)
    ]
    if not indexed_rows:
        return
    vector_store = require_knowledge_vector_store()
    for row in indexed_rows:
        await vector_store.delete_document(row.document_id)


async def run_document_ingest_job(
    factory: async_sessionmaker[AsyncSession],
    *,
    job_id: str,
) -> dict[str, object]:
    try:
        return await _run_document_ingest_job(factory, job_id=job_id)
    except Exception as exc:
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                payload = DocumentIngestJobRequest.model_validate(job.request or {})
                source = await session.get(StoredObject, payload.object_id)
                if source is not None:
                    source.knowledge_status = "failed"
                    source.knowledge_error = (str(exc) or exc.__class__.__name__)[:2000]
                    await session.commit()
        raise


async def _run_document_ingest_job(
    factory: async_sessionmaker[AsyncSession],
    *,
    job_id: str,
) -> dict[str, object]:
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")
        payload = DocumentIngestJobRequest.model_validate(job.request or {})
        source = await session.get(StoredObject, payload.object_id)
        if (
            source is None
            or source.kind != KIND_UNDERLAG
            or source.customer_id != job.customer_id
            or source.owner_user_id != payload.owner_user_id
        ):
            raise ValueError("Underlag not found for document ingest")
        source.knowledge_status = "running"
        source.knowledge_error = None
        raw_record = await _upsert_raw_document_record(session, source)
        is_reingest = raw_record.version is not None
        await session.commit()

        vector_store = require_knowledge_vector_store()
        embeddings = OpenAIEmbeddingProvider.from_settings()
        provider = SupabaseKnowledgeProvider(
            session,
            vector_store=vector_store,
            embeddings=embeddings,
        )
        result = await KnowledgeIngestService(
            provider=provider,
            vector_store=vector_store,
            embeddings=embeddings,
        ).ingest_document(
            document_id=raw_record.document_id,
            scope=KnowledgeScope(
                customer_id=source.customer_id,
                case_id=source.id,
                module=source.module,
            ),
        )
        source.extraction_status = _extraction_status(result.status)
        source.extracted_text = _extracted_text(result.extracted)
        raw_record.version = result.content_hash
        raw_record.extra = {
            **dict(raw_record.extra or {}),
            "content_hash": result.content_hash,
        }
        if result.status != "indexed" or result.extracted is None or result.segmented is None:
            source.knowledge_status = result.status
            source.knowledge_error = result.message
            await session.commit()
            if result.status == "failed":
                raise RuntimeError(result.message or "Document ingest failed")
            return {
                "object_id": source.id,
                "status": result.status,
                "chunks_indexed": result.chunks_indexed,
                "items_created": 0,
            }

        await persist_segmented_document(
            session,
            customer_id=source.customer_id,
            source_object_id=source.id,
            segmented=result.segmented,
        )
        # Vectors and TextUnits already exist outside this transaction. Persist
        # them before optional LLM enrichment so a later generation failure
        # cannot leave an untracked index.
        await session.commit()

        prompts = await require_active_prompts(
            session,
            customer_id=source.customer_id,
            module=source.module,
            language="sv",
        )
        data, _content_type = await read_stored_bytes(source)
        generation = await generate_document_knowledge(
            units=result.segmented.text_units,
            prompts=prompts,
        )
        accepted = await asyncio.to_thread(
            _accepted_generated_items,
            generation.items,
            units=result.segmented.text_units,
            pdf_bytes=data if source.content_type == "application/pdf" else None,
        )
        # A transient enrichment failure must not discard earlier generated
        # knowledge on re-ingest. Replace it only when at least one batch
        # completed, or when all batches completed successfully with no items.
        replace_generated = (
            generation.successful_batches > 0 or generation.failed_batches == 0
        )
        rows: list[DocumentKnowledgeItem] = []
        if replace_generated:
            await _archive_generated_items(session, source, mark_manual_stale=is_reingest)
            rows = await _persist_generated_items(session, source=source, items=accepted)
            await _index_generated_items(session, source=source, items=rows)
        partial = generation.failed_batches > 0
        source.knowledge_status = "partial" if partial else "ready"
        source.knowledge_error = (
            f"{generation.failed_batches} of {generation.total_batches} "
            "document-knowledge batches failed"
            if partial
            else None
        )
        await session.commit()
        return {
            "object_id": source.id,
            "status": source.knowledge_status,
            "chunks_indexed": result.chunks_indexed,
            "items_created": len(rows),
            "successful_batches": generation.successful_batches,
            "failed_batches": generation.failed_batches,
        }


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
    current: list[str] = []
    size = 0
    for unit in units:
        text = unit.text.strip()
        if not text:
            continue
        rendered = (
            f'<text_unit id="{unit.id}" locator="{(unit.locator or "unknown").strip()}">\n'
            f"{text}\n</text_unit>"
        )
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
    quote = _normalized(exact_quote or "")
    matches = [unit for unit in units if quote and quote in _normalized(unit.text)]
    if locator:
        located = [unit for unit in matches if unit.locator == locator]
        if located:
            matches = located
        elif not matches:
            matches = [unit for unit in units if unit.locator == locator]
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
        await _remove_item_vector(session, item.id)


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
    searchable = [item for item in items if item.kind in {"fact", "qa"}]
    if not searchable:
        return
    embeddings = OpenAIEmbeddingProvider.from_settings()
    vectors = await embeddings.embed([_embedding_text(item) for item in searchable])
    if len(vectors) != len(searchable):
        raise RuntimeError("EmbeddingProvider returned an unexpected document item count")
    chunks: list[EmbeddedKnowledgeChunk] = []
    for item, vector in zip(searchable, vectors, strict=True):
        await _upsert_item_record(session, source=source, item=item)
        chunks.append(EmbeddedKnowledgeChunk(chunk=_item_chunk(source, item), embedding=vector))
    await require_knowledge_vector_store().upsert_chunks(chunks)


async def _sync_item_vector(
    session: AsyncSession,
    *,
    source: StoredObject,
    item: DocumentKnowledgeItem,
) -> None:
    if item.status != "active" or item.kind not in {"fact", "qa"}:
        await _remove_item_vector(session, item.id)
        return
    embeddings = OpenAIEmbeddingProvider.from_settings()
    vectors = await embeddings.embed([_embedding_text(item)])
    if len(vectors) != 1:
        raise RuntimeError("EmbeddingProvider returned an unexpected document item count")
    await _upsert_item_record(session, source=source, item=item)
    await require_knowledge_vector_store().replace_document_chunks(
        item_vector_document_id(item.id),
        [EmbeddedKnowledgeChunk(chunk=_item_chunk(source, item), embedding=vectors[0])],
    )


async def _upsert_item_record(
    session: AsyncSession,
    *,
    source: StoredObject,
    item: DocumentKnowledgeItem,
) -> KnowledgeDocumentRecord:
    document_id = item_vector_document_id(item.id)
    row = await session.get(KnowledgeDocumentRecord, document_id)
    anchor = item.anchors[0] if item.anchors else None
    extra = {
        "knowledge_kind": "document_item",
        "document_knowledge_item_id": item.id,
        "source_document_id": source.id,
        "source_object_id": source.id,
        "item_kind": item.kind,
        "origin": item.origin,
        "page_number": anchor.page_number if anchor else None,
        "anchor_type": anchor.anchor_type if anchor else None,
    }
    if row is None:
        row = KnowledgeDocumentRecord(
            document_id=document_id,
            provider=SUPABASE_PROVIDER_ID,
            external_id=f"document-knowledge-item:{item.id}",
            customer_id=source.customer_id,
            source_object_id=source.id,
            case_id=source.id,
            module=source.module,
            title=item.title,
            mime_type="application/vnd.socialism.document-knowledge+json",
            storage_bucket=source.bucket,
            storage_key=source.object_key,
            version=str(item.revision),
            extra=extra,
        )
        session.add(row)
    else:
        row.title = item.title
        row.version = str(item.revision)
        row.extra = extra
    await session.flush()
    return row


async def _remove_item_vector(session: AsyncSession, item_id: str) -> None:
    document_id = item_vector_document_id(item_id)
    row = await session.get(KnowledgeDocumentRecord, document_id)
    if row is None:
        return
    await require_knowledge_vector_store().delete_document(document_id)
    await session.delete(row)


def _item_chunk(source: StoredObject, item: DocumentKnowledgeItem) -> KnowledgeChunk:
    anchor = item.anchors[0] if item.anchors else None
    document_id = item_vector_document_id(item.id)
    return KnowledgeChunk(
        document_id=document_id,
        chunk_id=f"revision:{item.revision}",
        text=_display_text(item),
        customer_id=source.customer_id,
        case_id=source.id,
        module=source.module,
        title=item.title,
        locator=anchor.locator if anchor else None,
        provider=SUPABASE_PROVIDER_ID,
        version=str(item.revision),
        content_hash=None,
        metadata={
            "knowledge_kind": "document_item",
            "document_knowledge_item_id": item.id,
            "source_document_id": source.id,
            "source_object_id": source.id,
            "item_kind": item.kind,
            "origin": item.origin,
            "page_number": anchor.page_number if anchor else None,
            "anchor_type": anchor.anchor_type if anchor else None,
        },
    )


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
    ids = [unit_id for unit_id in unit_ids if unit_id]
    if not ids:
        units = await current_text_units(session, item.source_object_id)
        anchor = item.anchors[0] if item.anchors else None
        ids = supporting_text_unit_ids(
            locator=anchor.locator if anchor else None,
            exact_quote=anchor.exact_text if anchor else None,
            units=units,
        )
    for link in list(item.text_unit_links):
        await session.delete(link)
    await session.flush()
    item.text_unit_links.clear()
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
