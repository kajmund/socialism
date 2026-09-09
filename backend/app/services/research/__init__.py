"""Research layer on top of Knowledge. Isolated from panel / MCP / LLM routing."""

from app.services.research.knowledge_source import (
    KnowledgeResearchSource,
    provenance_from_hit,
    search_scope,
)
from app.services.research.models import (
    RESEARCH_SOURCE_TYPES,
    ResearchContext,
    ResearchError,
    ResearchEvidence,
    ResearchNeed,
    ResearchScopeRequiredError,
    ResearchSourceNotRegisteredError,
    ResearchSourceType,
    make_evidence_id,
    research_evidence,
)
from app.services.research.registry import ResearchSourceRegistry, build_research_registry
from app.services.research.router import ResearchRouter
from app.services.research.source import ResearchSource

__all__ = [
    "RESEARCH_SOURCE_TYPES",
    "KnowledgeResearchSource",
    "ResearchContext",
    "ResearchError",
    "ResearchEvidence",
    "ResearchNeed",
    "ResearchRouter",
    "ResearchScopeRequiredError",
    "ResearchSource",
    "ResearchSourceNotRegisteredError",
    "ResearchSourceRegistry",
    "ResearchSourceType",
    "build_research_registry",
    "make_evidence_id",
    "provenance_from_hit",
    "research_evidence",
    "search_scope",
]
