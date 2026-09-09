"""Knowledge layer: read API plus ingest. Isolated from panel / research-router / MCP."""

from app.services.knowledge.chunking import KnowledgeChunker
from app.services.knowledge.embeddings import EmbeddingProvider, OpenAIEmbeddingProvider
from app.services.knowledge.extractors import (
    DefaultTextExtractor,
    ExtractedBlock,
    ExtractedDocument,
    TextExtractor,
)
from app.services.knowledge.ingest import KnowledgeIngestResult, KnowledgeIngestService
from app.services.knowledge.models import (
    EmbeddedKnowledgeChunk,
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
    "DefaultTextExtractor",
    "EmbeddedKnowledgeChunk",
    "EmbeddingProvider",
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
