"""Standard ResearchRouter composition. API must not implement routing."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge import (
    OpenAIEmbeddingProvider,
    MemoryKnowledgeVectorStore,
    SUPABASE_PROVIDER_ID,
    build_knowledge_registry,
)
from app.services.research.registry import build_research_registry
from app.services.research.router import ResearchRouter

ResearchRouterFactory = Callable[[AsyncSession], ResearchRouter]

_router_factory: ResearchRouterFactory | None = None


def set_research_router_factory(factory: ResearchRouterFactory | None) -> None:
    """Test seam. Production leaves this unset and uses the standard registry."""
    global _router_factory
    _router_factory = factory


def build_standard_research_router(session: AsyncSession) -> ResearchRouter:
    if _router_factory is not None:
        return _router_factory(session)
    registry = build_knowledge_registry(
        session,
        vector_store=MemoryKnowledgeVectorStore(),
        embeddings=OpenAIEmbeddingProvider.from_settings(),
    )
    provider = registry.get(SUPABASE_PROVIDER_ID)
    return ResearchRouter(build_research_registry(provider))
