"""Document ingest transactions around external extraction, embeddings and Q&A."""

from __future__ import annotations

import asyncio
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Job, StoredObject
from app.services.knowledge.canonical_ingest import ingest_extracted_source
from app.services.knowledge.extractors import DefaultTextExtractor
from app.services.knowledge.models import KnowledgeDocument, KnowledgeScope
from app.services.knowledge.persistence import current_text_units, text_unit_from_record
from app.services.object_storage import KIND_UNDERLAG
from app.services.prompt_store import require_active_prompts
from app.services.stored_objects import read_stored_bytes


async def run_document_ingest_job(factory: async_sessionmaker[AsyncSession], *, job_id: str) -> dict[str, object]:
    from app.services import document_knowledge as knowledge

    try:
        return await _run_ingest(factory, job_id=job_id)
    except Exception as exc:
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                payload = knowledge.DocumentIngestJobRequest.model_validate(job.request or {})
                source = await session.get(StoredObject, payload.object_id)
                if source is not None:
                    source.knowledge_status = "failed"
                    source.knowledge_error = (str(exc) or exc.__class__.__name__)[:2000]
                    await session.commit()
        raise


async def _run_ingest(factory: async_sessionmaker[AsyncSession], *, job_id: str) -> dict[str, object]:
    from app.services import document_knowledge as knowledge

    async with factory() as session:
        source, raw, previous_status = await _load_source(session, job_id)
        vector_store = knowledge.require_knowledge_vector_store()
        embeddings = knowledge.OpenAIEmbeddingProvider.from_settings()
        document = KnowledgeDocument(
            document_id=source.id, provider=knowledge.SUPABASE_PROVIDER_ID,
            external_id=raw.external_id, title=source.filename, mime_type=source.content_type,
            scope=KnowledgeScope(customer_id=source.customer_id, case_id=source.id, module=source.module, workspace_id=source.workspace_id),
            metadata={"source_object_id": source.id, "workspace_id": source.workspace_id},
        )
        data, _content_type = await read_stored_bytes(source)
        extracted = await DefaultTextExtractor().extract(data, source.content_type)
        result = await ingest_extracted_source(
            session, extracted=extracted, document=document, source_type="uploaded_file",
            canonical_uri=f"stored-object:{source.id}", content_hash=hashlib.sha256(data).hexdigest(),
            customer_id=source.customer_id, source_object_id=source.id,
            embeddings=embeddings, vector_store=vector_store,
        )
        source.extraction_status = knowledge._extraction_status(result.status)
        source.extracted_text = knowledge._extracted_text(result.extracted)
        raw.version = result.content_hash
        raw.extra = {**dict(raw.extra or {}), "content_hash": result.content_hash, "document_version_id": result.document_version_id}
        if result.status != "indexed":
            source.knowledge_status, source.knowledge_error = result.status, result.message
            await session.commit()
            return _result(source, result, 0)
        if result.reused_version and previous_status == "ready":
            source.knowledge_status = "ready"
            await session.commit()
            return _result(source, result, 0)
        units = [text_unit_from_record(row) for row in await current_text_units(session, source.id)]
        prompts = await require_active_prompts(session, customer_id=source.customer_id, module=source.module, language="sv")
        await session.commit()
        generation = await knowledge.generate_document_knowledge(units=units, prompts=prompts)
        accepted = await asyncio.to_thread(
            knowledge._accepted_generated_items, generation.items, units=units,
            pdf_bytes=data if source.content_type == "application/pdf" else None,
        )
        rows = []
        if generation.successful_batches > 0 or generation.failed_batches == 0:
            await knowledge._archive_generated_items(session, source, mark_manual_stale=not result.reused_version)
            rows = await knowledge._persist_generated_items(session, source=source, items=accepted)
            await session.commit()
            await knowledge._index_generated_items(session, source=source, items=rows)
        source.knowledge_status = "partial" if generation.failed_batches else "ready"
        source.knowledge_error = (
            f"{generation.failed_batches} of {generation.total_batches} document-knowledge batches failed"
            if generation.failed_batches else None
        )
        await session.commit()
        return {
            **_result(source, result, len(rows)),
            "successful_batches": generation.successful_batches,
            "failed_batches": generation.failed_batches,
        }


async def _load_source(session: AsyncSession, job_id: str):
    from app.services import document_knowledge as knowledge

    job = await session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job not found: {job_id}")
    payload = knowledge.DocumentIngestJobRequest.model_validate(job.request or {})
    source = await session.get(StoredObject, payload.object_id)
    if source is None or source.kind != KIND_UNDERLAG or source.customer_id != job.customer_id or source.owner_user_id != payload.owner_user_id:
        raise ValueError("Underlag not found for document ingest")
    previous_status = source.knowledge_status
    source.knowledge_status, source.knowledge_error = "running", None
    raw = await knowledge._upsert_raw_document_record(session, source)
    await session.commit()
    return source, raw, previous_status


def _result(source: StoredObject, result, item_count: int) -> dict[str, object]:
    return {
        "object_id": source.id, "status": source.knowledge_status,
        "chunks_indexed": result.chunks_indexed, "items_created": item_count,
        "document_version_id": result.document_version_id, "reused_version": result.reused_version,
    }
