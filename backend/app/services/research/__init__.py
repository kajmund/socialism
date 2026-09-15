"""Research layer on top of Knowledge. Isolated from panel / MCP / LLM routing.

Orchestration symbols in ``execution`` are loaded lazily so
``app.services.execution`` can finish importing. Eagerly importing
``research.execution`` from this package init created a circular ImportError.
"""

from typing import TYPE_CHECKING

from app.services.research.knowledge_source import (
    KnowledgeResearchSource,
    provenance_from_hit,
    search_scope,
)
from app.services.research.models import (
    RESEARCH_SOURCE_TYPES,
    InvalidResearchPlanError,
    ResearchCapabilityUnavailableError,
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
from app.services.research.planner import (
    FakeResearchPlanner,
    InvalidResearchObjectiveError,
    ResearchNeedDraft,
    ResearchObjective,
    ResearchPlannerError,
    plan_from_planner_drafts,
    research_objective_from_snapshot,
    research_objective_to_snapshot,
    require_research_objective,
)
from app.services.research.provider import (
    KnowledgeProviderDescriptor,
    NeedConstraints,
    ProviderAccess,
    constraints_from_need,
    knowledge_adapter_descriptor,
    rank_provider_candidates,
)
from app.services.research.registry import (
    KnowledgeProviderCapabilityRegistry,
    ResearchSourceRegistry,
    build_research_registry,
    production_registered_source_types,
)
from app.services.research.router import ResearchRouter
from app.services.research.source import ResearchSource

if TYPE_CHECKING:
    from app.services.research.execution import (
        AttemptResearchResult,
        ResearchExecutionError,
        execute_attempt_research,
        research_context_from_run,
    )

_LAZY_EXECUTION = frozenset(
    {
        "AttemptResearchResult",
        "ResearchExecutionError",
        "execute_attempt_research",
        "research_context_from_run",
    }
)

__all__ = [
    "RESEARCH_SOURCE_TYPES",
    "AttemptResearchResult",
    "FakeResearchPlanner",
    "InvalidResearchObjectiveError",
    "InvalidResearchPlanError",
    "KnowledgeProviderCapabilityRegistry",
    "KnowledgeProviderDescriptor",
    "ResearchNeedDraft",
    "ResearchObjective",
    "ResearchPlannerError",
    "KnowledgeResearchSource",
    "NeedConstraints",
    "ProviderAccess",
    "ResearchCapabilityUnavailableError",
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
    "constraints_from_need",
    "execute_attempt_research",
    "knowledge_adapter_descriptor",
    "production_registered_source_types",
    "make_evidence_id",
    "plan_from_planner_drafts",
    "provenance_from_hit",
    "rank_provider_candidates",
    "require_research_objective",
    "research_context_from_run",
    "research_evidence",
    "research_objective_from_snapshot",
    "research_objective_to_snapshot",
    "research_plan_from_snapshot",
    "research_plan_to_snapshot",
    "search_scope",
    "validate_research_plan",
]


def __getattr__(name: str):
    if name in _LAZY_EXECUTION:
        from app.services.research import execution as _execution

        return getattr(_execution, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
