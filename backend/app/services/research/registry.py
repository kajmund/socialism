"""KnowledgeProvider capability registry. No LLM selection."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.knowledge.provider import SUPABASE_PROVIDER_ID, KnowledgeProvider
from app.services.research.knowledge_source import KnowledgeResearchSource
from app.services.research.models import ResearchSourceType
from app.services.research.provider import (
    KnowledgeProviderDescriptor,
    NeedConstraints,
    ProviderCandidate,
    RegisteredProvider,
    descriptor_from_source,
    knowledge_adapter_descriptor,
    matches_axis_filters,
    rank_provider_candidates,
)
from app.services.research.source import ResearchSource

_KNOWLEDGE_RESEARCH_ADAPTER = "knowledge_research_source"
_standard_capability_descriptors: tuple[KnowledgeProviderDescriptor, ...] | None = None


def default_standard_capability_descriptors() -> tuple[KnowledgeProviderDescriptor, ...]:
    """Session-independent production capability contract.

    ``build_research_registry`` and planner availability both read this set.
    """
    return (
        knowledge_adapter_descriptor(SUPABASE_PROVIDER_ID, "case_knowledge"),
        knowledge_adapter_descriptor(SUPABASE_PROVIDER_ID, "customer_knowledge"),
    )


def set_standard_capability_descriptors(
    descriptors: Sequence[KnowledgeProviderDescriptor] | None,
) -> None:
    """Test seam for the standard capability definition. Production leaves this unset."""
    global _standard_capability_descriptors
    if descriptors is None:
        _standard_capability_descriptors = None
        return
    _standard_capability_descriptors = tuple(descriptors)


def standard_capability_descriptors() -> tuple[KnowledgeProviderDescriptor, ...]:
    if _standard_capability_descriptors is not None:
        return _standard_capability_descriptors
    return default_standard_capability_descriptors()


def _ordered_evidence_natures(
    descriptor: KnowledgeProviderDescriptor,
) -> tuple[str, ...]:
    return tuple(sorted(descriptor.evidence_natures))


def production_registered_source_types() -> tuple[ResearchSourceType, ...]:
    """Evidence natures the standard production capability registry can execute.

    Derived from the same descriptors ``build_research_registry`` registers.
    Catalog types that are not returned here must not be offered to planners.
    """
    seen: list[ResearchSourceType] = []
    for descriptor in standard_capability_descriptors():
        for nature in _ordered_evidence_natures(descriptor):
            if nature not in seen:
                seen.append(nature)  # type: ignore[arg-type]
    return tuple(seen)


class KnowledgeProviderCapabilityRegistry:
    """Register providers by capability metadata; resolve a bounded candidate set."""

    def __init__(self) -> None:
        self._entries: list[RegisteredProvider] = []

    def register(
        self,
        source: ResearchSource,
        descriptor: KnowledgeProviderDescriptor | None = None,
    ) -> None:
        resolved = descriptor or descriptor_from_source(source)
        self._entries.append(
            RegisteredProvider(
                descriptor=resolved,
                source=source,
                registration_index=len(self._entries),
            )
        )

    def sources_for(self, source_type: ResearchSourceType) -> list[ResearchSource]:
        return [
            entry.source
            for entry in self._entries
            if source_type in entry.descriptor.evidence_natures
            or entry.source.source_type == source_type
        ]

    def registered_types(self) -> list[ResearchSourceType]:
        seen: list[ResearchSourceType] = []
        for entry in self._entries:
            source_type = entry.source.source_type
            if source_type not in seen:
                seen.append(source_type)
        return seen

    def registered_evidence_natures(self) -> tuple[str, ...]:
        """Executable evidence natures. Planner source_types must stay inside this set."""
        seen: list[str] = []
        for entry in self._entries:
            for nature in entry.descriptor.evidence_natures:
                if nature not in seen:
                    seen.append(nature)
        return tuple(seen)

    def registered_providers(self) -> list[RegisteredProvider]:
        return list(self._entries)

    def candidates_for(self, constraints: NeedConstraints) -> list[ProviderCandidate]:
        """Filter + rank. Never substitutes an unrelated provider."""
        if constraints.evidence_natures:
            selected: list[ProviderCandidate] = []
            for nature in constraints.evidence_natures:
                selected.extend(self._candidates_for_nature(nature, constraints))
            return selected
        return self._candidates_without_nature(constraints)

    def _candidates_for_nature(
        self,
        nature: str,
        constraints: NeedConstraints,
    ) -> list[ProviderCandidate]:
        registered = [
            entry
            for entry in self._entries
            if nature in entry.descriptor.evidence_natures
        ]
        if not registered:
            return [
                ProviderCandidate(outcome="unregistered", evidence_nature=nature)
            ]
        matched = [
            entry for entry in registered if matches_axis_filters(entry.descriptor, constraints)
        ]
        if not matched:
            return [
                ProviderCandidate(outcome="unavailable", evidence_nature=nature)
            ]
        return [
            ProviderCandidate(
                outcome="run",
                evidence_nature=nature,
                descriptor=entry.descriptor,
                source=entry.source,
            )
            for entry in rank_provider_candidates(matched, constraints)
        ]

    def _candidates_without_nature(self, constraints: NeedConstraints) -> list[ProviderCandidate]:
        if not constraints.has_axis_filters:
            return []
        matched = [
            entry for entry in self._entries if matches_axis_filters(entry.descriptor, constraints)
        ]
        if not matched:
            return [ProviderCandidate(outcome="unavailable", evidence_nature=None)]
        return [
            ProviderCandidate(
                outcome="run",
                evidence_nature=next(iter(sorted(entry.descriptor.evidence_natures)), None),
                descriptor=entry.descriptor,
                source=entry.source,
            )
            for entry in rank_provider_candidates(matched, constraints)
        ]


ResearchSourceRegistry = KnowledgeProviderCapabilityRegistry


def _compose_standard_source(
    provider: KnowledgeProvider,
    descriptor: KnowledgeProviderDescriptor,
) -> tuple[ResearchSource, KnowledgeProviderDescriptor]:
    adapter = descriptor.access.adapter
    if adapter != _KNOWLEDGE_RESEARCH_ADAPTER:
        raise ValueError(
            f"standard capability {descriptor.provider_id} uses unsupported adapter {adapter!r}"
        )
    natures = _ordered_evidence_natures(descriptor)
    if len(natures) != 1:
        raise ValueError(
            f"standard capability {descriptor.provider_id} must declare exactly one evidence nature"
        )
    nature = natures[0]
    return (
        KnowledgeResearchSource(provider, source_type=nature),  # type: ignore[arg-type]
        knowledge_adapter_descriptor(provider.provider_id, nature),  # type: ignore[arg-type]
    )


def build_research_registry(provider: KnowledgeProvider) -> ResearchSourceRegistry:
    """Knowledge adapters only. domain_knowledge has no global namespace yet."""
    registry = KnowledgeProviderCapabilityRegistry()
    for descriptor in standard_capability_descriptors():
        source, live_descriptor = _compose_standard_source(provider, descriptor)
        registry.register(source, descriptor=live_descriptor)
    return registry
