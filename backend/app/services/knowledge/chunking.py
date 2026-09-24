"""TextUnit-backed chunking. KnowledgeChunk is the vector-store projection."""

from __future__ import annotations

from app.services.knowledge.extractors import ExtractedDocument
from app.services.knowledge.models import KnowledgeChunk, KnowledgeDocument
from app.services.knowledge.scope import SCOPE_CUSTOMER
from app.services.knowledge.segmentation import (
    DEFAULT_MAX_CHARS,
    DEFAULT_TARGET_CHARS,
    DocumentSegmenter,
)
from app.services.knowledge.units import (
    SegmentedDocument,
    TextUnit,
    make_text_unit_id,
)

DEFAULT_OVERLAP_CHARS = 0

make_chunk_id = make_text_unit_id


class KnowledgeChunker:
    """Segment extracted documents into TextUnits, then project to chunks."""

    def __init__(
        self,
        *,
        target_chars: int = DEFAULT_TARGET_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        if overlap_chars < 0:
            raise ValueError("overlap_chars must be >= 0")
        self.target_chars = target_chars
        self.overlap_chars = overlap_chars
        self.max_chars = max_chars
        self._segmenter = DocumentSegmenter(target_chars=target_chars, max_chars=max_chars)

    def segment(
        self,
        extracted: ExtractedDocument,
        document: KnowledgeDocument,
        *,
        content_hash: str | None = None,
        source_type: str | None = None,
        canonical_uri: str | None = None,
        document_version_id: str | None = None,
    ) -> SegmentedDocument:
        return self._segmenter.segment(
            extracted,
            document,
            content_hash=content_hash,
            source_type=source_type,
            canonical_uri=canonical_uri,
            document_version_id=document_version_id,
        )

    def chunk(
        self,
        extracted: ExtractedDocument,
        document: KnowledgeDocument,
        *,
        document_version_id: str | None = None,
    ) -> list[KnowledgeChunk]:
        return [
            text_unit_to_chunk(unit, document)
            for unit in self.segment(
                extracted,
                document,
                document_version_id=document_version_id,
            ).text_units
        ]


def text_unit_to_chunk(unit: TextUnit, document: KnowledgeDocument) -> KnowledgeChunk:
    tenant = document.scope.tenant
    if tenant.scope_type == SCOPE_CUSTOMER and tenant.customer_id is None:
        raise ValueError("text_unit_to_chunk requires document.scope.customer_id")
    metadata: dict[str, object] = {
        "document_id": document.document_id,
        "document_version_id": unit.document_version_id,
        "provider": document.provider,
        "version": document.version,
        "scope_type": tenant.scope_type,
        "scope_key": tenant.scope_key,
        "customer_id": tenant.customer_id,
        "case_id": document.scope.case_id,
        "module": document.scope.module,
        "locator": unit.locator,
        "content_hash": unit.content_hash,
        "text_unit_id": unit.id,
        "section_id": unit.section_id,
        "section_type": unit.metadata.get("section_type"),
        "section_title": unit.metadata.get("section_title"),
        "ordinal": unit.ordinal,
        "page_start": unit.page_start,
        "page_end": unit.page_end,
    }
    return KnowledgeChunk(
        document_id=document.document_id,
        chunk_id=unit.id,
        text=unit.text,
        customer_id=tenant.customer_id,
        scope_type=tenant.scope_type,
        case_id=document.scope.case_id,
        module=document.scope.module,
        title=document.title,
        locator=unit.locator,
        provider=document.provider,
        version=document.version,
        content_hash=unit.content_hash,
        metadata=metadata,
    )
