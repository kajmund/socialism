"""Standard ResearchRouter composition. API must not implement routing."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.knowledge import (
    SUPABASE_PROVIDER_ID,
    OpenAIEmbeddingProvider,
    build_knowledge_registry,
)
from app.services.knowledge.vector_store import KnowledgeVectorStore
from app.services.research.assessment import ResearchAssessor
from app.services.research.completeness import ResearchCompletenessReviewer
from app.services.research.followup import FollowUpResearchPlanner
from app.services.research.models import ResearchError
from app.services.research.planner import ResearchPlanner
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.question_semantic import SemanticQuestionIdentityMatcher
from app.services.lagen_nu.selection import (
    LagenNuPassageSelector,
    set_passage_selector_factory,
)
from app.services.research.registry import (
    build_research_registry,
    production_registered_source_types,
)
from app.services.research.router import ResearchRouter

ResearchRouterFactory = Callable[[AsyncSession], ResearchRouter]
ResearchAssessorFactory = Callable[[], ResearchAssessor]
FollowUpPlannerFactory = Callable[[], FollowUpResearchPlanner]
ResearchPlannerFactory = Callable[[], ResearchPlanner]
ResearchCompletenessReviewerFactory = Callable[[], ResearchCompletenessReviewer]
KnowledgeVectorStoreFactory = Callable[[], KnowledgeVectorStore]
LagenNuSelectorFactory = Callable[[], LagenNuPassageSelector]

_UNCONFIGURED_VECTOR_STORE = (
    "KnowledgeVectorStore is not configured; "
    "refusing to use an empty in-memory test store"
)

_router_factory: ResearchRouterFactory | None = None
_assessor_factory: ResearchAssessorFactory | None = None
_planner_factory: FollowUpPlannerFactory | None = None
_research_planner_factory: ResearchPlannerFactory | None = None
_completeness_reviewer_factory: ResearchCompletenessReviewerFactory | None = None
_vector_store_factory: KnowledgeVectorStoreFactory | None = None
_lagen_nu_selector_factory: LagenNuSelectorFactory | None = None


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


def set_follow_up_planner_factory(factory: FollowUpPlannerFactory | None) -> None:
    """Test seam for a complete follow-up planner. Production leaves this unset."""
    global _planner_factory
    _planner_factory = factory


def set_research_planner_factory(factory: ResearchPlannerFactory | None) -> None:
    """Test seam for the initial ResearchPlanner. Production leaves this unset."""
    global _research_planner_factory
    _research_planner_factory = factory


def set_completeness_reviewer_factory(
    factory: ResearchCompletenessReviewerFactory | None,
) -> None:
    """Test seam for the global completeness reviewer. Production leaves this unset."""
    global _completeness_reviewer_factory
    _completeness_reviewer_factory = factory


def set_knowledge_vector_store_factory(
    factory: KnowledgeVectorStoreFactory | None,
) -> None:
    """Production seam. Do not pass MemoryKnowledgeVectorStore here."""
    global _vector_store_factory
    _vector_store_factory = factory


def set_lagen_nu_selector_factory(
    factory: LagenNuSelectorFactory | None,
) -> None:
    """Production seam for the lagen.nu structured selector."""
    global _lagen_nu_selector_factory
    _lagen_nu_selector_factory = factory
    set_passage_selector_factory(factory)


def require_knowledge_vector_store() -> KnowledgeVectorStore:
    """Return the configured shared vector store for ingest and research."""
    if _vector_store_factory is None:
        raise ResearchCompositionError(_UNCONFIGURED_VECTOR_STORE)
    return _vector_store_factory()


def require_research_router_ready() -> None:
    """Fail closed if the standard router cannot be built.

    Checks composition seams only. Does not construct a session-bound
    router, embeddings, registry, or provider.
    """
    if _router_factory is not None or _vector_store_factory is not None:
        return
    raise ResearchCompositionError(_UNCONFIGURED_VECTOR_STORE)


def standard_available_source_types() -> tuple[str, ...]:
    """Executable natures for the production ``router_factory`` path.

    Same capability descriptors ``build_standard_research_router`` registers.
    Session-independent: does not construct a router or retrieval adapter.
    """
    return production_registered_source_types()


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
    selector = (
        _lagen_nu_selector_factory() if _lagen_nu_selector_factory is not None else None
    )
    return ResearchRouter(
        build_research_registry(provider, lagen_nu_selector=selector)
    )


def build_standard_question_graph() -> SqlQuestionEvidenceGraph:
    if _vector_store_factory is None:
        return SqlQuestionEvidenceGraph()
    return SqlQuestionEvidenceGraph(
        matcher=SemanticQuestionIdentityMatcher(
            vector_store=_vector_store_factory(),
            embeddings=OpenAIEmbeddingProvider.from_settings(),
            version=settings.research_question_embedding_version,
            threshold=settings.research_question_semantic_match_threshold,
            limit=settings.research_question_semantic_match_limit,
        )
    )


def resolve_research_assessor() -> ResearchAssessor | None:
    """Test-injected assessor, or None so the API can wire the LLM adapter."""
    if _assessor_factory is not None:
        return _assessor_factory()
    return None


def resolve_follow_up_planner() -> FollowUpResearchPlanner | None:
    """Test-injected planner, or None so the API can wire the LLM adapter."""
    if _planner_factory is not None:
        return _planner_factory()
    return None


def resolve_research_planner() -> ResearchPlanner | None:
    """Test-injected initial planner, or None so the API can wire the LLM adapter."""
    if _research_planner_factory is not None:
        return _research_planner_factory()
    return None


def resolve_completeness_reviewer() -> ResearchCompletenessReviewer | None:
    """Test-injected reviewer, or None so the API can wire the LLM adapter."""
    if _completeness_reviewer_factory is not None:
        return _completeness_reviewer_factory()
    return None
