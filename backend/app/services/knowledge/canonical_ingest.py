"""Upload-free ingest: ExtractedDocument → TextUnits → persist → embed.

External document providers call this after they have canonical source
identity and extracted text. This module does not import provider adapters.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CanonicalDocumentRecord
from app.services.knowledge.chunking import KnowledgeChunker, text_unit_to_chunk
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.extractors import ExtractedDocument
from app.services.knowledge.ingest import KnowledgeIngestResult
from app.services.knowledge.models import (
    EmbeddedKnowledgeChunk,
    KnowledgeDocument,
    KnowledgeScope,
)
from app.services.knowledge.persistence import (
    current_text_units,
    get_canonical_document_by_identity,
    get_current_document_version,
    persist_segmented_document,
    text_unit_from_record,
)
from app.services.knowledge.provider import KnowledgeVectorStoreError
from app.services.knowledge.scope import (
    KnowledgeTenantScope,
    require_persist_scope,
    scope_from_row,
)
from app.services.knowledge.units import TextUnit
from app.services.knowledge.vector_store import KnowledgeVectorStore

_MISSING_EMBEDDINGS = "missing ingest embeddings"


async def ingest_extracted_source(
    session: AsyncSession,
    *,
    extracted: ExtractedDocument,
    document: KnowledgeDocument,
    source_type: str,
    canonical_uri: str,
    content_hash: str,
    embeddings: EmbeddingProvider,
    vector_store: KnowledgeVectorStore,
    customer_id: int | None = None,
    scope: KnowledgeTenantScope | None = None,
    source_object_id: str | None = None,
    chunker: KnowledgeChunker | None = None,
) -> KnowledgeIngestResult:
    """Segment, persist, and index TextUnits for any citable source."""
    persist_scope = require_persist_scope(scope=scope, customer_id=customer_id)
    if document.scope.tenant != persist_scope:
        raise ValueError("ingest document scope does not match persist scope")
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
        scope=persist_scope,
        source_type=source_type,
        canonical_uri=canonical_uri,
    )
    resolved_document = document
    if existing is not None:
        resolved_document = replace(document, document_id=existing.id)

    splitter = chunker or KnowledgeChunker()
    segmented = splitter.segment(
        extracted,
        resolved_document,
        content_hash=content_hash,
        source_type=source_type,
        canonical_uri=canonical_uri,
    )
    if not segmented.text_units:
        return KnowledgeIngestResult(
            document_id=resolved_document.document_id,
            status="empty",
            chunks_indexed=0,
            content_hash=content_hash,
            document_version_id=segmented.version.id,
            extracted=extracted,
            segmented=segmented,
        )

    persisted = await persist_segmented_document(
        session,
        scope=persist_scope,
        source_object_id=source_object_id,
        segmented=segmented,
    )
    # Release the row lock and the pool connection before embedding. The
    # research session otherwise holds both until the need finishes, then
    # rolls the insert back when it closes.
    await session.commit()
    if persisted.reused_current:
        # A matching content hash reuses the SQL version. The current vector
        # index can still be empty after an index switch, so write the
        # persisted TextUnits when this index does not already have them.
        units = [
            text_unit_from_record(row)
            for row in await current_text_units(session, resolved_document.document_id)
        ]
        if not units:
            raise RuntimeError(
                f"reused document {resolved_document.document_id} has no current TextUnits"
            )
        if not await _index_has_text_units(
            vector_store,
            document_id=resolved_document.document_id,
            document_version_id=persisted.version.id,
            units=units,
        ):
            await _embed_and_replace(
                embeddings=embeddings,
                vector_store=vector_store,
                document=resolved_document,
                units=units,
            )
        return KnowledgeIngestResult(
            document_id=resolved_document.document_id,
            status="indexed",
            chunks_indexed=len(units),
            content_hash=content_hash,
            document_version_id=persisted.version.id,
            reused_version=True,
            extracted=extracted,
            segmented=segmented,
        )

    await _embed_and_replace(
        embeddings=embeddings,
        vector_store=vector_store,
        document=resolved_document,
        units=segmented.text_units,
    )
    return KnowledgeIngestResult(
        document_id=resolved_document.document_id,
        status="indexed",
        chunks_indexed=len(segmented.text_units),
        content_hash=content_hash,
        document_version_id=persisted.version.id,
        extracted=extracted,
        segmented=segmented,
    )


async def index_missing_persisted_documents(
    session: AsyncSession,
    *,
    embeddings: EmbeddingProvider,
    vector_store: KnowledgeVectorStore,
) -> tuple[int, int]:
    """Write current TextUnits the active vector index does not already store.

    Returns ``(documents_written, documents_already_present)``. Documents with
    no current version are left untouched.
    """
    rows = list((await session.execute(select(CanonicalDocumentRecord))).scalars().all())
    written = 0
    present = 0
    for row in rows:
        version = await get_current_document_version(session, row.id)
        if version is None:
            continue
        units = [text_unit_from_record(unit) for unit in await current_text_units(session, row.id)]
        if not units:
            continue
        tenant = scope_from_row(row)
        document = KnowledgeDocument(
            document_id=row.id,
            provider=row.source_type,
            external_id=row.canonical_uri,
            title=row.title,
            mime_type=version.mime_type,
            scope=KnowledgeScope(
                customer_id=tenant.customer_id,
                scope_type=tenant.scope_type,
            ),
            version=version.version,
            source_type=row.source_type,
            canonical_uri=row.canonical_uri,
        )
        if await _index_has_text_units(
            vector_store,
            document_id=row.id,
            document_version_id=version.id,
            units=units,
        ):
            present += 1
            continue
        await _embed_and_replace(
            embeddings=embeddings,
            vector_store=vector_store,
            document=document,
            units=units,
        )
        written += 1
    return written, present


async def _index_has_text_units(
    vector_store: KnowledgeVectorStore,
    *,
    document_id: str,
    document_version_id: str,
    units: Sequence[TextUnit],
) -> bool:
    try:
        await vector_store.get_text_unit_embeddings(
            document_id=document_id,
            document_version_id=document_version_id,
            text_unit_ids=[unit.id for unit in units],
        )
    except KnowledgeVectorStoreError as exc:
        if not str(exc).startswith(_MISSING_EMBEDDINGS):
            raise
        return False
    return True


async def _embed_and_replace(
    *,
    embeddings: EmbeddingProvider,
    vector_store: KnowledgeVectorStore,
    document: KnowledgeDocument,
    units: Sequence[TextUnit],
) -> None:
    vectors = await embeddings.embed([unit.text for unit in units])
    if len(vectors) != len(units):
        raise RuntimeError(
            f"EmbeddingProvider returned {len(vectors)} vectors for {len(units)} text units"
        )
    chunks = [text_unit_to_chunk(unit, document) for unit in units]
    await vector_store.replace_document_chunks(
        document.document_id,
        [
            EmbeddedKnowledgeChunk(chunk=chunk, embedding=vector)
            for chunk, vector in zip(chunks, vectors, strict=True)
        ],
    )
