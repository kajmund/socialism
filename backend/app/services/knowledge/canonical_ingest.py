"""Upload-free ingest: ExtractedDocument → TextUnits → persist → embed.

External document providers call this after they have canonical source
identity and extracted text. This module does not import provider adapters.
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.chunking import KnowledgeChunker, text_unit_to_chunk
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.extractors import ExtractedDocument
from app.services.knowledge.ingest import KnowledgeIngestResult
from app.services.knowledge.models import EmbeddedKnowledgeChunk, KnowledgeDocument
from app.services.knowledge.persistence import (
    get_canonical_document_by_identity,
    persist_segmented_document,
)
from app.services.knowledge.vector_store import KnowledgeVectorStore


async def ingest_extracted_source(
    session: AsyncSession,
    *,
    customer_id: int,
    extracted: ExtractedDocument,
    document: KnowledgeDocument,
    source_type: str,
    canonical_uri: str,
    content_hash: str,
    embeddings: EmbeddingProvider,
    vector_store: KnowledgeVectorStore,
    source_object_id: str | None = None,
    chunker: KnowledgeChunker | None = None,
) -> KnowledgeIngestResult:
    """Segment, persist, and index TextUnits for any citable source."""
    if extracted.status != "ok" or not any(block.text.strip() for block in extracted.blocks):
        return KnowledgeIngestResult(
            document_id=document.document_id,
            status="empty" if extracted.status == "ok" else extracted.status,
            chunks_indexed=0,
            content_hash=content_hash,
            message=extracted.message,
            extracted=extracted,
        )

    existing = await get_canonical_document_by_identity(
        session,
        customer_id=customer_id,
        source_type=source_type,
        canonical_uri=canonical_uri,
    )
    resolved = document
    if existing is not None:
        resolved = replace(document, document_id=existing.id)

    splitter = chunker or KnowledgeChunker()
    segmented = splitter.segment(
        extracted,
        resolved,
        content_hash=content_hash,
        source_type=source_type,
        canonical_uri=canonical_uri,
    )
    if not segmented.text_units:
        return KnowledgeIngestResult(
            document_id=resolved.document_id,
            status="empty",
            chunks_indexed=0,
            content_hash=content_hash,
            document_version_id=segmented.version.id,
            extracted=extracted,
            segmented=segmented,
        )

    persisted = await persist_segmented_document(
        session,
        customer_id=customer_id,
        source_object_id=source_object_id,
        segmented=segmented,
    )
    if persisted.reused_current:
        return KnowledgeIngestResult(
            document_id=resolved.document_id,
            status="indexed",
            chunks_indexed=len(segmented.text_units),
            content_hash=content_hash,
            document_version_id=persisted.version.id,
            reused_version=True,
            extracted=extracted,
            segmented=segmented,
        )

    vectors = await embeddings.embed([unit.text for unit in segmented.text_units])
    if len(vectors) != len(segmented.text_units):
        raise RuntimeError(
            f"EmbeddingProvider returned {len(vectors)} vectors for "
            f"{len(segmented.text_units)} text units"
        )
    chunks = [text_unit_to_chunk(unit, resolved) for unit in segmented.text_units]
    await vector_store.replace_document_chunks(
        resolved.document_id,
        [
            EmbeddedKnowledgeChunk(chunk=chunk, embedding=vector)
            for chunk, vector in zip(chunks, vectors, strict=True)
        ],
    )
    return KnowledgeIngestResult(
        document_id=resolved.document_id,
        status="indexed",
        chunks_indexed=len(chunks),
        content_hash=content_hash,
        document_version_id=persisted.version.id,
        extracted=extracted,
        segmented=segmented,
    )
