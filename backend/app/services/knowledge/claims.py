"""Domain-neutral claims grounded in TextUnits.

A claim is an assertion. Support is SUPPORTED_BY one or more TextUnits.
Adapters choose predicate strings; this module does not interpret them.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    KnowledgeClaimRecord,
    KnowledgeQuestionRow,
)
from app.services.knowledge.events import (
    CLAIM_SUPERSEDED,
    record_graph_event,
    utc_now,
)
from app.services.knowledge.identity import knowledge_claim_identity
from app.services.knowledge.scope import (
    SCOPE_CUSTOMER,
    KnowledgeScopeError,
    KnowledgeTenantScope,
    assert_not_promoted,
    require_persist_scope,
    scope_from_row,
    visible_to,
)
from app.services.overgraph.catalogs import require_knowledge
from app.services.knowledge.claim_supersession import supersede_graph_claim
from app.services.overgraph.claim_answers import (
    ClaimAnswerSource,
    answered_claim_ids,
    claim_answer_edges,
    link_claim_answer,
)
from app.services.overgraph.legal_claims import mark_claim_superseded, supporting_text_units
from app.services.overgraph.research import load_text_units
from app.services.overgraph.text_units import load_domain_text_unit

SUPPORTED_BY = "SUPPORTED_BY"
ANSWERED_BY = "ANSWERED_BY"


class KnowledgeClaimError(RuntimeError):
    """A claim cannot be grounded in the supplied TextUnits."""


class ClaimPassage(Protocol):
    id: str
    text: str


@dataclass(frozen=True)
class KnowledgeClaim:
    id: str
    customer_id: int | None
    predicate: str
    value: dict[str, object]
    supporting_text_unit_ids: tuple[str, ...]
    scope_type: str = SCOPE_CUSTOMER
    persistence_class: str | None = None
    observation_kind: str | None = None

    def __post_init__(self) -> None:
        require_persist_scope(scope_type=self.scope_type, customer_id=self.customer_id)

    @property
    def scope(self) -> KnowledgeTenantScope:
        return require_persist_scope(scope_type=self.scope_type, customer_id=self.customer_id)


@dataclass(frozen=True)
class KnowledgeClaimAnswerHit:
    """Reuse row: claim plus the evidence nature it answered."""

    claim: KnowledgeClaim
    source_type: str
    knowledge_question_id: str | None
    created_at: datetime | None


def knowledge_claim_id(
    *,
    predicate: str,
    value: dict[str, object],
    scope_key: str,
) -> str:
    return knowledge_claim_identity(
        scope_key=scope_key,
        predicate=predicate,
        value=value,
    )


def knowledge_claim(
    *,
    predicate: str,
    value: dict[str, object],
    supporting_text_unit_ids: Sequence[str],
    customer_id: int,
) -> KnowledgeClaim:
    scope = require_persist_scope(customer_id=customer_id)
    identity = knowledge_claim_id(
        scope_key=scope.scope_key,
        predicate=predicate,
        value=value,
    )
    return KnowledgeClaim(
        id=identity,
        customer_id=scope.customer_id,
        scope_type=scope.scope_type,
        predicate=predicate,
        value=value,
        supporting_text_unit_ids=tuple(supporting_text_unit_ids),
    )


def supporting_text_unit_ids_for_quote(
    quote: str,
    units: Sequence[ClaimPassage],
) -> list[str]:
    """Map a verbatim quote onto the TextUnits that contain it. No LLM."""
    text = quote.strip()
    if not text:
        raise KnowledgeClaimError("claim citation quote is empty")
    contained = [unit.id for unit in units if text in unit.text]
    if contained:
        return contained
    compact = _compact(text)
    contained = [unit.id for unit in units if compact in _compact(unit.text)]
    if contained:
        return contained
    joined = "\n\n".join(unit.text for unit in units)
    start = joined.find(text)
    if start < 0:
        raise KnowledgeClaimError(f"citation quote is absent from TextUnits: {text!r}")
    end = start + len(text)
    cursor = 0
    overlapping: list[str] = []
    for unit in units:
        unit_end = cursor + len(unit.text)
        if cursor < end and unit_end > start:
            overlapping.append(unit.id)
        cursor = unit_end + 2
    if not overlapping:
        raise KnowledgeClaimError(f"citation quote is absent from TextUnits: {text!r}")
    return overlapping


async def persist_knowledge_claim(
    session: AsyncSession, claim: KnowledgeClaim
) -> KnowledgeClaimRecord:
    # Circular: claim_store imports claim identity helpers from this module.
    from app.services.knowledge.claim_store import persist_knowledge_claim as persist

    return await persist(session, claim)


async def persist_knowledge_claims(
    session: AsyncSession, claims: Sequence[KnowledgeClaim]
) -> list[KnowledgeClaimRecord]:
    # Circular: claim_store imports claim identity helpers from this module.
    from app.services.knowledge.claim_store import persist_knowledge_claims as persist

    return await persist(session, claims)


async def supersede_knowledge_claim(
    session: AsyncSession,
    claim_id: str,
    *,
    successor: KnowledgeClaim | None = None,
    at: datetime | None = None,
    valid_to: datetime | None = None,
) -> object:
    """Close valid/system time on a claim. History stays queryable."""
    row = await session.get(KnowledgeClaimRecord, claim_id)
    if row is None:
        return await supersede_graph_claim(
            session, claim_id, KnowledgeClaimError,
            successor=successor, at=at, valid_to=valid_to,
        )
    if row.superseded_at is not None:
        raise KnowledgeClaimError(f"claim {claim_id} is already superseded")
    stamp = at or utc_now()
    successor_id = None
    if successor is not None:
        stored = await persist_knowledge_claim(session, successor)
        successor_id = stored.id
        if successor_id == claim_id:
            raise KnowledgeClaimError("a claim cannot supersede itself")
    row.superseded_at = stamp
    row.valid_to = valid_to or stamp
    row.successor_id = successor_id
    await session.flush()
    # Supersession must be visible in the graph, not only in the SQL mirror.
    await asyncio.to_thread(
        mark_claim_superseded,
        require_knowledge(),
        claim_id,
        superseded_at=stamp,
        valid_to=valid_to or stamp,
        successor_id=successor_id,
    )
    await record_graph_event(
        session,
        scope=scope_from_row(row),
        event_type=CLAIM_SUPERSEDED,
        node_kind="claim",
        node_id=claim_id,
        related_id=successor_id,
        payload={"successor_id": successor_id} if successor_id else {},
        created_at=stamp,
    )
    return row


async def answer_research_need(
    session: AsyncSession,
    *,
    research_need_id: str,
    question_key: str,
    claim_ids: Sequence[str],
    source_type: str,
    knowledge_question_id: str | None = None,
) -> None:
    """ResearchNeed → ANSWERED_BY → Claim. Reuse looks up question_key."""
    if not research_need_id.strip():
        raise KnowledgeClaimError("research_need_id is required")
    if not question_key.strip():
        raise KnowledgeClaimError("question_key is required")
    if not source_type.strip():
        raise KnowledgeClaimError("source_type is required")
    if not claim_ids:
        raise KnowledgeClaimError("ANSWERED_BY requires at least one claim")
    claim_scope = await _claim_scope(session, claim_ids[0])
    for claim_id in claim_ids[1:]:
        other = await _claim_scope(session, claim_id)
        if other != claim_scope:
            raise KnowledgeClaimError("ANSWERED_BY claims must share one knowledge scope")
    question_id = knowledge_question_id or await _scoped_knowledge_question_id(
        session,
        question_key=question_key,
        scope=claim_scope,
    )
    existing = set(
        await asyncio.to_thread(
            answered_claim_ids,
            require_knowledge(),
            research_need_id=research_need_id,
            claim_ids=tuple(claim_ids),
        )
    )
    for claim_id in claim_ids:
        if claim_id in existing:
            continue
        await asyncio.to_thread(
            link_claim_answer,
            require_knowledge(),
            claim_key=claim_id,
            scope=claim_scope,
            question_key=question_key,
            research_need_id=research_need_id,
            source=ClaimAnswerSource(
                source_type=source_type,
                knowledge_question_id=question_id,
                relation=ANSWERED_BY,
                created_at_ms=int(utc_now().timestamp() * 1000),
            ),
        )
    await session.flush()


async def claim_answers_for_question_key(
    session: AsyncSession,
    *,
    customer_id: int,
    question_key: str,
) -> list[KnowledgeClaimAnswerHit]:
    """Reuse: claims that answer this question, read from OverGraph."""
    catalog = require_knowledge()
    edges = await asyncio.to_thread(
        claim_answer_edges, catalog, customer_id=customer_id, question_key=question_key,
    )
    hits: list[KnowledgeClaimAnswerHit] = []
    for node, props in edges:
        claim_id = str(node.key)
        support = await catalog.run(supporting_text_units, catalog, claim_id)
        if not support:
            raise KnowledgeClaimError(f"claim {claim_id} has no SUPPORTED_BY TextUnits")
        scope_customer = scope_customer_from_node(node)
        hits.append(
            KnowledgeClaimAnswerHit(
                claim=KnowledgeClaim(
                    id=claim_id,
                    customer_id=scope_customer,
                    scope_type="customer" if scope_customer is not None else "shared",
                    predicate=str(node.props.get("predicate") or ""),
                    value=json.loads(str(node.props.get("value_json") or "{}")),
                    supporting_text_unit_ids=tuple(support),
                ),
                source_type=str(props.get("source_type") or ""),
                knowledge_question_id=str(props.get("knowledge_question_id") or "") or None,
                created_at=_created_at(props, node),
            )
        )
    return hits


def scope_customer_from_node(node) -> int | None:
    """Customer id encoded in a graph node's ``scope_key`` (None for shared)."""
    scope_key = str(node.props.get("scope_key") or "")
    if not scope_key.startswith("customer:"):
        return None
    return int(scope_key.split(":", 1)[1])


