"""Iterative KnowledgeQuestion-driven research.

KnowledgeQuestion is the reusable identity. ResearchNeed is an execution
request for remaining gaps. Follow-ups become child KnowledgeQuestions
with idempotent parent/child lineage before any provider runs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    EvidenceSet,
    EvidenceSetItem,
    KnowledgeQuestionLineage,
    KnowledgeQuestionRow,
    ResearchRuntimeNeed,
)
from app.services.knowledge.scope import persist_scope_fields
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.knowledge_question import (
    KnowledgeQuestion,
    KnowledgeQuestionError,
    KnowledgeQuestionScope,
    QuestionIdentity,
    identity_from_text,
    tenant_question_scope,
)
from app.services.research.models import ResearchContext, ResearchNeed
from app.services.research.question_graph import (
    QuestionEvidenceGraph,
    QuestionEvidenceGraphError,
)
from app.services.research.question_reuse import (
    gap_source_types,
    lookup_reusable_claims,
    should_skip_providers,
)

GENERATED_FROM = "GENERATED_FROM"
QuestionRelationKind = Literal["same_as", "broader", "narrower"]
GROUNDED_REF_KEYS = (
    "knowledge_question_ids",
    "knowledge_claim_ids",
    "document_version_ids",
    "text_unit_ids",
)


@dataclass(frozen=True)
class RelatedKnowledgeQuestion:
    """Reserved semantic neighbour. v1 resolution does not consume these."""

    question: KnowledgeQuestion
    relation: QuestionRelationKind


class QuestionRelationResolver(Protocol):
    """Optional same_as / broader / narrower after canonical identity misses."""

    async def related_questions(
        self,
        *,
        normalized_text: str,
        identity_key: str,
        scope: KnowledgeQuestionScope,
    ) -> Sequence[RelatedKnowledgeQuestion]: ...


class CanonicalOnlyQuestionResolver:
    """v1 seam: identity_key only. Do not cluster or embed here."""

    async def related_questions(
        self,
        *,
        normalized_text: str,
        identity_key: str,
        scope: KnowledgeQuestionScope,
    ) -> Sequence[RelatedKnowledgeQuestion]:
        del normalized_text, identity_key, scope
        return []


@dataclass(frozen=True)
class QuestionLineageEdge:
    parent_question_id: str
    child_question_id: str
    trigger_claim_id: str | None = None
    trigger_graph_event_id: str | None = None
    why_needed: str = ""
    relation: str = GENERATED_FROM


def empty_grounded_refs() -> dict[str, list[str]]:
    return {key: [] for key in GROUNDED_REF_KEYS}


async def match_canonical_question(
    session: AsyncSession,
    question: str,
    scope: KnowledgeQuestionScope,
) -> KnowledgeQuestion | None:
    """Exact identity_key reuse inside one namespace."""
    identity = identity_from_text(question)
    row = (
        await session.execute(
            select(KnowledgeQuestionRow).where(
                KnowledgeQuestionRow.namespace == scope.namespace,
                KnowledgeQuestionRow.identity_key == identity.identity_key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.scope_key != scope.tenant.scope_key:
        raise KnowledgeQuestionError(
            "canonical question reuse crossed a knowledge tenant boundary"
        )
    return question_from_row(row)


async def resolve_or_create_knowledge_question(
    session: AsyncSession,
    *,
    graph: QuestionEvidenceGraph,
    question: str,
    scope: KnowledgeQuestionScope,
    relations: QuestionRelationResolver | None = None,
) -> KnowledgeQuestion:
    """Canonical reuse, then graph upsert, then persist the SQL identity."""
    existing = await match_canonical_question(session, question, scope)
    if existing is not None:
        return existing
    resolver = relations or CanonicalOnlyQuestionResolver()
    identity = identity_from_text(question)
    related = await resolver.related_questions(
        normalized_text=identity.normalized_text,
        identity_key=identity.identity_key,
        scope=scope,
    )
    for neighbour in related:
        if neighbour.relation == "same_as":
            return neighbour.question
    try:
        created = await graph.upsert_question(session, identity, scope)
    except QuestionEvidenceGraphError:
        return await _create_sql_question(session, identity, scope)
    return await _ensure_sql_question(session, created)


async def _create_sql_question(
    session: AsyncSession,
    identity: QuestionIdentity,
    scope: KnowledgeQuestionScope,
) -> KnowledgeQuestion:
    colliding = await match_canonical_question(session, identity.display_text, scope)
    if colliding is not None:
        return colliding
    session.add(
        KnowledgeQuestionRow(
            id=uuid4().hex,
            identity_key=identity.identity_key,
            normalized_text=identity.normalized_text,
            display_text=identity.display_text,
            namespace=scope.namespace,
            visibility=scope.visibility,
            **persist_scope_fields(scope.tenant),
        )
    )
    await session.flush()
    stored = await match_canonical_question(session, identity.display_text, scope)
    if stored is None:
        raise RuntimeError("KnowledgeQuestion SQL persist failed")
    return stored


async def _ensure_sql_question(
    session: AsyncSession,
    question: KnowledgeQuestion,
) -> KnowledgeQuestion:
    row = await session.get(KnowledgeQuestionRow, question.id)
    if row is not None:
        return question_from_row(row)
    colliding = await match_canonical_question(
        session, question.display_text, question.scope
    )
    if colliding is not None:
        return colliding
    session.add(
        KnowledgeQuestionRow(
            id=question.id,
            identity_key=question.identity_key,
            normalized_text=question.normalized_text,
            display_text=question.display_text,
            namespace=question.scope.namespace,
            visibility=question.scope.visibility,
            embedding_model=question.embedding_model,
            embedding_version=question.embedding_version,
            embedding_dimension=question.embedding_dimension,
            **persist_scope_fields(question.scope.tenant),
        )
    )
    await session.flush()
    stored = await session.get(KnowledgeQuestionRow, question.id)
    if stored is None:
        raise RuntimeError(f"KnowledgeQuestion {question.id} did not persist")
    return question_from_row(stored)


async def record_question_lineage(
    session: AsyncSession,
    *,
    parent_question_id: str,
    child_question_id: str,
    why_needed: str = "",
    trigger_claim_id: str | None = None,
    trigger_graph_event_id: str | None = None,
) -> QuestionLineageEdge | None:
    """Idempotent parent/child edge. Cycles are refused, not rewritten."""
    if parent_question_id == child_question_id:
        return None
    if child_question_id in await lineage_ancestors(session, parent_question_id):
        return None
    existing = (
        await session.execute(
            select(KnowledgeQuestionLineage).where(
                KnowledgeQuestionLineage.parent_question_id == parent_question_id,
                KnowledgeQuestionLineage.child_question_id == child_question_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return QuestionLineageEdge(
            parent_question_id=existing.parent_question_id,
            child_question_id=existing.child_question_id,
            trigger_claim_id=existing.trigger_claim_id,
            trigger_graph_event_id=existing.trigger_graph_event_id,
            why_needed=existing.why_needed,
        )
    session.add(
        KnowledgeQuestionLineage(
            id=uuid4().hex,
            parent_question_id=parent_question_id,
            child_question_id=child_question_id,
            trigger_claim_id=trigger_claim_id,
            trigger_graph_event_id=trigger_graph_event_id,
            why_needed=why_needed,
        )
    )
    await session.flush()
    return QuestionLineageEdge(
        parent_question_id=parent_question_id,
        child_question_id=child_question_id,
        trigger_claim_id=trigger_claim_id,
        trigger_graph_event_id=trigger_graph_event_id,
        why_needed=why_needed,
    )


async def lineage_ancestors(session: AsyncSession, question_id: str) -> set[str]:
    """Walk generated_from parents. A node may have more than one parent."""
    ancestors: set[str] = set()
    stack = [question_id]
    while stack:
        current = stack.pop()
        if current in ancestors:
            continue
        ancestors.add(current)
        parents = (
            await session.execute(
                select(KnowledgeQuestionLineage.parent_question_id).where(
                    KnowledgeQuestionLineage.child_question_id == current
                )
            )
        ).all()
        stack.extend(row[0] for row in parents if row[0])
    return ancestors


async def list_question_children(
    session: AsyncSession,
    parent_question_id: str,
) -> list[QuestionLineageEdge]:
    rows = (
        await session.execute(
            select(KnowledgeQuestionLineage)
            .where(KnowledgeQuestionLineage.parent_question_id == parent_question_id)
            .order_by(KnowledgeQuestionLineage.created_at, KnowledgeQuestionLineage.id)
        )
    ).scalars()
    return [
        QuestionLineageEdge(
            parent_question_id=row.parent_question_id,
            child_question_id=row.child_question_id,
            trigger_claim_id=row.trigger_claim_id,
            trigger_graph_event_id=row.trigger_graph_event_id,
            why_needed=row.why_needed,
        )
        for row in rows
    ]


async def gaps_for_need(
    session: AsyncSession,
    *,
    need: ResearchNeed,
    context: ResearchContext,
) -> list[str]:
    """Source types not closed by fresh grounded claims."""
    if context.scope.customer_id is None:
        return list(need.source_types)
    reused = await lookup_reusable_claims(session, need=need, context=context)
    return gap_source_types(need, reused)


async def question_is_freshly_answered(
    session: AsyncSession,
    *,
    need: ResearchNeed,
    context: ResearchContext,
) -> bool:
    if context.scope.customer_id is None:
        return False
    reused = await lookup_reusable_claims(session, need=need, context=context)
    return should_skip_providers(need, reused)


def bind_need_to_question(need: RuntimeResearchNeed, question: KnowledgeQuestion) -> RuntimeResearchNeed:
    return replace(need, knowledge_question_id=question.id, question_key=question.identity_key)


async def bind_runtime_needs_to_questions(
    session: AsyncSession,
    *,
    graph: QuestionEvidenceGraph,
    context: ResearchContext,
    attempt_id: str,
    relations: QuestionRelationResolver | None = None,
) -> list[ResearchRuntimeNeed]:
    """Attach canonical KnowledgeQuestion ids to persisted runtime needs."""
    customer_id = context.scope.customer_id
    if customer_id is None:
        return list(
            (
                await session.execute(
                    select(ResearchRuntimeNeed)
                    .where(ResearchRuntimeNeed.attempt_id == attempt_id)
                    .order_by(
                        ResearchRuntimeNeed.wave_number,
                        ResearchRuntimeNeed.created_at,
                        ResearchRuntimeNeed.research_need_id,
                    )
                )
            ).scalars()
        )
    scope = tenant_question_scope(customer_id)
    rows = list(
        (
            await session.execute(
                select(ResearchRuntimeNeed)
                .where(ResearchRuntimeNeed.attempt_id == attempt_id)
                .order_by(
                    ResearchRuntimeNeed.wave_number,
                    ResearchRuntimeNeed.created_at,
                    ResearchRuntimeNeed.research_need_id,
                )
            )
        ).scalars()
    )
    by_need_id = {row.research_need_id: row for row in rows}
    for row in rows:
        if row.knowledge_question_id:
            continue
        question = await resolve_or_create_knowledge_question(
            session,
            graph=graph,
            question=row.question,
            scope=scope,
            relations=relations,
        )
        row.knowledge_question_id = question.id
        parent_id = row.generated_from_question_id
        if parent_id is None and row.parent_research_need_id:
            parent_row = by_need_id.get(row.parent_research_need_id)
            if parent_row is not None and parent_row.knowledge_question_id:
                parent_id = parent_row.knowledge_question_id
                row.generated_from_question_id = parent_id
        if parent_id:
            await record_question_lineage(
                session,
                parent_question_id=parent_id,
                child_question_id=question.id,
                why_needed=row.why_needed or row.source_gap,
                trigger_claim_id=row.trigger_claim_id,
                trigger_graph_event_id=row.trigger_graph_event_id,
            )
    await session.flush()
    return rows


async def prepare_iterative_follow_ups(
    session: AsyncSession,
    *,
    graph: QuestionEvidenceGraph,
    context: ResearchContext,
    accepted: Sequence[RuntimeResearchNeed],
    previous: Sequence[RuntimeResearchNeed],
    relations: QuestionRelationResolver | None = None,
) -> list[RuntimeResearchNeed]:
    """Resolve/reuse child KnowledgeQuestions and keep only remaining gaps."""
    customer_id = context.scope.customer_id
    if customer_id is None:
        return list(accepted)
    scope = tenant_question_scope(customer_id)
    previous_by_id = {row.research_need_id: row for row in previous}
    prepared: list[RuntimeResearchNeed] = []
    max_depth = settings.research_max_follow_up_waves
    for need in accepted:
        child = await resolve_or_create_knowledge_question(
            session,
            graph=graph,
            question=need.question,
            scope=scope,
            relations=relations,
        )
        parent_id = _parent_question_id(need, previous_by_id)
        if parent_id is None and need.parent_research_need_id:
            parent_need = previous_by_id.get(need.parent_research_need_id)
            if parent_need is not None:
                parent = await resolve_or_create_knowledge_question(
                    session,
                    graph=graph,
                    question=parent_need.question,
                    scope=scope,
                    relations=relations,
                )
                parent_id = parent.id
        if parent_id is not None:
            ancestors = await lineage_ancestors(session, parent_id)
            if child.id in ancestors or len(ancestors) > max_depth:
                continue
            await record_question_lineage(
                session,
                parent_question_id=parent_id,
                child_question_id=child.id,
                why_needed=need.why_needed or need.source_gap,
                trigger_claim_id=need.trigger_claim_id or None,
                trigger_graph_event_id=need.trigger_graph_event_id or None,
            )
        executable = replace(
            need.as_need(),
            knowledge_question_id=child.id,
        )
        if await question_is_freshly_answered(
            session, need=executable, context=context
        ):
            continue
        remaining = await gaps_for_need(session, need=executable, context=context)
        if not remaining:
            continue
        prepared.append(
            replace(
                need,
                source_types=list(remaining),  # type: ignore[arg-type]
                knowledge_question_id=child.id,
                generated_from_question_id=parent_id or "",
                question_key=child.identity_key,
            )
        )
    return prepared


def question_from_row(row: KnowledgeQuestionRow) -> KnowledgeQuestion:
    return KnowledgeQuestion(
        id=row.id,
        identity_key=row.identity_key,
        normalized_text=row.normalized_text,
        display_text=row.display_text,
        scope=KnowledgeQuestionScope(
            visibility=row.visibility,  # type: ignore[arg-type]
            customer_id=row.customer_id,
        ),
        embedding_model=row.embedding_model,
        embedding_version=row.embedding_version,
        embedding_dimension=row.embedding_dimension,
        created_at=row.created_at,
    )


def _parent_question_id(
    need: RuntimeResearchNeed,
    previous_by_id: dict[str, RuntimeResearchNeed],
) -> str | None:
    if need.generated_from_question_id:
        return need.generated_from_question_id
    parent_need = previous_by_id.get(need.parent_research_need_id or "")
    if parent_need is None or not parent_need.knowledge_question_id:
        return None
    return parent_need.knowledge_question_id


def collect_grounded_refs(
    *,
    question_ids: Sequence[str],
    items: Sequence[EvidenceSetItem],
) -> dict[str, list[str]]:
    """Immutable freeze snapshot of grounded identities. No live pointers."""
    questions = {item for item in question_ids if item}
    claims: set[str] = set()
    versions: set[str] = set()
    units: set[str] = set()
    for item in items:
        provenance = item.provenance or {}
        reuse = provenance.get("reuse")
        if isinstance(reuse, dict):
            question_id = reuse.get("knowledge_question_id")
            if isinstance(question_id, str) and question_id.strip():
                questions.add(question_id.strip())
        for claim_id in _string_list(provenance.get("knowledge_claim_ids")):
            claims.add(claim_id)
        version_id = provenance.get("document_version_id")
        if isinstance(version_id, str) and version_id.strip():
            versions.add(version_id.strip())
        for unit_id in _string_list(provenance.get("supporting_text_unit_ids")):
            units.add(unit_id)
    return {
        "knowledge_question_ids": sorted(questions),
        "knowledge_claim_ids": sorted(claims),
        "document_version_ids": sorted(versions),
        "text_unit_ids": sorted(units),
    }


def _string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


async def attach_freeze_grounded_refs(
    session: AsyncSession,
    *,
    evidence_set_id: str,
    attempt_id: str,
) -> dict[str, list[str]]:
    items = list(
        (
            await session.execute(
                select(EvidenceSetItem).where(
                    EvidenceSetItem.evidence_set_id == evidence_set_id
                )
            )
        ).scalars()
    )
    question_ids = [
        row[0]
        for row in (
            await session.execute(
                select(ResearchRuntimeNeed.knowledge_question_id).where(
                    ResearchRuntimeNeed.attempt_id == attempt_id,
                    ResearchRuntimeNeed.knowledge_question_id.is_not(None),
                )
            )
        ).all()
        if row[0]
    ]
    refs = collect_grounded_refs(question_ids=question_ids, items=items)
    evidence_set = await session.get(EvidenceSet, evidence_set_id)
    if evidence_set is None:
        return refs
    evidence_set.grounded_refs = refs
    await session.flush()
    return refs

