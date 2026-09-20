"""Research layer on top of Knowledge. Isolated from panel / MCP / LLM routing.

Orchestration symbols in ``execution`` are loaded lazily so
``app.services.execution`` can finish importing. Eagerly importing
``research.execution`` from this package init created a circular ImportError.
"""

from importlib import import_module
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
    require_research_objective,
    research_objective_from_snapshot,
    research_objective_to_snapshot,
)
from app.services.research.provider import (
    KnowledgeProviderDescriptor,
    NeedConstraints,
    ProviderAccess,
    constraints_from_need,
    knowledge_adapter_descriptor,
    rank_provider_candidates,
)
from app.services.research.source import ResearchSource

if TYPE_CHECKING:
    from app.services.research.execution import (
        AttemptResearchResult,
        ResearchExecutionError,
        execute_attempt_research,
        research_context_from_run,
    )
    from app.services.research.registry import (
        KnowledgeProviderCapabilityRegistry,
        ResearchSourceRegistry,
        build_research_registry,
        production_registered_source_types,
    )
    from app.services.research.router import ResearchRouter

_LAZY_MODULE_BY_NAME = {
    "AttemptResearchResult": "app.services.research.execution",
    "ResearchExecutionError": "app.services.research.execution",
    "execute_attempt_research": "app.services.research.execution",
    "research_context_from_run": "app.services.research.execution",
    "KnowledgeProviderCapabilityRegistry": "app.services.research.registry",
    "ResearchSourceRegistry": "app.services.research.registry",
    "build_research_registry": "app.services.research.registry",
    "production_registered_source_types": "app.services.research.registry",
    "ResearchRouter": "app.services.research.router",
}

__all__ = [
    "RESEARCH_SOURCE_TYPES",
    "AttemptResearchResult",
    "FakeResearchPlanner",
    "InvalidResearchObjectiveError",
    "InvalidResearchPlanError",
    "KnowledgeProviderCapabilityRegistry",
    "KnowledgeProviderDescriptor",
    "KnowledgeResearchSource",
    "NeedConstraints",
    "ProviderAccess",
    "ResearchCapabilityUnavailableError",
    "ResearchContext",
    "ResearchError",
    "ResearchEvidence",
    "ResearchExecutionError",
    "ResearchNeed",
    "ResearchNeedDraft",
    "ResearchObjective",
    "ResearchPlan",
    "ResearchPlannerError",
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
    "make_evidence_id",
    "plan_from_planner_drafts",
    "production_registered_source_types",
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
    module_name = _LAZY_MODULE_BY_NAME.get(name)
    if module_name is not None:
        return getattr(import_module(module_name), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
