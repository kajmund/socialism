"""Knowledge layer: read API plus ingest. Isolated from panel / research-router / MCP."""

from app.services.knowledge.chunking import KnowledgeChunker, text_unit_to_chunk
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
from app.services.knowledge.canonical_ingest import ingest_extracted_source
from app.services.knowledge.ingest import KnowledgeIngestResult, KnowledgeIngestService
from app.services.knowledge.persistence import (
    get_canonical_document_by_identity,
    get_current_document_version,
    list_document_versions,
    persist_segmented_document,
)
from app.services.knowledge.segmentation import DocumentSegmenter, expand_text_unit_context
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
from app.services.knowledge.supabase_provider import SupabaseKnowledgeProvider
from app.services.knowledge.vector_store import (
    KnowledgeVectorStore,
    MemoryKnowledgeVectorStore,
    SupabaseVectorBucketStore,
    VectorBucketClient,
)

__all__ = [
    "SUPABASE_PROVIDER_ID",
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
    "SegmentedDocument",
    "TextUnit",
    "expand_text_unit_context",
    "get_canonical_document_by_identity",
    "get_current_document_version",
    "ingest_extracted_source",
    "list_document_versions",
    "make_document_version_id",
    "make_section_id",
    "make_text_unit_id",
    "persist_segmented_document",
    "text_unit_to_chunk",
    "KnowledgeVectorStore",
    "KnowledgeVectorStoreError",
    "MemoryKnowledgeVectorStore",
    "OpenAIEmbeddingProvider",
    "SupabaseKnowledgeProvider",
    "SupabaseVectorBucketStore",
    "TextExtractor",
    "VectorBucketClient",
    "build_knowledge_registry",
]
