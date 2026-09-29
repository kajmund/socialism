"""Hydrate Graph v2 facts from their canonical source passages, never claims."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.graph_v2 import GraphFact, GraphFactSource
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, TextUnitRecord
from app.services.research.models import (
    ResearchContext,
    ResearchError,
    ResearchEvidence,
    ResearchNeed,
)
from app.services.research.models import research_evidence


class GraphResearchError(ResearchError):
    """A graph read or its persisted source grounding is invalid."""


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def current_interval(start: datetime | None, end: datetime | None, now: datetime) -> bool:
    return (start is None or _utc(start) <= now) and (end is None or now < _utc(end))


def fact_is_current(fact: GraphFact, now: datetime) -> bool:
    return fact.status == "active" and current_interval(fact.valid_at, fact.invalid_at, now)


def _scope_allowed(scope: str, fact: GraphFact) -> bool:
    # Shared facts must never expose customer-owned passages.
    return scope == "shared" or scope == fact.scope_key


def _context_allowed(extra: dict, context: ResearchContext, *, require_case: bool = False) -> bool:
    case_id = extra.get("knowledge_case_id") or extra.get("case_id")
    module = extra.get("knowledge_module") or extra.get("module")
    if require_case and not case_id:
        return False
    return (case_id is None or case_id == context.scope.case_id) and (
        module is None or module == context.scope.module
    )


async def grounded_fact_evidence(
    session: AsyncSession,
    *,
    fact: GraphFact,
    need: ResearchNeed,
    context: ResearchContext,
    now: datetime,
    max_age_seconds: int | None,
) -> list[ResearchEvidence]:
    refs = list(
        (
            await session.scalars(
                select(GraphFactSource.source_ref)
                .where(
                    GraphFactSource.fact_id == fact.id,
                    GraphFactSource.source_kind == "text_unit",
                )
                .order_by(GraphFactSource.source_ref)
            )
        ).all()
    )
    if not refs:
        # Structural edges (e.g. decomposition) are traversal context, not evidence.
        return []
    units = list(
        (
            await session.scalars(
                select(TextUnitRecord)
                .where(
                    TextUnitRecord.id.in_(refs),
                )
                .order_by(
                    TextUnitRecord.document_version_id, TextUnitRecord.ordinal, TextUnitRecord.id
                )
            )
        ).all()
    )
    if len(units) != len(refs):
        raise GraphResearchError(f"Graph fact {fact.id} has missing supporting TextUnits")
    grouped: dict[str, list[TextUnitRecord]] = defaultdict(list)
    for unit in units:
        if not _scope_allowed(unit.scope_key, fact):
            raise GraphResearchError(f"Graph fact {fact.id} crosses its source scope")
        grouped[unit.document_version_id].append(unit)
    output = []
    for version_id, passages in grouped.items():
        version = await session.get(DocumentVersionRecord, version_id)
        document = await session.get(CanonicalDocumentRecord, passages[0].document_id)
        if version is None or document is None:
            raise GraphResearchError(f"Graph fact {fact.id} has missing source document/version")
        if not _valid_grounding(fact, document, version, passages):
            raise GraphResearchError(f"Graph fact {fact.id} has inconsistent source grounding")
        if _usable_source(
            document=document,
            version=version,
            passages=passages,
            need=need,
            context=context,
            now=now,
        ):
            output.append(
                _to_evidence(
                    fact=fact,
                    document=document,
                    version=version,
                    passages=passages,
                    need=need,
                    now=now,
                    max_age_seconds=max_age_seconds,
                )
            )
    return output


def _valid_grounding(fact, document, version, passages) -> bool:
    return (
        _scope_allowed(document.scope_key, fact)
        and version.scope_key == document.scope_key
        and version.document_id == document.id
        and all(
            unit.document_id == document.id and unit.scope_key == version.scope_key
            for unit in passages
        )
    )


def _usable_source(*, document, version, passages, need, context, now) -> bool:
    return (
        document.source_type in need.source_types
        and version.superseded_at is None
        and current_interval(version.valid_from, version.valid_to, now)
        and _context_allowed(
            document.extra, context, require_case=document.source_type == "case_knowledge"
        )
        and all(current_interval(unit.valid_from, unit.valid_to, now) for unit in passages)
        and all(_context_allowed(unit.extra, context) for unit in passages)
    )


def _to_evidence(
    *, fact, document, version, passages, need, now, max_age_seconds
) -> ResearchEvidence:
    stamp = _utc(version.ingested_at)
    age = (now - stamp).total_seconds()
    fresh = age >= 0 and (max_age_seconds is None or age <= max_age_seconds)
    return research_evidence(
        research_need_id=need.id,
        source_type=document.source_type,
        status="found",
        title=document.title,
        excerpt="\n\n".join(unit.text for unit in passages),
        locator=", ".join(unit.locator or unit.id for unit in passages),
        source_id=document.id,
        source_url=document.canonical_uri,
        provider="graph_v2",
        retrieved_at=stamp,
        metadata={
            "graph_fact_ids": [fact.id],
            "graph_fact_text": fact.fact_text,
            "supporting_text_unit_ids": [unit.id for unit in passages],
            "document_ids": [document.id],
            "document_version_ids": [version.id],
            "document_version_id": version.id,
            "reuse": {
                "origin": "persistent_knowledge",
                "freshness": "fresh" if fresh else "stale",
                "evidence_ref": f"{fact.id}:{version.id}",
                "knowledge_question_id": need.knowledge_question_id,
            },
        },
    )
