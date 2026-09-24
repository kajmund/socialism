"""Knowledge layer: read API plus ingest. Isolated from panel / research-router / MCP."""

from app.services.knowledge.canonical_ingest import ingest_extracted_source
from app.services.knowledge.chunking import KnowledgeChunker, text_unit_to_chunk
from app.services.knowledge.claims import (
    SUPPORTED_BY,
    KnowledgeClaim,
    KnowledgeClaimError,
    persist_knowledge_claim,
    persist_knowledge_claims,
    supporting_text_unit_ids_for_quote,
)
from app.services.knowledge.embeddings import (
    EmbeddingProvider,
    EmbeddingSpec,
    OpenAIEmbeddingProvider,
)
from app.services.knowledge.extractors import (
    DefaultTextExtractor,
    ExtractedBlock,
    ExtractedDocument,
    TextExtractor,
)
from app.services.knowledge.ingest import KnowledgeIngestResult, KnowledgeIngestService
from app.services.knowledge.models import (
    EmbeddedKnowledgeChunk,
    EmbeddedKnowledgeQuery,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeHit,
    KnowledgeQuery,
    KnowledgeScope,
    KnowledgeScopeRequiredError,
)
from app.services.knowledge.persistence import (
    get_canonical_document_by_identity,
    get_current_document_version,
    list_document_versions,
    persist_segmented_document,
)
from app.services.knowledge.provider import (
    SUPABASE_PROVIDER_ID,
    KnowledgeError,
    KnowledgeNotFoundError,
    KnowledgeProvider,
    KnowledgeProviderNotFoundError,
    KnowledgeVectorStoreError,
)
from app.services.knowledge.registry import (
    KnowledgeProviderRegistry,
    build_knowledge_registry,
)
from app.services.knowledge.segmentation import DocumentSegmenter, expand_text_unit_context
from app.services.knowledge.supabase_provider import SupabaseKnowledgeProvider
from app.services.knowledge.units import (
    CanonicalDocument,
    DocumentSection,
    DocumentVersion,
    SegmentedDocument,
    TextUnit,
    make_document_version_id,
    make_section_id,
    make_text_unit_id,
)
from app.services.knowledge.vector_store import (
    KnowledgeVectorStore,
    MemoryKnowledgeVectorStore,
    SupabaseVectorBucketStore,
    TextUnitEmbeddingReader,
    VectorBucketClient,
)

__all__ = [
    "SUPABASE_PROVIDER_ID",
    "SUPPORTED_BY",
    "CanonicalDocument",
    "DefaultTextExtractor",
    "DocumentSection",
    "DocumentSegmenter",
    "DocumentVersion",
    "EmbeddedKnowledgeChunk",
    "EmbeddedKnowledgeQuery",
    "EmbeddingProvider",
    "EmbeddingSpec",
    "ExtractedBlock",
    "ExtractedDocument",
    "KnowledgeChunk",
    "KnowledgeChunker",
    "KnowledgeClaim",
    "KnowledgeClaimError",
    "KnowledgeDocument",
    "KnowledgeError",
    "KnowledgeHit",
    "KnowledgeIngestResult",
    "KnowledgeIngestService",
    "KnowledgeNotFoundError",
    "KnowledgeProvider",
    "KnowledgeProviderNotFoundError",
    "KnowledgeProviderRegistry",
    "KnowledgeQuery",
    "KnowledgeScope",
    "KnowledgeScopeRequiredError",
    "KnowledgeVectorStore",
    "KnowledgeVectorStoreError",
    "MemoryKnowledgeVectorStore",
    "OpenAIEmbeddingProvider",
    "SegmentedDocument",
    "SupabaseKnowledgeProvider",
    "SupabaseVectorBucketStore",
    "TextExtractor",
    "TextUnit",
    "TextUnitEmbeddingReader",
    "VectorBucketClient",
    "build_knowledge_registry",
    "expand_text_unit_context",
    "get_canonical_document_by_identity",
    "get_current_document_version",
    "ingest_extracted_source",
    "list_document_versions",
    "make_document_version_id",
    "make_section_id",
    "make_text_unit_id",
    "persist_knowledge_claim",
    "persist_knowledge_claims",
    "persist_segmented_document",
    "supporting_text_unit_ids_for_quote",
    "text_unit_to_chunk",
]
