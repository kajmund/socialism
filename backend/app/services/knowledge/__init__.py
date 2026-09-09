"""Read-only knowledge layer. Isolated from panel / research-router / MCP."""

from app.services.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeHit,
    KnowledgeQuery,
    KnowledgeScope,
    KnowledgeScopeRequiredError,
)
from app.services.knowledge.provider import (
    KnowledgeError,
    KnowledgeNotFoundError,
    KnowledgeProvider,
    KnowledgeProviderNotFoundError,
    KnowledgeVectorStoreError,
    SUPABASE_PROVIDER_ID,
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
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeError",
    "KnowledgeHit",
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
    "SupabaseKnowledgeProvider",
    "SupabaseVectorBucketStore",
    "VectorBucketClient",
    "build_knowledge_registry",
]
