"""Revalidate frozen EvidenceSets when the graph changes. Snapshots stay immutable."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    EvidenceSet,
    EvidenceSetItem,
    EvidenceSetRevalidation,
    ExecutionRun,
    KnowledgeClaimAnswer,
    KnowledgeClaimTextUnit,
    KnowledgeGraphEventRecord,
    KnowledgeQuestionRow,
    KnowledgeRelationshipRecord,
)
from app.jev.system import JevClientError, JevSystemOne, parse_noul
from app.services.knowledge.events import (
    CLAIM_ADDED,
    CLAIM_SUPERSEDED,
    EDGE_ADDED,
    utc_now,
)
from app.services.knowledge.scope import (
    SCOPE_CUSTOMER,
    KnowledgeScopeError,
    scope_from_row,
)

REVALIDATION_CLEAR = "clear"
REVALIDATION_IMPACTED = "impacted"
REVALIDATION_REQUIRED = "revalidation_required"
REVALIDATION_UNKNOWN = "unknown"
REVALIDATION_STATES = frozenset(
    {
        REVALIDATION_CLEAR,
        REVALIDATION_IMPACTED,
        REVALIDATION_REQUIRED,
        REVALIDATION_UNKNOWN,
    }
)
RevalidationState = Literal["clear", "impacted", "revalidation_required", "unknown"]
_IMPACT_QUESTION = {
    "type": "noul",
    "instructions": (
        "True if the new claim or edge can materially change the frozen answer. "
        "False if it is redundant, off-topic, or too weak to move the previous conclusion."
    ),
}


class RevalidationError(RuntimeError):
    """Impact lookup failed. Jev errors become unknown, never clear."""


@dataclass(frozen=True)
class GraphImpact:
    question_keys: tuple[str, ...]
    claim_ids: tuple[str, ...]
    text_unit_ids: tuple[str, ...]


@dataclass(frozen=True)
class RevalidationDecision:
    evidence_set_id: str
    graph_event_id: str
    state: RevalidationState
    impact_noul: float | None
    question_key: str | None
    knowledge_question_id: str | None


async def graph_impact_from_event(
    session: AsyncSession,
    event: KnowledgeGraphEventRecord,
) -> GraphImpact:
    claim_ids: set[str] = set()
    if event.event_type in {CLAIM_ADDED, CLAIM_SUPERSEDED} and event.node_kind == "claim":
        claim_ids.add(event.node_id)
    if event.event_type == EDGE_ADDED:
        edge = await session.get(KnowledgeRelationshipRecord, event.node_id)
        if edge is None:
            raise RevalidationError(f"EDGE_ADDED relationship {event.node_id} is missing")
        if edge.from_kind == "claim":
            claim_ids.add(edge.from_id)
        if edge.to_kind == "claim":
            claim_ids.add(edge.to_id)
        if edge.from_kind == "text_unit" or edge.to_kind == "text_unit":
            unit_ids = {
                edge.from_id if edge.from_kind == "text_unit" else "",
                edge.to_id if edge.to_kind == "text_unit" else "",
            }
            unit_ids.discard("")
            keys = await _question_keys_for_claims(session, claim_ids) if claim_ids else []
            return GraphImpact(
                question_keys=tuple(keys),
                claim_ids=tuple(sorted(claim_ids)),
                text_unit_ids=tuple(sorted(unit_ids)),
            )
    if not claim_ids:
        return GraphImpact(question_keys=(), claim_ids=(), text_unit_ids=())
    keys = await _question_keys_for_claims(session, claim_ids)
    units = await _text_units_for_claims(session, claim_ids)
    return GraphImpact(
        question_keys=tuple(keys),
        claim_ids=tuple(sorted(claim_ids)),
        text_unit_ids=tuple(units),
    )


async def affected_frozen_evidence_sets(
    session: AsyncSession,
    *,
    customer_id: int | None,
    impact: GraphImpact,
) -> list[EvidenceSet]:
    if not impact.question_keys and not impact.claim_ids and not impact.text_unit_ids:
        return []
    query = (
        select(EvidenceSet)
        .join(ExecutionRun, ExecutionRun.id == EvidenceSet.run_id)
        .where(EvidenceSet.status == "frozen")
    )
    if customer_id is not None:
        query = query.where(ExecutionRun.customer_id == customer_id)
    else:
        raise KnowledgeScopeError(
            "revalidation of customer graph events requires customer_id"
        )
    rows = (await session.execute(query)).scalars().all()
    affected: list[EvidenceSet] = []
    for evidence_set in rows:
        items = (
            await session.execute(
                select(EvidenceSetItem).where(
                    EvidenceSetItem.evidence_set_id == evidence_set.id
                )
            )
        ).scalars().all()
        if any(_item_touches_impact(item, impact) for item in items):
            affected.append(evidence_set)
    return affected


def classify_revalidation_state(
    noul: float,
    *,
    impact_threshold: float,
    clear_threshold: float,
) -> RevalidationState:
    """Map a valid noul onto conservative bands. Invalid scores are unknown."""
    if clear_threshold >= impact_threshold:
        raise RevalidationError(
            "revalidation_clear_threshold must be below revalidation_impact_threshold"
        )
    if not math.isfinite(noul) or noul < 0.0 or noul > 1.0:
        return REVALIDATION_UNKNOWN
    if noul >= impact_threshold:
        return REVALIDATION_IMPACTED
    if noul <= clear_threshold:
        return REVALIDATION_CLEAR
    return REVALIDATION_REQUIRED


async def revalidate_after_event(
    session: AsyncSession,
    event: KnowledgeGraphEventRecord | str,
    *,
    jev: JevSystemOne,
) -> list[RevalidationDecision]:
    """Jev decides whether a graph mutation can change a frozen answer."""
    row = (
        event
        if isinstance(event, KnowledgeGraphEventRecord)
        else await session.get(KnowledgeGraphEventRecord, event)
    )
    if row is None:
        raise RevalidationError("graph event is missing")
    event = row
    impact = await graph_impact_from_event(session, event)
    event_scope = scope_from_row(event)
    if event_scope.scope_type == SCOPE_CUSTOMER and event_scope.customer_id is None:
        raise KnowledgeScopeError("customer graph event is missing customer_id")
    sets = await affected_frozen_evidence_sets(
        session,
        customer_id=event_scope.customer_id,
        impact=impact,
    )
    if not sets:
        return []
    question_id = await _knowledge_question_id(
        session, impact.question_keys, event_scope
    )
    question_key = impact.question_keys[0] if impact.question_keys else None
    try:
        noul: float | None = await _impact_noul(
            jev, event=event, impact=impact, evidence_sets=sets
        )
        state = classify_revalidation_state(
            noul,
            impact_threshold=settings.revalidation_impact_threshold,
            clear_threshold=settings.revalidation_clear_threshold,
        )
    except JevClientError:
        noul = None
        state = REVALIDATION_UNKNOWN
    decisions: list[RevalidationDecision] = []
    for evidence_set in sets:
        row = await _persist_revalidation(
            session,
            evidence_set_id=evidence_set.id,
            graph_event_id=event.id,
            question_key=question_key,
            knowledge_question_id=question_id,
            state=state,
            impact_noul=noul,
        )
        decisions.append(
            RevalidationDecision(
                evidence_set_id=row.evidence_set_id,
                graph_event_id=row.graph_event_id,
                state=state,
                impact_noul=noul,
                question_key=question_key,
                knowledge_question_id=question_id,
            )
        )
    return decisions


def _item_touches_impact(item: EvidenceSetItem, impact: GraphImpact) -> bool:
    provenance = item.provenance if isinstance(item.provenance, dict) else {}
    key = provenance.get("answered_by_question_key")
    if isinstance(key, str) and key in impact.question_keys:
        return True
    claim_ids = provenance.get("knowledge_claim_ids")
    if isinstance(claim_ids, list) and any(
        isinstance(claim_id, str) and claim_id in impact.claim_ids for claim_id in claim_ids
    ):
        return True
    unit_ids = provenance.get("text_unit_ids") or provenance.get("supporting_text_unit_ids")
    return isinstance(unit_ids, list) and any(
        isinstance(unit_id, str) and unit_id in impact.text_unit_ids for unit_id in unit_ids
    )


async def _question_keys_for_claims(
    session: AsyncSession,
    claim_ids: set[str],
) -> list[str]:
    rows = (
        await session.execute(
            select(KnowledgeClaimAnswer.question_key).where(
                KnowledgeClaimAnswer.claim_id.in_(list(claim_ids))
            )
        )
    ).all()
    return sorted({row[0] for row in rows if row[0]})


async def _text_units_for_claims(
    session: AsyncSession,
    claim_ids: set[str],
) -> list[str]:
    rows = (
        await session.execute(
            select(KnowledgeClaimTextUnit.text_unit_id).where(
                KnowledgeClaimTextUnit.claim_id.in_(list(claim_ids))
            )
        )
    ).all()
    return sorted({row[0] for row in rows if row[0]})


async def _knowledge_question_id(
    session: AsyncSession,
    question_keys: Sequence[str],
    scope: object,
) -> str | None:
    if not question_keys:
        return None
    return (
        await session.execute(
            select(KnowledgeQuestionRow.id).where(
                KnowledgeQuestionRow.identity_key == question_keys[0],
                KnowledgeQuestionRow.scope_key == scope.scope_key,
            )
        )
    ).scalar_one_or_none()


async def _impact_noul(
    jev: JevSystemOne,
    *,
    event: KnowledgeGraphEventRecord,
    impact: GraphImpact,
    evidence_sets: Sequence[EvidenceSet],
) -> float:
    result = await jev.ask(
        state={
            "event_type": event.event_type,
            "node_kind": event.node_kind,
            "node_id": event.node_id,
            "question_keys": list(impact.question_keys),
            "claim_ids": list(impact.claim_ids),
            "text_unit_ids": list(impact.text_unit_ids),
            "frozen_evidence_set_ids": [row.id for row in evidence_sets],
        },
        questions={"material_change": _IMPACT_QUESTION},
        model=settings.jev_model,
        timeout_seconds=settings.jev_timeout_seconds,
    )
    return parse_noul(result.answers, "material_change")


async def _persist_revalidation(
    session: AsyncSession,
    *,
    evidence_set_id: str,
    graph_event_id: str,
    question_key: str | None,
    knowledge_question_id: str | None,
    state: RevalidationState,
    impact_noul: float | None,
) -> EvidenceSetRevalidation:
    existing = (
        await session.execute(
            select(EvidenceSetRevalidation).where(
                EvidenceSetRevalidation.evidence_set_id == evidence_set_id,
                EvidenceSetRevalidation.graph_event_id == graph_event_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = EvidenceSetRevalidation(
        id=_revalidation_id(evidence_set_id, graph_event_id),
        evidence_set_id=evidence_set_id,
        graph_event_id=graph_event_id,
        question_key=question_key,
        knowledge_question_id=knowledge_question_id,
        state=state,
        impact_noul=impact_noul,
        created_at=utc_now(),
    )
    session.add(row)
    await session.flush()
    return row


def _revalidation_id(evidence_set_id: str, graph_event_id: str) -> str:
    return hashlib.sha256(f"{evidence_set_id}\0{graph_event_id}".encode()).hexdigest()
