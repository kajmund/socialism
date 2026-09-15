"""Standard ResearchRouter composition. API must not implement routing."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge import (
    SUPABASE_PROVIDER_ID,
    OpenAIEmbeddingProvider,
    build_knowledge_registry,
)
from app.services.knowledge.vector_store import KnowledgeVectorStore
from app.services.research.assessment import ResearchAssessor
from app.services.research.assessment_llm import build_llm_research_assessor
from app.services.research.models import ResearchError
from app.services.research.registry import build_research_registry
from app.services.research.router import ResearchRouter

ResearchRouterFactory = Callable[[AsyncSession], ResearchRouter]
ResearchAssessorFactory = Callable[[], ResearchAssessor]
KnowledgeVectorStoreFactory = Callable[[], KnowledgeVectorStore]

_UNCONFIGURED_VECTOR_STORE = (
    "KnowledgeVectorStore is not configured; "
    "refusing to use an empty in-memory test store"
)

_router_factory: ResearchRouterFactory | None = None
_assessor_factory: ResearchAssessorFactory | None = None
_vector_store_factory: KnowledgeVectorStoreFactory | None = None


class ResearchCompositionError(ResearchError):
    """ResearchRouter cannot be built without a configured KnowledgeVectorStore."""


def set_research_router_factory(factory: ResearchRouterFactory | None) -> None:
    """Test seam for a complete router. Production leaves this unset."""
    global _router_factory
    _router_factory = factory


def set_research_assessor_factory(factory: ResearchAssessorFactory | None) -> None:
    """Test seam for a complete assessor. Production leaves this unset."""
    global _assessor_factory
    _assessor_factory = factory


def set_knowledge_vector_store_factory(
    factory: KnowledgeVectorStoreFactory | None,
) -> None:
    """Production seam. Do not pass MemoryKnowledgeVectorStore here."""
    global _vector_store_factory
    _vector_store_factory = factory


def require_research_router_ready() -> None:
    """Fail closed if the standard router cannot be built.

    Checks composition seams only. Does not construct a session-bound
    router, embeddings, registry, or provider.
    """
    if _router_factory is not None or _vector_store_factory is not None:
        return
    raise ResearchCompositionError(_UNCONFIGURED_VECTOR_STORE)


def build_standard_research_router(session: AsyncSession) -> ResearchRouter:
    if _router_factory is not None:
        return _router_factory(session)
    if _vector_store_factory is None:
        raise ResearchCompositionError(_UNCONFIGURED_VECTOR_STORE)
    registry = build_knowledge_registry(
        session,
        vector_store=_vector_store_factory(),
        embeddings=OpenAIEmbeddingProvider.from_settings(),
    )
    provider = registry.get(SUPABASE_PROVIDER_ID)
    return ResearchRouter(build_research_registry(provider))


async def build_standard_research_assessor(
    session: AsyncSession,
    *,
    customer_id: int,
    module: str,
) -> ResearchAssessor:
    if _assessor_factory is not None:
        return _assessor_factory()
    return await build_llm_research_assessor(
        session, customer_id=customer_id, module=module
    )