def _created_at(props: dict[str, object], node=None):
    """When the evidence was created: the claim node wins over the answer edge."""
    claim_created = int((node.props.get("created_at_ms") if node is not None else 0) or 0)
    created = claim_created or int(props.get("created_at_ms") or 0)
    return datetime.fromtimestamp(created / 1000, tz=UTC) if created else utc_now()


async def claims_answering_question_key(
    session: AsyncSession,
    *,
    customer_id: int,
    question_key: str,
) -> list[KnowledgeClaim]:
    """Reuse: claims that already answer this question key for the tenant."""
    return [
        hit.claim
        for hit in await claim_answers_for_question_key(
            session,
            customer_id=customer_id,
            question_key=question_key,
        )
    ]


async def _scoped_knowledge_question_id(
    session: AsyncSession,
    *,
    question_key: str,
    scope: KnowledgeTenantScope,
) -> str | None:
    row = (
        await session.execute(
            select(KnowledgeQuestionRow.id).where(
                KnowledgeQuestionRow.identity_key == question_key,
                KnowledgeQuestionRow.scope_key == scope.scope_key,
            )
        )
    ).scalar_one_or_none()
    return row


async def _claim_scope(session: AsyncSession, claim_id: str) -> KnowledgeTenantScope:
    """Claim scope from SQL, or from the graph node when the claim lives only there."""
    catalog = require_knowledge()
    node = catalog.get_by_key("Claim", claim_id)
    if node is None:
        raise KnowledgeClaimError(f"claim {claim_id} is missing")
    scope_key = str(node.props.get("scope_key") or "")
    if not scope_key:
        raise KnowledgeClaimError(f"claim {claim_id} has no scope")
    if scope_key == "shared":
        return require_persist_scope(scope_type="shared")
    if scope_key.startswith("customer:"):
        return require_persist_scope(customer_id=int(scope_key.split(":", 1)[1]))
    raise KnowledgeClaimError(f"claim {claim_id} has an unknown scope {scope_key!r}")


