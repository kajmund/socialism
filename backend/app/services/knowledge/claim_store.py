"""Idempotent persist for classified domain claims."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeClaimRecord, KnowledgeClaimTextUnit
from app.services.knowledge.claims import (
    SUPPORTED_BY,
    KnowledgeClaim,
    KnowledgeClaimError,
    assert_claim_grounding_scope,
    knowledge_claim_id,
    supporting_text_unit_ids_for_claim,
)
from app.services.knowledge.events import CLAIM_ADDED, record_graph_event, utc_now
from app.services.knowledge.persistence_class import DOMAIN_KNOWLEDGE, classify_persistence
from app.services.knowledge.scope import persist_scope_fields, scope_from_row


async def persist_knowledge_claims(
    session: AsyncSession,
    claims: Sequence[KnowledgeClaim],
) -> list[KnowledgeClaimRecord]:
    return [await persist_knowledge_claim(session, claim) for claim in claims]


async def persist_knowledge_claim(
    session: AsyncSession,
    claim: KnowledgeClaim,
) -> KnowledgeClaimRecord:
    row, _reused = await persist_domain_claim(session, claim)
    return row


async def persist_domain_claim(
    session: AsyncSession,
    claim: KnowledgeClaim,
) -> tuple[KnowledgeClaimRecord, bool]:
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
    row = await claim_by_identity(session, claim.scope.scope_key, identity)
    if row is not None:
        _reject_superseded_claim(row)
        if scope_from_row(row) != claim.scope:
            raise KnowledgeClaimError(
                f"claim {row.id} already exists in a different knowledge scope"
            )
        reused = True
    else:
        row, reused = await _insert_claim(session, claim, identity)
    await attach_supporting_text_units(session, row.id, claim.supporting_text_unit_ids)
    return row, reused


async def attach_supporting_text_units(
    session: AsyncSession,
    claim_id: str,
    unit_ids: Sequence[str],
) -> None:
    existing = await supporting_text_unit_ids_for_claim(session, claim_id)
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    seen = set(existing)
    ordinal = len(existing)
    for unit_id in unit_ids:
        if unit_id in seen:
            continue
        await session.execute(
            insert(KnowledgeClaimTextUnit)
            .values(
                claim_id=claim_id,
                text_unit_id=unit_id,
                ordinal=ordinal,
                relation=SUPPORTED_BY,
            )
            .on_conflict_do_nothing(index_elements=["claim_id", "text_unit_id"])
        )
        seen.add(unit_id)
        ordinal += 1
    await session.flush()


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


async def _insert_claim(
    session: AsyncSession,
    claim: KnowledgeClaim,
    identity: str,
) -> tuple[KnowledgeClaimRecord, bool]:
    now = utc_now()
    row = KnowledgeClaimRecord(
        id=identity,
        identity_key=identity,
        predicate=claim.predicate,
        value=claim.value,
        valid_from=now,
        created_at=now,
        **persist_scope_fields(claim.scope),
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        winner = await claim_by_identity(session, claim.scope.scope_key, identity)
        if winner is None:
            raise
        _reject_superseded_claim(winner)
        return winner, True
    await record_graph_event(
        session,
        scope=claim.scope,
        event_type=CLAIM_ADDED,
        node_kind="claim",
        node_id=row.id,
        payload={"predicate": claim.predicate},
        created_at=now,
    )
    return row, False


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
