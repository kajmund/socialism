"""One-shot rekey of claims to source-independent identity.

Runs during schema upgrade so runtime persist can look up NEW_HASH
without depending on later cleanup.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.database.knowledge_observation import KnowledgeObservationRecord
from app.database.models import (
    KnowledgeClaimAnswer,
    KnowledgeClaimRecord,
    KnowledgeClaimTextUnit,
    KnowledgeGraphEventRecord,
    KnowledgeQuestionLineage,
    KnowledgeRelationshipRecord,
    ResearchRuntimeNeed,
    TextUnitRecord,
)
from app.services.knowledge.claims import SUPPORTED_BY
from app.services.knowledge.identity import knowledge_claim_identity
from app.services.knowledge.observations import (
    KnowledgeObservationError,
    ObservationSeed,
    knowledge_observation,
)
from app.services.knowledge.persistence_class import (
    DOMAIN_KNOWLEDGE,
    PersistenceDecision,
    classify_persistence,
)
from app.services.knowledge.relationships import merge_relationship_extra
from app.services.knowledge.scope import persist_scope_fields, require_persist_scope


async def backfill_source_independent_claims(session: AsyncSession) -> None:
    await session.run_sync(rekey_claim_identities)


def rekey_claim_identities(session: Session) -> None:
    _reclassify_non_domain_claims(session)
    grouped: dict[tuple[str, str], list[KnowledgeClaimRecord]] = defaultdict(list)
    for claim in list(session.scalars(select(KnowledgeClaimRecord))):
        identity = knowledge_claim_identity(
            scope_key=claim.scope_key,
            predicate=claim.predicate,
            value=claim.value,
        )
        grouped[(claim.scope_key, identity)].append(claim)
    for (_scope_key, identity), rows in grouped.items():
        ordered = sorted(
            rows,
            key=lambda row: (row.superseded_at is not None, row.created_at, row.id),
        )
        winner = ordered[0]
        for loser in ordered[1:]:
            _merge_loser(session, winner, loser)
        winner.identity_key = identity
    session.flush()


def _reclassify_non_domain_claims(session: Session) -> None:
    for claim in list(session.scalars(select(KnowledgeClaimRecord))):
        decision = classify_persistence(value=claim.value)
        if decision.persistence_class == DOMAIN_KNOWLEDGE:
            continue
        _migrate_observation(session, claim, decision)
        session.delete(claim)
    session.flush()


def _migrate_observation(
    session: Session,
    claim: KnowledgeClaimRecord,
    decision: PersistenceDecision,
) -> None:
    support = _support_ids(session, claim.id)
    if not support:
        return
    unit = session.get(TextUnitRecord, support[0])
    if unit is None:
        return
    try:
        observation = knowledge_observation(
            ObservationSeed(
                observation_class=decision.persistence_class,
                kind=decision.kind,
                document_id=unit.document_id,
                document_version_id=unit.document_version_id,
                statement_normalized=decision.statement_normalized or claim.predicate,
                extra={"predicate": claim.predicate, "migrated_claim_id": claim.id},
            ),
            require_persist_scope(customer_id=claim.customer_id, scope_type=claim.scope_type),
        )
    except KnowledgeObservationError:
        return
    if session.get(KnowledgeObservationRecord, observation.id) is not None:
        return
    session.add(
        KnowledgeObservationRecord(
            id=observation.id,
            observation_class=observation.observation_class,
            kind=observation.kind,
            document_id=observation.document_id,
            document_version_id=observation.document_version_id,
            question_key=observation.question_key,
            statement_normalized=observation.statement_normalized,
            extra=observation.extra,
            **persist_scope_fields(observation.scope),
        )
    )


def _merge_loser(
    session: Session,
    winner: KnowledgeClaimRecord,
    loser: KnowledgeClaimRecord,
) -> None:
    _attach_support(session, winner.id, _support_ids(session, loser.id))
    _rewire_claim_references(session, loser.id, winner.id)
    session.delete(loser)


def _support_ids(session: Session, claim_id: str) -> list[str]:
    return list(
        session.scalars(
            select(KnowledgeClaimTextUnit.text_unit_id)
            .where(KnowledgeClaimTextUnit.claim_id == claim_id)
            .order_by(KnowledgeClaimTextUnit.ordinal, KnowledgeClaimTextUnit.text_unit_id)
        )
    )


def _attach_support(session: Session, claim_id: str, unit_ids: list[str]) -> None:
    seen = set(_support_ids(session, claim_id))
    ordinal = len(seen)
    for unit_id in unit_ids:
        if unit_id in seen:
            continue
        session.add(
            KnowledgeClaimTextUnit(
                claim_id=claim_id,
                text_unit_id=unit_id,
                ordinal=ordinal,
                relation=SUPPORTED_BY,
            )
        )
        seen.add(unit_id)
        ordinal += 1


def _rewire_claim_references(session: Session, loser_id: str, winner_id: str) -> None:
    winner_needs = set(
        session.scalars(
            select(KnowledgeClaimAnswer.research_need_id).where(
                KnowledgeClaimAnswer.claim_id == winner_id
            )
        )
    )
    for answer in list(
        session.scalars(
            select(KnowledgeClaimAnswer).where(KnowledgeClaimAnswer.claim_id == loser_id)
        )
    ):
        if answer.research_need_id in winner_needs:
            session.delete(answer)
        else:
            answer.claim_id = winner_id
    session.execute(
        update(KnowledgeQuestionLineage)
        .where(KnowledgeQuestionLineage.trigger_claim_id == loser_id)
        .values(trigger_claim_id=winner_id)
    )
    session.execute(
        update(ResearchRuntimeNeed)
        .where(ResearchRuntimeNeed.trigger_claim_id == loser_id)
        .values(trigger_claim_id=winner_id)
    )
    session.execute(
        update(KnowledgeClaimRecord)
        .where(KnowledgeClaimRecord.successor_id == loser_id)
        .values(successor_id=winner_id)
    )
    _rewire_node(session, "claim", loser_id, winner_id)


def _rewire_node(session: Session, kind: str, loser_id: str, winner_id: str) -> None:
    edges = list(
        session.scalars(
            select(KnowledgeRelationshipRecord).where(
                or_(
                    (
                        (KnowledgeRelationshipRecord.from_kind == kind)
                        & (KnowledgeRelationshipRecord.from_id == loser_id)
                    ),
                    (
                        (KnowledgeRelationshipRecord.to_kind == kind)
                        & (KnowledgeRelationshipRecord.to_id == loser_id)
                    ),
                )
            )
        )
    )
    for edge in edges:
        _rewire_edge(session, edge, kind=kind, loser_id=loser_id, winner_id=winner_id)
    _rewire_graph_events(session, kind, loser_id, winner_id)


def _rewire_edge(
    session: Session,
    edge: KnowledgeRelationshipRecord,
    *,
    kind: str,
    loser_id: str,
    winner_id: str,
) -> None:
    new_from = winner_id if edge.from_kind == kind and edge.from_id == loser_id else edge.from_id
    new_to = winner_id if edge.to_kind == kind and edge.to_id == loser_id else edge.to_id
    if new_from == edge.from_id and new_to == edge.to_id:
        return
    existing = session.scalars(
        select(KnowledgeRelationshipRecord).where(
            KnowledgeRelationshipRecord.scope_key == edge.scope_key,
            KnowledgeRelationshipRecord.relation == edge.relation,
            KnowledgeRelationshipRecord.from_kind == edge.from_kind,
            KnowledgeRelationshipRecord.from_id == new_from,
            KnowledgeRelationshipRecord.to_kind == edge.to_kind,
            KnowledgeRelationshipRecord.to_id == new_to,
            KnowledgeRelationshipRecord.temporal_key == (edge.temporal_key or ""),
        )
    ).first()
    if existing is not None and existing.id != edge.id:
        existing.extra = merge_relationship_extra(existing.extra, edge.extra)
        _rewire_graph_events(session, "relationship", edge.id, existing.id)
        session.delete(edge)
        return
    edge.from_id = new_from
    edge.to_id = new_to
    session.flush()


def _rewire_graph_events(session: Session, kind: str, loser_id: str, winner_id: str) -> None:
    session.execute(
        update(KnowledgeGraphEventRecord)
        .where(
            KnowledgeGraphEventRecord.node_kind == kind,
            KnowledgeGraphEventRecord.node_id == loser_id,
        )
        .values(node_id=winner_id)
    )
    session.execute(
        update(KnowledgeGraphEventRecord)
        .where(KnowledgeGraphEventRecord.related_id == loser_id)
        .values(related_id=winner_id)
    )
