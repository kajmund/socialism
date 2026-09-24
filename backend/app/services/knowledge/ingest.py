"""Index an existing KnowledgeDocument: fetch → extract → chunk → embed → upsert."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from app.services.knowledge.chunking import KnowledgeChunker, text_unit_to_chunk
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.extractors import DefaultTextExtractor, ExtractedDocument, TextExtractor
from app.services.knowledge.models import EmbeddedKnowledgeChunk, KnowledgeScope, require_scope
from app.services.knowledge.provider import KnowledgeNotFoundError, KnowledgeProvider
from app.services.knowledge.units import SegmentedDocument
from app.services.knowledge.vector_store import KnowledgeVectorStore

IngestStatus = Literal["indexed", "empty", "unsupported", "needs_ocr", "failed"]


@dataclass(frozen=True)
class KnowledgeIngestResult:
    document_id: str
    status: IngestStatus
    chunks_indexed: int
    content_hash: str | None = None
    message: str | None = None
    extracted: ExtractedDocument | None = None
    segmented: SegmentedDocument | None = None


class KnowledgeIngestService:
    """Build a searchable representation for a document already in KnowledgeProvider."""

    def __init__(
        self,
        *,
        provider: KnowledgeProvider,
        vector_store: KnowledgeVectorStore,
        embeddings: EmbeddingProvider,
        extractor: TextExtractor | None = None,
        chunker: KnowledgeChunker | None = None,
    ) -> None:
        self._provider = provider
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._extractor = extractor or DefaultTextExtractor()
        self._chunker = chunker or KnowledgeChunker()

    async def ingest_document(
        self,
        *,
        document_id: str,
        scope: KnowledgeScope,
    ) -> KnowledgeIngestResult:
        require_scope(scope)
        document = await self._provider.get_document(document_id, scope)
        if document is None:
            raise KnowledgeNotFoundError(document_id)

        content = await self._provider.fetch_content(document_id, scope)
        content_hash = hashlib.sha256(content).hexdigest()

        extracted = await self._extractor.extract(content, document.mime_type)
        outcome = _extraction_outcome(extracted)
        if outcome is not None:
            return _result(
                document_id,
                outcome,
                content_hash,
                message=extracted.message,
                extracted=extracted,
            )

        segmented = self._chunker.segment(extracted, document, content_hash=content_hash)
        chunks = [text_unit_to_chunk(unit, document) for unit in segmented.text_units]
        if not chunks:
            return _result(
                document_id,
                "empty",
                content_hash,
                extracted=extracted,
                segmented=segmented,
            )

        try:
            vectors = await self._embeddings.embed([unit.text for unit in segmented.text_units])
        except Exception as exc:  # noqa: BLE001 — keep the previous index searchable
            return _result(
                document_id,
                "failed",
                content_hash,
                message=str(exc),
                extracted=extracted,
                segmented=segmented,
            )

        if len(vectors) != len(chunks):
            return _result(
                document_id,
                "failed",
                content_hash,
                message=(
                    f"EmbeddingProvider returned {len(vectors)} vectors for {len(chunks)} chunks"
                ),
                extracted=extracted,
                segmented=segmented,
            )

        embedded = [
            EmbeddedKnowledgeChunk(chunk=chunk, embedding=vector)
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await self._vector_store.replace_document_chunks(document_id, embedded)
        return KnowledgeIngestResult(
            document_id=document_id,
            status="indexed",
            chunks_indexed=len(embedded),
            content_hash=content_hash,
            extracted=extracted,
            segmented=segmented,
        )


def _extraction_outcome(extracted: ExtractedDocument) -> IngestStatus | None:
    if extracted.status in {"unsupported", "needs_ocr", "failed", "empty"}:
        return extracted.status
    if not any(block.text.strip() for block in extracted.blocks):
        return "empty"
    return None


def _result(
    document_id: str,
    status: IngestStatus,
    content_hash: str | None,
    *,
    message: str | None = None,
    extracted: ExtractedDocument | None = None,
    segmented: SegmentedDocument | None = None,
) -> KnowledgeIngestResult:
    return KnowledgeIngestResult(
        document_id=document_id,
        status=status,
        chunks_indexed=0,
        content_hash=content_hash,
        message=message,
        extracted=extracted,
        segmented=segmented,
    )
