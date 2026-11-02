"""Upload-free ingest: ExtractedDocument → TextUnits → persist → embed.

External document providers call this after they have canonical source
identity and extracted text. This module does not import provider adapters.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord
from app.services.knowledge.chunking import KnowledgeChunker, text_unit_to_chunk
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.extractors import ExtractedDocument
from app.services.knowledge.ingest import KnowledgeIngestResult
from app.services.knowledge.models import (
    EmbeddedKnowledgeChunk,
    KnowledgeDocument,
    KnowledgeScope,
)
from app.services.knowledge.materialized_document import persisted_segment
from app.services.knowledge.persistence import (
    get_canonical_document_by_identity,
    get_current_document_version,
    persist_segmented_document,
    write_segmented_document_text_units,
)
from app.services.knowledge.provider import KnowledgeVectorStoreError
from app.services.overgraph.owner_runtime import get_owner_runtime
from app.services.overgraph.owner_writer import (
    load_text_units_via_owner,
    write_text_unit_embeddings_via_owner,
)
from app.services.knowledge.scope import (
    KnowledgeTenantScope,
    require_persist_scope,
    scope_from_row,
)
from app.services.knowledge.units import TextUnit
from app.services.knowledge.vector_store import KnowledgeVectorStore
from app.serializers import utcnow

_MISSING_EMBEDDINGS = "missing ingest embeddings"


@dataclass(frozen=True)
class PersistedExtractedSource:
    result: KnowledgeIngestResult
    document: KnowledgeDocument


@dataclass(frozen=True)
class ExtractedSourceIdentity:
    """Where an extracted document comes from and who may read it."""

    source_type: str
    canonical_uri: str
    content_hash: str
    customer_id: int | None = None
    scope: KnowledgeTenantScope | None = None
    source_object_id: str | None = None


async def ingest_extracted_source(  # noqa: PLR0913
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
    persisted = await persist_extracted_source(
        session,
        extracted=extracted,
        document=document,
        identity=ExtractedSourceIdentity(
            source_type=source_type,
            canonical_uri=canonical_uri,
            content_hash=content_hash,
            customer_id=customer_id,
            scope=scope,
            source_object_id=source_object_id,
        ),
        chunker=chunker,
    )
    return await index_persisted_source(
        persisted, embeddings=embeddings, vector_store=vector_store,
    )


async def persist_extracted_source(
    session: AsyncSession,
    *,
    extracted: ExtractedDocument,
    document: KnowledgeDocument,
    identity: ExtractedSourceIdentity,
    chunker: KnowledgeChunker | None = None,
) -> PersistedExtractedSource:
    """Write TextUnits and commit. Does not embed or touch the vector store."""
    persist_scope = require_persist_scope(scope=identity.scope, customer_id=identity.customer_id)
    if document.scope.tenant != persist_scope:
        raise ValueError("ingest document scope does not match persist scope")
    if persist_scope.scope_type == "shared" and identity.source_object_id is not None:
        raise ValueError("Customer-owned stored objects cannot be ingested as global knowledge")
    if extracted.status != "ok" or not any(block.text.strip() for block in extracted.blocks):
        return PersistedExtractedSource(
            KnowledgeIngestResult(
                document_id=document.document_id,
                status="empty" if extracted.status == "ok" else extracted.status,
                chunks_indexed=0,
                content_hash=identity.content_hash,
                message=extracted.message,
                extracted=extracted,
            ),
            document,
        )

    existing = await get_canonical_document_by_identity(
        session,
        scope=persist_scope,
        source_type=identity.source_type,
        canonical_uri=identity.canonical_uri,
    )
    resolved = replace(document, document_id=existing.id) if existing is not None else document
    segmented = (chunker or KnowledgeChunker()).segment(
        extracted,
        resolved,
        content_hash=identity.content_hash,
        source_type=identity.source_type,
        canonical_uri=identity.canonical_uri,
    )
    if not segmented.text_units:
        return PersistedExtractedSource(
            KnowledgeIngestResult(
                document_id=resolved.document_id,
                status="empty",
                chunks_indexed=0,
                content_hash=identity.content_hash,
                document_version_id=segmented.version.id,
                extracted=extracted,
                segmented=segmented,
            ),
            resolved,
        )

    if existing is not None:
        current = await get_current_document_version(session, existing.id)
        if current is not None and current.content_hash == identity.content_hash:
            current_units = await load_text_units_via_owner(
                get_owner_runtime().require_client(),
                document_version_id=current.id,
            )
            if not current_units:
                # A stale SQL version without graph TextUnits cannot be reused.
                # Supersede it so the normal persist path writes a fresh version
                # with its TextUnits instead of raising.
                current.superseded_at = utcnow()
                await session.flush()
    written = await persist_segmented_document(
        session,
        scope=persist_scope,
        source_object_id=identity.source_object_id,
        segmented=segmented,
        materialize_graph=False,
    )
    version_row = written.version
    version_id = version_row.id
    await session.commit()
    if not written.reused_current:
        await write_segmented_document_text_units(segmented, persist_scope)
    segmented = await persisted_segment(session, segmented, version_row)
    units = list(segmented.text_units)
    if written.reused_current and not units:
        raise RuntimeError(f"reused document {resolved.document_id} has no current TextUnits")
    return PersistedExtractedSource(
        KnowledgeIngestResult(
            document_id=resolved.document_id,
            status="indexed",
            chunks_indexed=len(units),
            content_hash=identity.content_hash,
            document_version_id=version_id,
            reused_version=written.reused_current,
            extracted=extracted,
            segmented=segmented,
        ),
        resolved,
    )


async def index_persisted_source(
    persisted: PersistedExtractedSource,
    *,
    embeddings: EmbeddingProvider,
    vector_store: KnowledgeVectorStore,
) -> KnowledgeIngestResult:
    """Embed persisted TextUnits. Upsert only; never scan or replace the index."""
    result = persisted.result
    if result.status != "indexed" or result.segmented is None:
        return result
    units = list(result.segmented.text_units)
    if not units:
        return result
    if result.reused_version and await _index_has_text_units(
        vector_store,
        document_id=persisted.document.document_id,
        document_version_id=result.document_version_id or "",
        units=units,
    ):
        return result
    await _embed_and_upsert(
        embeddings=embeddings,
        vector_store=vector_store,
        document=persisted.document,
        units=units,
    )
    return result


async def embed_persisted_document(
    session: AsyncSession,
    *,
    document_id: str,
    embeddings: EmbeddingProvider,
    vector_store: KnowledgeVectorStore,
) -> None:
    """Embed one persisted document. Session must not be in a transaction."""
    if session.in_transaction():
        raise RuntimeError("Document embed requires a session without an active transaction")
    try:
        inputs = await _current_index_inputs(session, document_id=document_id)
    finally:
        await session.rollback()
    for document, units in inputs:
        await _embed_and_upsert(
            embeddings=embeddings,
            vector_store=vector_store,
            document=document,
            units=units,
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
    if session.in_transaction():
        raise RuntimeError("Index repair requires a session without an active transaction")
    try:
        inputs = await _current_index_inputs(session)
    finally:
        await session.rollback()
    written = 0
    present = 0
    for document, units in inputs:
        if await _index_has_text_units(
            vector_store,
            document_id=document.document_id,
            document_version_id=units[0].document_version_id,
            units=units,
        ):
            present += 1
            continue
        await _embed_and_upsert(
            embeddings=embeddings,
            vector_store=vector_store,
            document=document,
            units=units,
        )
        written += 1
    return written, present


async def _current_index_inputs(
    session: AsyncSession,
    document_id: str | None = None,
) -> list[tuple[KnowledgeDocument, list[TextUnit]]]:
    statement = select(CanonicalDocumentRecord)
    if document_id is not None:
        statement = statement.where(CanonicalDocumentRecord.id == document_id)
    rows = list(await session.scalars(statement))
    versions = []
    for row in rows:
        version = await get_current_document_version(session, row.id)
        if version is not None:
            versions.append((_knowledge_document_for_index(row, version), version.id))
    client = get_owner_runtime().require_client()
    inputs = []
    for document, version_id in versions:
        units = await load_text_units_via_owner(client, document_version_id=version_id)
        if not units:
            continue
        inputs.append((document, units))
    await session.rollback()
    return inputs


def _knowledge_document_for_index(
    row: CanonicalDocumentRecord,
    version: DocumentVersionRecord,
) -> KnowledgeDocument:
    extra = dict(row.extra or {})
    tenant = scope_from_row(row)
    provider = extra.get("provider")
    return KnowledgeDocument(
        document_id=row.id,
        provider=str(provider).strip() if isinstance(provider, str) and provider.strip() else row.source_type,
        external_id=str(extra.get("external_id") or row.canonical_uri),
        title=row.title,
        mime_type=version.mime_type,
        scope=KnowledgeScope(
            customer_id=tenant.customer_id,
            scope_type=tenant.scope_type,
            case_id=_optional_str(extra.get("case_id")) or row.source_object_id,
            module=_optional_str(extra.get("module")),
            workspace_id=_optional_str(extra.get("workspace_id")),
        ),
        version=version.version,
        source_type=row.source_type,
        canonical_uri=row.canonical_uri,
        metadata=extra,
    )


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


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


async def _embed_and_upsert(
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
    # TextUnit IDs belong to a temporal occurrence. Keep earlier projections
    # addressable by their frozen source IDs; no document-wide scan or delete.
    await vector_store.upsert_chunks(
        [
            EmbeddedKnowledgeChunk(chunk=chunk, embedding=vector)
            for chunk, vector in zip(chunks, vectors, strict=True)
        ],
    )
    # The authoritative TextUnit vector also goes through the single writer.
    owner = get_owner_runtime().require_client()
    await write_text_unit_embeddings_via_owner(owner, list(units), list(vectors))
