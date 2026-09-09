"""Deterministic ResearchNeed → registered sources → ResearchEvidence[].

Routing is the order of ``need.source_types``. No LLM, no early-exit on hits.
"""

from __future__ import annotations

from app.services.research.models import (
    ResearchContext,
    ResearchEvidence,
    ResearchNeed,
    ResearchScopeRequiredError,
    ResearchSourceNotRegisteredError,
    ResearchSourceType,
    research_evidence,
)
from app.services.research.registry import ResearchSourceRegistry
from app.services.research.source import ResearchSource

def _safe_error_metadata(source_type: ResearchSourceType, exc: BaseException) -> dict[str, object]:
    return {"error_type": type(exc).__name__, "source_type": source_type}


def _safe_error_message(exc: BaseException) -> str:
    if isinstance(exc, (ResearchScopeRequiredError, ResearchSourceNotRegisteredError)):
        return str(exc)
    return f"{type(exc).__name__}: research source failed"


def _error_evidence(
    need: ResearchNeed,
    source_type: ResearchSourceType,
    exc: BaseException,
    *,
    provider: str | None = None,
) -> ResearchEvidence:
    metadata = _safe_error_metadata(source_type, exc)
    return research_evidence(
        research_need_id=need.id,
        source_type=source_type,
        status="error",
        provider=provider,
        excerpt=_safe_error_message(exc),
        metadata=metadata,
    )


def _not_found_evidence(
    need: ResearchNeed,
    source_type: ResearchSourceType,
    *,
    provider: str | None = None,
) -> ResearchEvidence:
    return research_evidence(
        research_need_id=need.id,
        source_type=source_type,
        status="not_found",
        provider=provider,
    )


def _source_provider(source: ResearchSource) -> str | None:
    provider = getattr(source, "provider_id", None)
    return provider if isinstance(provider, str) else None


class ResearchRouter:
    def __init__(self, registry: ResearchSourceRegistry) -> None:
        self._registry = registry

    async def execute_need(
        self,
        need: ResearchNeed,
        context: ResearchContext,
    ) -> list[ResearchEvidence]:
        collected: list[ResearchEvidence] = []
        for source_type in need.source_types:
            sources = self._registry.sources_for(source_type)
            if not sources:
                collected.append(
                    _error_evidence(need, source_type, ResearchSourceNotRegisteredError(source_type))
                )
                continue
            for source in sources:
                collected.extend(await self._run_source(source, need, context))
        return collected

    async def _run_source(
        self,
        source: ResearchSource,
        need: ResearchNeed,
        context: ResearchContext,
    ) -> list[ResearchEvidence]:
        provider = _source_provider(source)
        try:
            evidence = await source.research(need, context)
        except Exception as exc:
            return [_error_evidence(need, source.source_type, exc, provider=provider)]
        if not evidence:
            return [_not_found_evidence(need, source.source_type, provider=provider)]
        return list(evidence)
