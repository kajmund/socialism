"""Research layer on top of Knowledge. Isolated from panel / MCP / LLM routing."""

from app.services.research.knowledge_source import (
    KnowledgeResearchSource,
    provenance_from_hit,
    search_scope,
)
from app.services.research.execution import (
    AttemptResearchResult,
    ResearchExecutionError,
    execute_attempt_research,
    research_context_from_run,
)
from app.services.research.models import (
    RESEARCH_SOURCE_TYPES,
    InvalidResearchPlanError,
    ResearchContext,
    ResearchError,
    ResearchEvidence,
    ResearchNeed,
    ResearchPlan,
    ResearchScopeRequiredError,
    ResearchSourceNotRegisteredError,
    ResearchSourceType,
    make_evidence_id,
    research_evidence,
)
from app.services.research.plan import (
    research_plan_from_snapshot,
    research_plan_to_snapshot,
    validate_research_plan,
)
from app.services.research.registry import ResearchSourceRegistry, build_research_registry
from app.services.research.router import ResearchRouter
from app.services.research.source import ResearchSource

__all__ = [
    "RESEARCH_SOURCE_TYPES",
    "AttemptResearchResult",
    "InvalidResearchPlanError",
    "KnowledgeResearchSource",
    "ResearchContext",
    "ResearchError",
    "ResearchEvidence",
    "ResearchExecutionError",
    "ResearchNeed",
    "ResearchPlan",
    "ResearchRouter",
    "ResearchScopeRequiredError",
    "ResearchSource",
    "ResearchSourceNotRegisteredError",
    "ResearchSourceRegistry",
    "ResearchSourceType",
    "build_research_registry",
    "execute_attempt_research",
    "make_evidence_id",
    "provenance_from_hit",
    "research_context_from_run",
    "research_evidence",
    "research_plan_from_snapshot",
    "research_plan_to_snapshot",
    "search_scope",
    "validate_research_plan",
]