async def assert_claim_grounding_scope(
    session: AsyncSession,
    claim: KnowledgeClaim,
) -> None:
    catalog = require_knowledge()
    for unit_id in claim.supporting_text_unit_ids:
        loaded = await catalog.run(load_text_units, catalog, [unit_id])
        unit = loaded[0] if loaded else None
        if unit is None:
            raise KnowledgeClaimError(f"SUPPORTED_BY TextUnit {unit_id} is missing")
        unit_scope = scope_from_row(unit)
        try:
            assert_not_promoted(source=unit_scope, target=claim.scope)
        except KnowledgeScopeError as exc:
            raise KnowledgeClaimError(str(exc)) from exc
        if unit_scope.scope_type == SCOPE_CUSTOMER and claim.scope != unit_scope:
            raise KnowledgeClaimError("customer claim cannot ground in another tenant TextUnit")
        if (
            claim.scope.scope_type == SCOPE_CUSTOMER
            and unit_scope.scope_type == SCOPE_CUSTOMER
            and not visible_to(owned=unit_scope, reader_customer_id=claim.scope.customer_id)
        ):
            raise KnowledgeClaimError("customer claim cannot ground in another tenant TextUnit")


async def document_refs_for_units(
    session: AsyncSession,
    unit_ids: Sequence[str],
) -> tuple[str, str] | None:
    if not unit_ids:
        return None
    unit = await asyncio.to_thread(
        load_domain_text_unit, require_knowledge(), unit_id=unit_ids[0],
    )
    if unit is None:
        return None
    return unit.document_id, unit.document_version_id


async def supporting_text_unit_ids_for_claim(
    session: AsyncSession,
    claim_id: str,
) -> list[str]:
    catalog = require_knowledge()
    return await catalog.run(supporting_text_units, catalog, claim_id)


def _compact(value: str) -> str:
    return " ".join(value.split())
