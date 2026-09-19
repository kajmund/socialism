"""KnowledgeProvider capability descriptors and deterministic candidate ranking.

Access mechanisms (MCP, API, vector store, dataset) are metadata, not
top-level architecture types. v1 ranking is programmatic; embeddings are
a later seam, not a current dependency.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.services.research.models import ResearchNeed, ResearchSourceType
from app.services.research.source import ResearchSource


@dataclass(frozen=True)
class ProviderAccess:
    """How a provider is reached. Not a routing taxonomy."""

    mechanism: str
    adapter: str | None = None


@dataclass(frozen=True)
class KnowledgeProviderDescriptor:
    """Stable registration contract for deterministic filter/rank."""

    provider_id: str
    domains: frozenset[str] = field(default_factory=frozenset)
    modalities: frozenset[str] = field(default_factory=frozenset)
    capabilities: frozenset[str] = field(default_factory=frozenset)
    evidence_natures: frozenset[str] = field(default_factory=frozenset)
    authority: dict[str, object] = field(default_factory=dict)
    access: ProviderAccess = field(default_factory=lambda: ProviderAccess(mechanism="adapter"))
    rank: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", self.provider_id.strip())
        object.__setattr__(self, "domains", _frozen_tokens(self.domains))
        object.__setattr__(self, "modalities", _frozen_tokens(self.modalities))
        object.__setattr__(self, "capabilities", _frozen_tokens(self.capabilities))
        object.__setattr__(self, "evidence_natures", _frozen_tokens(self.evidence_natures))
        object.__setattr__(self, "authority", dict(self.authority))
        if not self.provider_id:
            raise ValueError("KnowledgeProviderDescriptor.provider_id is required")


@dataclass(frozen=True)
class NeedConstraints:
    """Declared routing constraints derived from a ResearchNeed."""

    evidence_natures: tuple[str, ...] = ()
    domains: frozenset[str] = field(default_factory=frozenset)
    modalities: frozenset[str] = field(default_factory=frozenset)
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_natures",
            tuple(token for token in (_token(item) for item in self.evidence_natures) if token),
        )
        object.__setattr__(self, "domains", _frozen_tokens(self.domains))
        object.__setattr__(self, "modalities", _frozen_tokens(self.modalities))
        object.__setattr__(self, "capabilities", _frozen_tokens(self.capabilities))

    @property
    def has_axis_filters(self) -> bool:
        return bool(self.domains or self.modalities or self.capabilities)


@dataclass(frozen=True)
class RegisteredProvider:
    descriptor: KnowledgeProviderDescriptor
    source: ResearchSource
    registration_index: int


CandidateOutcome = Literal["run", "unregistered", "unavailable"]


@dataclass(frozen=True)
class ProviderCandidate:
    outcome: CandidateOutcome
    evidence_nature: str | None
    descriptor: KnowledgeProviderDescriptor | None = None
    source: ResearchSource | None = None


def _token(value: object) -> str:
    return str(value).strip()


def _frozen_tokens(values: object) -> frozenset[str]:
    if values is None:
        return frozenset()
    if isinstance(values, str):
        token = values.strip()
        return frozenset({token} if token else ())
    return frozenset(token for token in (_token(item) for item in values) if token)


def constraints_from_need(need: ResearchNeed) -> NeedConstraints:
    """v1: ``source_types`` are evidence natures. Extra axes are optional."""
    return NeedConstraints(
        evidence_natures=tuple(str(item) for item in need.source_types),
        domains=_frozen_tokens(getattr(need, "domains", ())),
        modalities=_frozen_tokens(getattr(need, "modalities", ())),
        capabilities=_frozen_tokens(getattr(need, "capabilities", ())),
    )


def descriptor_from_source(source: ResearchSource) -> KnowledgeProviderDescriptor:
    """Compat descriptor when a caller registers a ResearchSource only."""
    source_type = source.source_type
    raw_id = getattr(source, "provider_id", None)
    retrieval_id = raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else source_type
    return KnowledgeProviderDescriptor(
        provider_id=f"{retrieval_id}.{source_type}",
        evidence_natures=frozenset({source_type}),
        authority={"retrieval_provider": retrieval_id},
        access=ProviderAccess(mechanism="adapter"),
    )


def descriptor_requires_case(descriptor: KnowledgeProviderDescriptor) -> bool:
    return bool(descriptor.authority.get("requires_case"))


def filter_source_types_for_scope(
    source_types: Sequence[str],
    *,
    case_id: str | None,
    descriptors: Sequence[KnowledgeProviderDescriptor] | None = None,
) -> tuple[str, ...]:
    """Drop case-scoped natures when the Run has no case_id.

    Those providers are registered but not executable in this scope.
    """
    if case_id:
        return tuple(source_types)
    case_natures = {"case_knowledge"}
    if descriptors:
        case_natures.update(
            nature
            for descriptor in descriptors
            if descriptor_requires_case(descriptor)
            for nature in descriptor.evidence_natures
        )
    return tuple(item for item in source_types if item not in case_natures)


def knowledge_adapter_descriptor(
    retrieval_provider_id: str,
    source_type: ResearchSourceType,
) -> KnowledgeProviderDescriptor:
    return KnowledgeProviderDescriptor(
        provider_id=f"{retrieval_provider_id}.{source_type}",
        domains=frozenset({"tenant"}),
        modalities=frozenset({"text"}),
        capabilities=frozenset({"search"}),
        evidence_natures=frozenset({source_type}),
        authority={
            "tenant_bound": True,
            "requires_case": source_type == "case_knowledge",
            "retrieval_provider": retrieval_provider_id,
        },
        access=ProviderAccess(mechanism="adapter", adapter="knowledge_research_source"),
        rank=0 if source_type == "case_knowledge" else 1,
    )


def matches_axis_filters(descriptor: KnowledgeProviderDescriptor, constraints: NeedConstraints) -> bool:
    return (
        _intersects_if_required(descriptor.domains, constraints.domains)
        and _intersects_if_required(descriptor.modalities, constraints.modalities)
        and _intersects_if_required(descriptor.capabilities, constraints.capabilities)
    )


def _intersects_if_required(declared: frozenset[str], required: frozenset[str]) -> bool:
    if not required:
        return True
    return bool(declared & required)


def rank_provider_candidates(
    candidates: Sequence[RegisteredProvider],
    constraints: NeedConstraints,
) -> list[RegisteredProvider]:
    """Deterministic v1 order. Semantic re-ranking can wrap this later."""
    _ = constraints
    return sorted(
        candidates,
        key=lambda item: (item.descriptor.rank, item.descriptor.provider_id, item.registration_index),
    )
