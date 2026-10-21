"""Idempotent persist for classified domain claims."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeClaimRecord, KnowledgeClaimTextUnit
from app.services.knowledge.claims import (
    KnowledgeClaim,
    KnowledgeClaimError,
    assert_claim_grounding_scope,
    knowledge_claim_id,
)
from app.services.knowledge.events import CLAIM_ADDED, record_graph_event, utc_now
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.legal_claims import claim_in_graph, claim_is_superseded
from app.services.knowledge.graph_claim_mirror import attach_claim_supports, mirror_claim
from app.services.knowledge.persistence_class import DOMAIN_KNOWLEDGE, classify_persistence
from app.services.knowledge.scope import scope_from_row


@dataclass(frozen=True)
class PersistedClaim:
    """Outcome of a claim write. The graph node is authoritative."""

    id: str
    identity_key: str


async def persist_knowledge_claims(
    session: AsyncSession,
    claims: Sequence[KnowledgeClaim],
) -> list[PersistedClaim]:
    return [await persist_knowledge_claim(session, claim) for claim in claims]


async def persist_knowledge_claim(
    session: AsyncSession,
    claim: KnowledgeClaim,
) -> PersistedClaim:
    stored, _reused = await persist_domain_claim(session, claim)
    return stored


async def persist_domain_claim(
    session: AsyncSession,
    claim: KnowledgeClaim,
) -> tuple[PersistedClaim, bool]:
    if not claim.supporting_text_unit_ids:
        raise KnowledgeClaimError(f"claim {claim.id} has no SUPPORTED_BY TextUnits")
    decision = classify_persistence(
        value=claim.value,
        declared_class=claim.persistence_class,
        declared_kind=claim.observation_kind,
    )
    if decision.persistence_class != DOMAIN_KNOWLEDGE:
        raise KnowledgeClaimError(
            f"claim rejected as {decision.persistence_class}: {decision.reason}"
        )
    identity = knowledge_claim_id(
        scope_key=claim.scope.scope_key,
        predicate=claim.predicate,
        value=claim.value,
    )
    if claim.id != identity:
        raise KnowledgeClaimError("claim id does not match stable identity")
    await assert_claim_grounding_scope(session, claim)
    # Legacy rows keep their id; they are materialised into the graph here.
    legacy = await claim_by_identity(session, claim.scope.scope_key, identity)
    if legacy is not None:
        _reject_superseded_claim(legacy)
        if scope_from_row(legacy) != claim.scope:
            raise KnowledgeClaimError(
                f"claim {legacy.id} already exists in a different knowledge scope"
            )
        key = legacy.id
    else:
        key = identity
    catalog = require_knowledge()
    if claim_is_superseded(catalog, key):
        raise KnowledgeClaimError(f"claim {key} is superseded")
    reused = legacy is not None or (
        claim_in_graph(catalog, scope_key=claim.scope.scope_key, identity=key) is not None
    )
    await asyncio.to_thread(mirror_claim, claim, key=key)
    await asyncio.to_thread(attach_claim_supports, key, claim.supporting_text_unit_ids)
    if not reused:
        await record_graph_event(
            session,
            scope=claim.scope,
            event_type=CLAIM_ADDED,
            node_kind="claim",
            node_id=key,
            related_id=claim.supporting_text_unit_ids[0],
            payload={"predicate": claim.predicate},
            created_at=utc_now(),
        )
    return PersistedClaim(id=key, identity_key=identity), reused


async def attach_supporting_text_units(
    session: AsyncSession,
    claim_id: str,
    unit_ids: Sequence[str],
) -> None:
    """Attach supporting TextUnits in the graph (idempotent)."""
    await asyncio.to_thread(attach_claim_supports, claim_id, tuple(unit_ids))


async def claim_by_identity(
    session: AsyncSession,
    scope_key: str,
    identity: str,
) -> KnowledgeClaimRecord | None:
    return (
        await session.execute(
            select(KnowledgeClaimRecord)
            .where(
                KnowledgeClaimRecord.identity_key == identity,
                KnowledgeClaimRecord.scope_key == scope_key,
            )
            .order_by(KnowledgeClaimRecord.created_at, KnowledgeClaimRecord.id)
        )
    ).scalars().first()


def _reject_superseded_claim(row: KnowledgeClaimRecord) -> None:
    if row.superseded_at is not None:
        raise KnowledgeClaimError(f"claim {row.id} is superseded")


async def prune_unsupported_claims(session: AsyncSession) -> None:
    supported = select(KnowledgeClaimTextUnit.claim_id).distinct()
    rows = list(
        (
            await session.execute(
                select(KnowledgeClaimRecord).where(KnowledgeClaimRecord.id.not_in(supported))
            )
        ).scalars().all()
    )
    for row in rows:
        await session.delete(row)
    if rows:
        await session.flush()
