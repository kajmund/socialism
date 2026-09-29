"""Classify-then-persist boundary for durable knowledge."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.knowledge import (
    KnowledgeDecision,
    KnowledgePersistStats,
    record_knowledge_decision,
)
from app.services.knowledge.claim_store import persist_domain_claim
from app.services.knowledge.claims import (
    KnowledgeClaim,
    KnowledgeClaimError,
    document_refs_for_units,
)
from app.services.knowledge.entities import (
    KnowledgeEntity,
    persist_knowledge_entity_result,
)
from app.services.knowledge.observations import (
    KnowledgeObservation,
    ObservationSeed,
    knowledge_observation,
    persist_knowledge_observation,
)
from app.services.knowledge.persistence_class import (
    DOMAIN_KNOWLEDGE,
    PersistenceDecision,
    classify_persistence,
)
from app.services.knowledge.relationships import (
    KnowledgeRelationship,
    knowledge_relationship,
    persist_knowledge_relationship_result,
)


@dataclass(frozen=True)
class ClaimPersistResult:
    action: str
    claim_id: str | None
    observation_id: str | None
    proposed_id: str
    persistence_class: str
    reason: str


@dataclass
class ExtractedKnowledgePersistResult:
    stats: KnowledgePersistStats
    claims: list[ClaimPersistResult] = field(default_factory=list)
    claim_id_map: dict[str, str] = field(default_factory=dict)
    accepted_claim_ids: list[str] = field(default_factory=list)


def classify_claim(claim: KnowledgeClaim) -> PersistenceDecision:
    return classify_persistence(
        value=claim.value,
        declared_class=claim.persistence_class,
        declared_kind=claim.observation_kind,
    )


async def persist_extracted_claim(
    session: AsyncSession,
    claim: KnowledgeClaim,
    *,
    stats: KnowledgePersistStats | None = None,
    question_key: str = "",
) -> ClaimPersistResult:
    counters = stats or KnowledgePersistStats()
    record_knowledge_decision(
        counters, KnowledgeDecision(kind="claim", action="proposed")
    )
    decision = classify_claim(claim)
    if decision.persistence_class != DOMAIN_KNOWLEDGE:
        return await _persist_rejected_claim(
            session, claim, decision, counters=counters, question_key=question_key
        )
    row, reused = await persist_domain_claim(session, claim)
    record_knowledge_decision(
        counters,
        KnowledgeDecision(
            kind="claim",
            action="reused" if reused else "accepted",
            persistence_class=DOMAIN_KNOWLEDGE,
            reason=decision.reason,
            predicate=claim.predicate,
            identity_key=row.identity_key,
        ),
    )
    return ClaimPersistResult(
        action="reused" if reused else "accepted",
        claim_id=row.id,
        observation_id=None,
        proposed_id=claim.id,
        persistence_class=DOMAIN_KNOWLEDGE,
        reason=decision.reason,
    )


async def persist_extracted_knowledge(
    session: AsyncSession,
    *,
    claims: Sequence[KnowledgeClaim] = (),
    entities: Sequence[KnowledgeEntity] = (),
    relationships: Sequence[KnowledgeRelationship] = (),
    observations: Sequence[KnowledgeObservation] = (),
    question_key: str = "",
) -> ExtractedKnowledgePersistResult:
    counters = KnowledgePersistStats()
    results: list[ClaimPersistResult] = []
    claim_id_map: dict[str, str] = {}
    accepted_claim_ids: list[str] = []
    entity_id_map: dict[str, str] = {}
    for observation in observations:
        await _persist_observation(session, observation, counters)
    for claim in claims:
        result = await persist_extracted_claim(
            session, claim, stats=counters, question_key=question_key
        )
        results.append(result)
        if result.claim_id is not None:
            claim_id_map[result.proposed_id] = result.claim_id
            accepted_claim_ids.append(result.claim_id)
    for entity in entities:
        record_knowledge_decision(
            counters,
            KnowledgeDecision(
                kind="entity", action="proposed", entity_type=entity.entity_type
            ),
        )
        _row, reused = await persist_knowledge_entity_result(session, entity)
        entity_id_map[entity.id] = _row.id
        record_knowledge_decision(
            counters,
            KnowledgeDecision(
                kind="entity",
                action="reused" if reused else "accepted",
                entity_type=entity.entity_type,
                identity_key=entity.id,
            ),
        )
    for edge in _remap_relationships(relationships, claim_id_map, entity_id_map):
        record_knowledge_decision(
            counters,
            KnowledgeDecision(
                kind="relationship", action="proposed", relation=edge.relation
            ),
        )
        _row, reused = await persist_knowledge_relationship_result(session, edge)
        record_knowledge_decision(
            counters,
            KnowledgeDecision(
                kind="relationship",
                action="reused" if reused else "accepted",
                relation=edge.relation,
                identity_key=edge.id,
            ),
        )
    return ExtractedKnowledgePersistResult(
        stats=counters,
        claims=results,
        claim_id_map=claim_id_map,
        accepted_claim_ids=accepted_claim_ids,
    )


async def _persist_rejected_claim(
    session: AsyncSession,
    claim: KnowledgeClaim,
    decision: PersistenceDecision,
    *,
    counters: KnowledgePersistStats,
    question_key: str,
) -> ClaimPersistResult:
    observation = await _observation_from_claim(
        session, claim, decision, question_key=question_key
    )
    row, reused = await persist_knowledge_observation(session, observation)
    record_knowledge_decision(
        counters,
        KnowledgeDecision(
            kind="claim",
            action="rejected_by_class",
            persistence_class=decision.persistence_class,
            reason=decision.reason,
            predicate=claim.predicate,
            identity_key=claim.id,
        ),
    )
    record_knowledge_decision(
        counters,
        KnowledgeDecision(
            kind="observation",
            action="reused" if reused else "accepted",
            persistence_class=decision.persistence_class,
            reason=decision.kind,
            identity_key=row.id,
            document_id=observation.document_id,
        ),
    )
    return ClaimPersistResult(
        action="rejected_by_class",
        claim_id=None,
        observation_id=row.id,
        proposed_id=claim.id,
        persistence_class=decision.persistence_class,
        reason=decision.reason,
    )


async def _persist_observation(
    session: AsyncSession,
    observation: KnowledgeObservation,
    counters: KnowledgePersistStats,
) -> None:
    row, reused = await persist_knowledge_observation(session, observation)
    record_knowledge_decision(
        counters,
        KnowledgeDecision(
            kind="observation",
            action="reused" if reused else "accepted",
            persistence_class=observation.observation_class,
            reason=observation.kind,
            identity_key=row.id,
            document_id=observation.document_id,
        ),
    )


async def _observation_from_claim(
    session: AsyncSession,
    claim: KnowledgeClaim,
    decision: PersistenceDecision,
    *,
    question_key: str,
) -> KnowledgeObservation:
    refs = await document_refs_for_units(session, claim.supporting_text_unit_ids)
    if refs is None:
        raise KnowledgeClaimError(
            f"claim {claim.id} has no TextUnit document for observation"
        )
    document_id, document_version_id = refs
    return knowledge_observation(
        ObservationSeed(
            observation_class=decision.persistence_class,
            kind=decision.kind,
            document_id=document_id,
            document_version_id=document_version_id,
            statement_normalized=decision.statement_normalized or claim.predicate,
            question_key=question_key,
            extra={"predicate": claim.predicate},
        ),
        claim.scope,
    )


def _remap_relationships(
    relationships: Sequence[KnowledgeRelationship],
    claim_id_map: dict[str, str],
    entity_id_map: dict[str, str],
) -> list[KnowledgeRelationship]:
    remapped: list[KnowledgeRelationship] = []
    for edge in relationships:
        item = _remap_relationship(edge, claim_id_map, entity_id_map)
        if item is not None:
            remapped.append(item)
    return remapped


def _remap_relationship(
    edge: KnowledgeRelationship,
    claim_id_map: dict[str, str],
    entity_id_map: dict[str, str],
) -> KnowledgeRelationship | None:
    from_id = edge.from_id
    to_id = edge.to_id
    if edge.from_kind == "claim":
        if edge.from_id not in claim_id_map:
            return None
        from_id = claim_id_map[edge.from_id]
    if edge.to_kind == "claim":
        if edge.to_id not in claim_id_map:
            return None
        to_id = claim_id_map[edge.to_id]
    if edge.from_kind == "entity" and edge.from_id in entity_id_map:
        from_id = entity_id_map[edge.from_id]
    if edge.to_kind == "entity" and edge.to_id in entity_id_map:
        to_id = entity_id_map[edge.to_id]
    if from_id == edge.from_id and to_id == edge.to_id:
        return edge
    extra = dict(edge.extra)
    if edge.temporal_key:
        extra["temporal_key"] = edge.temporal_key
    return knowledge_relationship(
        customer_id=edge.customer_id,
        scope=edge.scope,
        relation=edge.relation,
        from_kind=edge.from_kind,
        from_id=from_id,
        to_kind=edge.to_kind,
        to_id=to_id,
        extra=extra,
    )
