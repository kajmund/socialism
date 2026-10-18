"""Document ingest: extract and persist TextUnits, then enqueue OverGraph write.

Embeddings run after the job has succeeded. They are not part of Dokumentförståelse.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass

from openai import OpenAIError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Job, KnowledgeDocumentRecord, StoredObject
from app.services.document_ingest_batch.progress import (
    record_extracting,
    record_job_failed,
    record_job_result,
)
from app.services.document_qa.catalog_outbox import enqueue_document_catalog
from app.services.knowledge.canonical_ingest import (
    ExtractedSourceIdentity,
    PersistedExtractedSource,
    embed_persisted_document,
    persist_extracted_source,
)
from app.services.knowledge.extractors import DefaultTextExtractor, ExtractedDocument
from app.services.knowledge.ingest import KnowledgeIngestResult
from app.services.knowledge.models import KnowledgeDocument, KnowledgeScope
from app.services.knowledge.provider import KnowledgeVectorStoreError
from app.services.object_storage import KIND_UNDERLAG, get_object
from app.services.research.composition import ResearchCompositionError

_EXTRACT_SLOTS = asyncio.Semaphore(3)
_EMBED_SLOTS = asyncio.Semaphore(3)
# Expected failure modes only: vector store, embedding provider, or DB load errors.
_EMBED_ERRORS = (
    KnowledgeVectorStoreError,
    OpenAIError,
    ResearchCompositionError,
    SQLAlchemyError,
    RuntimeError,
    ValueError,
)


@dataclass(frozen=True)
class _LoadedSource:
    object_id: str
    filename: str
    content_type: str
    customer_id: int
    workspace_id: str | None
    module: str
    owner_user_id: str
    bucket: str
    object_key: str
    previous_status: str
    external_id: str


@dataclass(frozen=True)
class _IndexedWork:
    result: KnowledgeIngestResult
    knowledge_status: str
    graph_work_id: str | None


async def run_document_ingest_job(factory: async_sessionmaker[AsyncSession], *, job_id: str) -> dict[str, object]:
    await record_extracting(factory, job_id)
    try:
        async with _EXTRACT_SLOTS:
            loaded = await _prepare_source(factory, job_id)
            data, extracted = await _read_and_extract(loaded)
            persisted = await _persist_text(factory, loaded=loaded, data=data, extracted=extracted)
        if persisted.result.status != "indexed":
            payload = _progress_payload(loaded, _IndexedWork(persisted.result, persisted.result.status, None))
            await record_job_result(factory, job_id, payload)
            return payload
        indexed = await _finish_ready(factory, loaded=loaded, result=persisted.result)
        payload = _progress_payload(loaded, indexed)
        await record_job_result(factory, job_id, payload)
        return payload
    except Exception as exc:
        await record_job_failed(factory, job_id, str(exc) or exc.__class__.__name__)
        await _mark_source_failed(factory, job_id, exc)
        raise


async def _prepare_source(factory: async_sessionmaker[AsyncSession], job_id: str) -> _LoadedSource:
    from app.services import document_knowledge as knowledge

    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")
        payload = knowledge.DocumentIngestJobRequest.model_validate(job.request or {})
        source = await session.get(StoredObject, payload.object_id)
        if (
            source is None
            or source.kind != KIND_UNDERLAG
            or source.customer_id != job.customer_id
            or source.owner_user_id != payload.owner_user_id
        ):
            raise ValueError("Underlag not found for document ingest")
        previous_status = source.knowledge_status
        source.knowledge_status, source.knowledge_error = "running", None
        raw = await knowledge._upsert_raw_document_record(session, source)
        loaded = _LoadedSource(
            object_id=source.id,
            filename=source.filename,
            content_type=source.content_type,
            customer_id=source.customer_id,
            workspace_id=source.workspace_id,
            module=source.module,
            owner_user_id=source.owner_user_id,
            bucket=source.bucket,
            object_key=source.object_key,
            previous_status=previous_status,
            external_id=raw.external_id,
        )
        await session.commit()
        return loaded


async def _read_and_extract(loaded: _LoadedSource) -> tuple[bytes, ExtractedDocument]:
    data, _content_type = await get_object(loaded.bucket, loaded.object_key)
    extracted = await DefaultTextExtractor().extract(data, loaded.content_type)
    return data, extracted


async def _persist_text(
    factory: async_sessionmaker[AsyncSession],
    *,
    loaded: _LoadedSource,
    data: bytes,
    extracted: ExtractedDocument,
) -> PersistedExtractedSource:
    from app.services import document_knowledge as knowledge

    async with factory() as session:
        source = await session.get(StoredObject, loaded.object_id)
        if source is None:
            raise ValueError("Underlag not found for document ingest")
        raw = await session.get(KnowledgeDocumentRecord, loaded.object_id)
        if raw is None:
            raw = await knowledge._upsert_raw_document_record(session, source)
        persisted = await persist_extracted_source(
            session,
            extracted=extracted,
            document=_document(loaded),
            identity=ExtractedSourceIdentity(
                source_type="uploaded_file",
                canonical_uri=f"stored-object:{loaded.object_id}",
                content_hash=hashlib.sha256(data).hexdigest(),
                customer_id=loaded.customer_id,
                source_object_id=loaded.object_id,
            ),
        )
        source.extraction_status = knowledge._extraction_status(persisted.result.status)
        source.extracted_text = knowledge._extracted_text(persisted.result.extracted)
        source.content_sha256 = persisted.result.content_hash
        raw.version = persisted.result.content_hash
        raw.extra = {
            **dict(raw.extra or {}),
            "content_hash": persisted.result.content_hash,
            "document_version_id": persisted.result.document_version_id,
        }
        if persisted.result.status != "indexed":
            source.knowledge_status, source.knowledge_error = persisted.result.status, persisted.result.message
        elif persisted.result.reused_version and loaded.previous_status == "ready":
            source.knowledge_status = "ready"
        await session.commit()
        return persisted


async def embed_after_ingest(
    factory: async_sessionmaker[AsyncSession], payload: dict[str, object],
) -> None:
    """Write vectors after Dokumentförståelse has already succeeded."""
    if str(payload.get("status") or "") != "ready":
        return
    document_id = str(payload.get("document_id") or payload.get("object_id") or "")
    object_id = str(payload.get("object_id") or document_id)
    if not document_id:
        return
    from app.services import document_knowledge as knowledge

    try:
        async with _EMBED_SLOTS:
            async with factory() as session:
                await embed_persisted_document(
                    session,
                    document_id=document_id,
                    embeddings=knowledge.OpenAIEmbeddingProvider.from_settings(),
                    vector_store=knowledge.require_knowledge_vector_store(),
                )
    except _EMBED_ERRORS as exc:  # Persist already succeeded; missing vectors are repairable.
        await _mark_embed_partial(factory, object_id, exc)


async def _finish_ready(
    factory: async_sessionmaker[AsyncSession],
    *,
    loaded: _LoadedSource,
    result: KnowledgeIngestResult,
) -> _IndexedWork:
    async with factory() as session:
        source = await session.get(StoredObject, loaded.object_id)
        if source is None:
            raise ValueError("Underlag not found for document ingest")
        work_id = None
        if result.status == "indexed":
            work_id = await enqueue_document_catalog(
                session,
                customer_id=loaded.customer_id,
                document_id=result.document_id,
                document_version_id=result.document_version_id or "",
                workspace_id=loaded.workspace_id or "",
            )
            source.knowledge_status = "ready"
            source.knowledge_error = None
        elif result.reused_version and loaded.previous_status == "ready":
            source.knowledge_status = "ready"
        else:
            source.knowledge_status, source.knowledge_error = result.status, result.message
        await session.commit()
        return _IndexedWork(result, source.knowledge_status, work_id)


def _document(loaded: _LoadedSource) -> KnowledgeDocument:
    from app.services import document_knowledge as knowledge

    return KnowledgeDocument(
        document_id=loaded.object_id,
        provider=knowledge.SUPABASE_PROVIDER_ID,
        external_id=loaded.external_id,
        title=loaded.filename,
        mime_type=loaded.content_type,
        scope=KnowledgeScope(
            customer_id=loaded.customer_id,
            case_id=loaded.object_id,
            module=loaded.module,
            workspace_id=loaded.workspace_id,
        ),
        metadata={
            "source_object_id": loaded.object_id,
            "workspace_id": loaded.workspace_id,
            "case_id": loaded.object_id,
            "module": loaded.module,
            "provider": knowledge.SUPABASE_PROVIDER_ID,
        },
    )


def _progress_payload(loaded: _LoadedSource, indexed: _IndexedWork) -> dict[str, object]:
    payload: dict[str, object] = {
        "object_id": loaded.object_id,
        "document_id": indexed.result.document_id,
        "status": indexed.knowledge_status,
        "chunks_indexed": indexed.result.chunks_indexed,
        "items_created": 0,
        "document_version_id": indexed.result.document_version_id,
        "reused_version": indexed.result.reused_version,
    }
    if indexed.graph_work_id:
        payload["graph_work_id"] = indexed.graph_work_id
    if indexed.result.message:
        payload["message"] = indexed.result.message
    return payload


async def _mark_source_failed(
    factory: async_sessionmaker[AsyncSession], job_id: str, exc: BaseException,
) -> None:
    from app.services import document_knowledge as knowledge
    from app.services.document_ingest_status import document_text_ready

    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        payload = knowledge.DocumentIngestJobRequest.model_validate(job.request or {})
        source = await session.get(StoredObject, payload.object_id)
        if source is None:
            return
        source.knowledge_status = "partial" if document_text_ready(source) else "failed"
        source.knowledge_error = (str(exc) or exc.__class__.__name__)[:2000]
        await session.commit()


async def _mark_embed_partial(
    factory: async_sessionmaker[AsyncSession], object_id: str, exc: BaseException,
) -> None:
    from app.services.document_ingest_status import document_text_ready

    async with factory() as session:
        source = await session.get(StoredObject, object_id)
        if source is None or not document_text_ready(source):
            return
        source.knowledge_status = "partial"
        source.knowledge_error = (str(exc) or exc.__class__.__name__)[:2000]
        await session.commit()
