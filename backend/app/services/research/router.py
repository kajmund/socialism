"""Deterministic ResearchNeed → provider candidates → ResearchEvidence[].

Routing is metadata filtering + stable rank. No LLM, no early-exit on hits,
no silent fallback to unrelated providers.
"""

from __future__ import annotations

import logging

from app.services.lagen_nu.selection import LagenNuSelectionError
from app.services.research.models import (
    ResearchCapabilityUnavailableError,
    ResearchContext,
    ResearchEvidence,
    ResearchNeed,
    ResearchScopeRequiredError,
    ResearchSourceNotRegisteredError,
    research_evidence,
)
from app.services.research.provider import (
    KnowledgeProviderDescriptor,
    ProviderCandidate,
    constraints_from_need,
    descriptor_requires_case,
)
from app.services.research.registry import KnowledgeProviderCapabilityRegistry
from app.services.research.source import ResearchSource

logger = logging.getLogger(__name__)


def _safe_error_metadata(source_type: str | None, exc: BaseException) -> dict[str, object]:
    metadata: dict[str, object] = {"error_type": type(exc).__name__}
    if source_type is not None:
        metadata["source_type"] = source_type
    return metadata


def _safe_error_message(exc: BaseException) -> str:
    if isinstance(
        exc,
        (
            ResearchScopeRequiredError,
            ResearchSourceNotRegisteredError,
            ResearchCapabilityUnavailableError,
            LagenNuSelectionError,
        ),
    ):
        if isinstance(exc, LagenNuSelectionError):
            return f"{type(exc).__name__}: {_selection_error_text(exc)}"
        return str(exc)
    return f"{type(exc).__name__}: research source failed"


def _selection_error_text(exc: LagenNuSelectionError) -> str:
    parts = [str(exc).strip() or type(exc).__name__]
    cause = exc.__cause__
    if cause is not None:
        detail = str(cause).strip() or type(cause).__name__
        if detail not in parts[0]:
            parts.append(detail)
    return ": ".join(parts)


def _evidence_source_type(need: ResearchNeed, candidate: ProviderCandidate) -> str:
    if candidate.evidence_nature:
        return candidate.evidence_nature
    if candidate.source is not None:
        return candidate.source.source_type
    if need.source_types:
        return need.source_types[0]
    return "unavailable"


def _error_evidence(
    need: ResearchNeed,
    source_type: str,
    exc: BaseException,
    *,
    provider: str | None = None,
) -> ResearchEvidence:
    return research_evidence(
        research_need_id=need.id,
        source_type=source_type,
        status="error",
        provider=provider,
        excerpt=_safe_error_message(exc),
        metadata=_safe_error_metadata(source_type, exc),
    )


def _not_found_evidence(
    need: ResearchNeed,
    source_type: str,
    *,
    provider: str | None = None,
    excerpt: str | None = None,
    metadata: dict[str, object] | None = None,
) -> ResearchEvidence:
    return research_evidence(
        research_need_id=need.id,
        source_type=source_type,
        status="not_found",
        provider=provider,
        excerpt=excerpt,
        metadata=metadata or {},
    )


def _source_provider(source: ResearchSource | None) -> str | None:
    if source is None:
        return None
    provider = getattr(source, "provider_id", None)
    if isinstance(provider, str) and provider.strip():
        return provider
    return None


def _registered_provider(
    source: ResearchSource | None,
    descriptor: KnowledgeProviderDescriptor | None,
) -> str | None:
    """Prefer the adapter id; fall back to the stable registry descriptor."""
    return _source_provider(source) or (descriptor.provider_id if descriptor else None)


def _unavailable_detail(need: ResearchNeed, nature: str | None) -> str:
    constraints = constraints_from_need(need)
    parts = []
    if nature:
        parts.append(f"evidence_nature={nature}")
    if constraints.domains:
        parts.append("domains=" + ",".join(sorted(constraints.domains)))
    if constraints.modalities:
        parts.append("modalities=" + ",".join(sorted(constraints.modalities)))
    if constraints.capabilities:
        parts.append("capabilities=" + ",".join(sorted(constraints.capabilities)))
    joined = " ".join(parts) if parts else "declared constraints"
    return f"No knowledge provider matches {joined}"


class ResearchRouter:
    def __init__(self, registry: KnowledgeProviderCapabilityRegistry) -> None:
        self._registry = registry

    def available_source_types(self) -> tuple[str, ...]:
        """Evidence natures this router's capability registry can execute."""
        return self._registry.registered_evidence_natures()

    def registered_descriptors(self) -> tuple[KnowledgeProviderDescriptor, ...]:
        """Registration contracts the quality scorer may read. No invented authority."""
        return tuple(entry.descriptor for entry in self._registry.registered_providers())

    async def execute_need(
        self,
        need: ResearchNeed,
        context: ResearchContext,
    ) -> list[ResearchEvidence]:
        collected: list[ResearchEvidence] = []
        for candidate in self._registry.candidates_for(constraints_from_need(need)):
            if _case_required(candidate) and not context.scope.case_id:
                candidate = ProviderCandidate(
                    outcome="unavailable",
                    evidence_nature=candidate.evidence_nature,
                    descriptor=candidate.descriptor,
                )
            collected.extend(await self._run_candidate(candidate, need, context))
        return collected

    async def _run_candidate(
        self,
        candidate: ProviderCandidate,
        need: ResearchNeed,
        context: ResearchContext,
    ) -> list[ResearchEvidence]:
        source_type = _evidence_source_type(need, candidate)
        if candidate.outcome == "unregistered":
            return [
                _error_evidence(
                    need,
                    source_type,
                    ResearchSourceNotRegisteredError(source_type),
                )
            ]
        if candidate.outcome == "unavailable":
            unavailable = ResearchCapabilityUnavailableError(
                evidence_nature=candidate.evidence_nature,
                detail=_unavailable_detail(need, candidate.evidence_nature),
            )
            return [
                _not_found_evidence(
                    need,
                    source_type,
                    excerpt=str(unavailable),
                    metadata={
                        "error_type": type(unavailable).__name__,
                        "reason": "no_matching_provider",
                        **({"source_type": source_type} if candidate.evidence_nature else {}),
                    },
                )
            ]
        if candidate.outcome == "run":
            if candidate.source is None:
                return [
                    _not_found_evidence(
                        need,
                        source_type,
                        provider=_registered_provider(None, candidate.descriptor),
                        metadata={"reason": "no_matching_provider"},
                    )
                ]
            return await self._run_source(
                candidate.source,
                need,
                context,
                descriptor=candidate.descriptor,
            )
        raise AssertionError(f"unhandled provider candidate outcome: {candidate.outcome}")

    async def _run_source(
        self,
        source: ResearchSource,
        need: ResearchNeed,
        context: ResearchContext,
        *,
        descriptor: KnowledgeProviderDescriptor | None = None,
    ) -> list[ResearchEvidence]:
        provider = _registered_provider(source, descriptor)
        try:
            evidence = await source.research(need, context)
        except Exception as exc:  # noqa: BLE001 — isolate provider failures per need
            logger.exception(
                "research source %s failed for need %s",
                source.source_type,
                need.id,
            )
            return [_error_evidence(need, source.source_type, exc, provider=provider)]
        if not evidence:
            return [_not_found_evidence(need, source.source_type, provider=provider)]
        return list(evidence)


def _case_required(candidate: ProviderCandidate) -> bool:
    if candidate.descriptor is not None and descriptor_requires_case(candidate.descriptor):
        return True
    return candidate.evidence_nature == "case_knowledge"
