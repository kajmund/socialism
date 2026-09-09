"""Register research sources per logical source_type. No LLM selection."""

from __future__ import annotations

from app.services.knowledge.provider import KnowledgeProvider
from app.services.research.knowledge_source import KnowledgeResearchSource
from app.services.research.models import ResearchSourceType
from app.services.research.source import ResearchSource

_IMPLEMENTED_KNOWLEDGE_TYPES: tuple[ResearchSourceType, ...] = (
    "case_knowledge",
    "customer_knowledge",
)


class ResearchSourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[ResearchSourceType, list[ResearchSource]] = {}

    def register(self, source: ResearchSource) -> None:
        self._sources.setdefault(source.source_type, []).append(source)

    def sources_for(self, source_type: ResearchSourceType) -> list[ResearchSource]:
        return list(self._sources.get(source_type, ()))

    def registered_types(self) -> list[ResearchSourceType]:
        return [source_type for source_type, sources in self._sources.items() if sources]


def build_research_registry(provider: KnowledgeProvider) -> ResearchSourceRegistry:
    """Knowledge adapters only. domain_knowledge has no global namespace yet."""
    registry = ResearchSourceRegistry()
    for source_type in _IMPLEMENTED_KNOWLEDGE_TYPES:
        registry.register(KnowledgeResearchSource(provider, source_type=source_type))
    return registry
