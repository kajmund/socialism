"""Dry-run audit and explicit cleanup for knowledge-graph duplicates."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.knowledge_observation import KnowledgeObservationRecord
from app.database.models import (
    KnowledgeClaimAnswer,
    KnowledgeClaimRecord,
    KnowledgeClaimTextUnit,
    KnowledgeEntityRecord,
    KnowledgeGraphEventRecord,
    KnowledgeQuestionLineage,
    KnowledgeRelationshipRecord,
    ResearchRuntimeNeed,
)
from app.observability.knowledge import (
    KnowledgeDecision,
    KnowledgePersistStats,
    record_knowledge_decision,
)
from app.services.knowledge.claim_store import attach_supporting_text_units
from app.services.knowledge.identity import knowledge_claim_identity, normalize_assertion_text
from app.services.knowledge.relationships import merge_relationship_extra
from app.services.knowledge.observations import (
    ObservationSeed,
    knowledge_observation,
    persist_knowledge_observation,
)
from app.services.knowledge.scope import require_persist_scope
from app.services.knowledge.persistence_class import (
    DOMAIN_KNOWLEDGE,
    classify_persistence,
)


@dataclass
class DuplicateGroup:
    key: str
    winner_id: str
    loser_ids: list[str]
    count: int


@dataclass
class KnowledgeAuditReport:
    exact_duplicate_claims: list[DuplicateGroup] = field(default_factory=list)
    normalizable_duplicate_claims: list[DuplicateGroup] = field(default_factory=list)
    duplicate_entities: list[DuplicateGroup] = field(default_factory=list)
    duplicate_relationships: list[DuplicateGroup] = field(default_factory=list)
    source_quality_claim_count: int = 0
    research_observation_claim_count: int = 0
    domain_claim_count: int = 0
    observation_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "exact_duplicate_claims": [group.__dict__ for group in self.exact_duplicate_claims],
            "normalizable_duplicate_claims": [
                group.__dict__ for group in self.normalizable_duplicate_claims
            ],
            "duplicate_entities": [group.__dict__ for group in self.duplicate_entities],
            "duplicate_relationships": [group.__dict__ for group in self.duplicate_relationships],
            "source_quality_claim_count": self.source_quality_claim_count,
            "research_observation_claim_count": self.research_observation_claim_count,
            "domain_claim_count": self.domain_claim_count,
            "observation_count": self.observation_count,
        }


async def audit_knowledge_graph(session: AsyncSession) -> KnowledgeAuditReport:
    claims = list(
        (await session.execute(select(KnowledgeClaimRecord))).scalars().all()
    )
    entities = list(
        (await session.execute(select(KnowledgeEntityRecord))).scalars().all()
    )
    edges = list(
        (await session.execute(select(KnowledgeRelationshipRecord))).scalars().all()
    )
    observations = (
        await session.execute(select(KnowledgeObservationRecord.id))
    ).all()
    report = KnowledgeAuditReport(observation_count=len(observations))
    exact: dict[str, list[KnowledgeClaimRecord]] = defaultdict(list)
    normalized: dict[str, list[KnowledgeClaimRecord]] = defaultdict(list)
    for claim in claims:
        decision = classify_persistence(value=claim.value)
        if decision.persistence_class == "source_quality":
            report.source_quality_claim_count += 1
        elif decision.persistence_class == "research_observation":
            report.research_observation_claim_count += 1
        else:
            report.domain_claim_count += 1
        exact_key = "|".join((claim.scope_key, claim.predicate, str(claim.value)))
        exact[exact_key].append(claim)
        identity = knowledge_claim_identity(
            scope_key=claim.scope_key,
            predicate=claim.predicate,
            value=claim.value,
        )
        normalized[f"{claim.scope_key}|{identity}"].append(claim)
    report.exact_duplicate_claims = _groups(exact)
    report.normalizable_duplicate_claims = _groups(normalized)
    entity_groups: dict[str, list[KnowledgeEntityRecord]] = defaultdict(list)
    for entity in entities:
        key = f"{entity.scope_key}|{entity.entity_type}|{normalize_assertion_text(entity.entity_key)}"
        entity_groups[key].append(entity)
    report.duplicate_entities = _groups(entity_groups)
    edge_groups: dict[str, list[KnowledgeRelationshipRecord]] = defaultdict(list)
    for edge in edges:
        stamp = getattr(edge, "temporal_key", "") or ""
        key = "|".join(
            (
                edge.scope_key,
                edge.relation,
                edge.from_kind,
                edge.from_id,
                edge.to_kind,
                edge.to_id,
                stamp,
            )
        )
        edge_groups[key].append(edge)
    report.duplicate_relationships = _groups(edge_groups)
    return report


async def cleanup_knowledge_graph(
    session: AsyncSession,
    *,
    apply: bool,
) -> dict[str, Any]:
    report = await audit_knowledge_graph(session)
    payload = report.as_dict()
    payload["applied"] = False
    payload["stats"] = KnowledgePersistStats().as_dict()
    if not apply:
        return payload
    stats = KnowledgePersistStats()
    await _reclassify_non_domain_claims(session, stats)
    await _merge_claim_groups(session, report.normalizable_duplicate_claims, stats)
    await _merge_entity_groups(session, report.duplicate_entities)
    await _merge_relationship_groups(session, report.duplicate_relationships)
    await session.flush()
    payload = (await audit_knowledge_graph(session)).as_dict()
    payload["applied"] = True
    payload["stats"] = stats.as_dict()
    return payload


def _groups(buckets: dict[str, list[Any]]) -> list[DuplicateGroup]:
    groups: list[DuplicateGroup] = []
    for key, rows in buckets.items():
        if len(rows) < 2:
            continue
        ordered = sorted(rows, key=lambda row: (row.created_at, row.id))
        groups.append(
            DuplicateGroup(
                key=key,
                winner_id=ordered[0].id,
                loser_ids=[row.id for row in ordered[1:]],
                count=len(ordered),
            )
        )
    return groups


async def _reclassify_non_domain_claims(
    session: AsyncSession,
    stats: KnowledgePersistStats,
) -> None:
    claims = list(
        (await session.execute(select(KnowledgeClaimRecord))).scalars().all()
    )
    for claim in claims:
        decision = classify_persistence(value=claim.value)
        if decision.persistence_class == DOMAIN_KNOWLEDGE:
            continue
        observation = knowledge_observation(
            ObservationSeed(
                observation_class=decision.persistence_class,
                kind=decision.kind,
                document_id=claim.document_id,
                document_version_id=claim.document_version_id,
                statement_normalized=decision.statement_normalized or claim.predicate,
                extra={"predicate": claim.predicate, "migrated_claim_id": claim.id},
            ),
            require_persist_scope(customer_id=claim.customer_id, scope_type=claim.scope_type),
        )
        await persist_knowledge_observation(session, observation)
        await _delete_claim(session, claim.id)
        record_knowledge_decision(
            stats,
            KnowledgeDecision(
                kind="claim",
                action="rejected_by_class",
                persistence_class=decision.persistence_class,
                reason="cleanup_reclassify",
                predicate=claim.predicate,
                identity_key=claim.id,
                document_id=claim.document_id,
            ),
        )


async def _merge_claim_groups(
    session: AsyncSession,
    groups: SequenceLike,
    stats: KnowledgePersistStats,
) -> None:
    for group in groups:
        winner = await session.get(KnowledgeClaimRecord, group.winner_id)
        if winner is None:
            continue
        for loser_id in group.loser_ids:
            loser = await session.get(KnowledgeClaimRecord, loser_id)
            if loser is None:
                continue
            support = [
                row[0]
                for row in (
                    await session.execute(
                        select(KnowledgeClaimTextUnit.text_unit_id).where(
                            KnowledgeClaimTextUnit.claim_id == loser_id
                        )
                    )
                ).all()
            ]
            await attach_supporting_text_units(session, winner.id, support)
            await _rewire_claim_references(session, loser_id, winner.id)
            await _delete_claim(session, loser_id)
            record_knowledge_decision(
                stats,
                KnowledgeDecision(
                    kind="claim",
                    action="merged",
                    identity_key=winner.identity_key,
                    document_id=winner.document_id,
                    predicate=winner.predicate,
                ),
            )
        winner.identity_key = knowledge_claim_identity(
            scope_key=winner.scope_key,
            predicate=winner.predicate,
            value=winner.value,
        )


async def _merge_entity_groups(session: AsyncSession, groups: SequenceLike) -> None:
    for group in groups:
        winner = await session.get(KnowledgeEntityRecord, group.winner_id)
        if winner is None:
            continue
        for loser_id in group.loser_ids:
            loser = await session.get(KnowledgeEntityRecord, loser_id)
            if loser is None:
                continue
            winner.extra = merge_relationship_extra(winner.extra, loser.extra)
            await _rewire_node(session, "entity", loser_id, group.winner_id)
            await session.delete(loser)


async def _merge_relationship_groups(session: AsyncSession, groups: SequenceLike) -> None:
    for group in groups:
        for loser_id in group.loser_ids:
            row = await session.get(KnowledgeRelationshipRecord, loser_id)
            if row is not None:
                await session.delete(row)


async def _rewire_claim_references(session: AsyncSession, loser_id: str, winner_id: str) -> None:
    winner_needs = {
        row[0]
        for row in (
            await session.execute(
                select(KnowledgeClaimAnswer.research_need_id).where(
                    KnowledgeClaimAnswer.claim_id == winner_id
                )
            )
        ).all()
    }
    loser_answers = list(
        (
            await session.execute(
                select(KnowledgeClaimAnswer).where(KnowledgeClaimAnswer.claim_id == loser_id)
            )
        ).scalars().all()
    )
    for answer in loser_answers:
        if answer.research_need_id in winner_needs:
            await session.delete(answer)
        else:
            answer.claim_id = winner_id
    await session.execute(
        update(KnowledgeQuestionLineage)
        .where(KnowledgeQuestionLineage.trigger_claim_id == loser_id)
        .values(trigger_claim_id=winner_id)
    )
    await session.execute(
        update(ResearchRuntimeNeed)
        .where(ResearchRuntimeNeed.trigger_claim_id == loser_id)
        .values(trigger_claim_id=winner_id)
    )
    await session.execute(
        update(KnowledgeClaimRecord)
        .where(KnowledgeClaimRecord.successor_id == loser_id)
        .values(successor_id=winner_id)
    )
    await _rewire_node(session, "claim", loser_id, winner_id)


async def _rewire_node(session: AsyncSession, kind: str, loser_id: str, winner_id: str) -> None:
    edges = list(
        (
            await session.execute(
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
        ).scalars().all()
    )
    for edge in edges:
        await _rewire_edge(session, edge, kind=kind, loser_id=loser_id, winner_id=winner_id)
    await _rewire_graph_events(session, kind, loser_id, winner_id)


async def _rewire_edge(
    session: AsyncSession,
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
    existing = await _edge_for_tuple(session, edge, from_id=new_from, to_id=new_to)
    if existing is not None and existing.id != edge.id:
        existing.extra = merge_relationship_extra(existing.extra, edge.extra)
        await _rewire_graph_events(session, "relationship", edge.id, existing.id)
        await session.delete(edge)
        return
    edge.from_id = new_from
    edge.to_id = new_to
    await session.flush()


async def _edge_for_tuple(
    session: AsyncSession,
    edge: KnowledgeRelationshipRecord,
    *,
    from_id: str,
    to_id: str,
) -> KnowledgeRelationshipRecord | None:
    return (
        await session.execute(
            select(KnowledgeRelationshipRecord).where(
                KnowledgeRelationshipRecord.scope_key == edge.scope_key,
                KnowledgeRelationshipRecord.relation == edge.relation,
                KnowledgeRelationshipRecord.from_kind == edge.from_kind,
                KnowledgeRelationshipRecord.from_id == from_id,
                KnowledgeRelationshipRecord.to_kind == edge.to_kind,
                KnowledgeRelationshipRecord.to_id == to_id,
                KnowledgeRelationshipRecord.temporal_key == (edge.temporal_key or ""),
            )
        )
    ).scalars().first()


async def _rewire_graph_events(
    session: AsyncSession,
    kind: str,
    loser_id: str,
    winner_id: str,
) -> None:
    await session.execute(
        update(KnowledgeGraphEventRecord)
        .where(
            KnowledgeGraphEventRecord.node_kind == kind,
            KnowledgeGraphEventRecord.node_id == loser_id,
        )
        .values(node_id=winner_id)
    )
    await session.execute(
        update(KnowledgeGraphEventRecord)
        .where(KnowledgeGraphEventRecord.related_id == loser_id)
        .values(related_id=winner_id)
    )


async def _delete_claim(session: AsyncSession, claim_id: str) -> None:
    row = await session.get(KnowledgeClaimRecord, claim_id)
    if row is not None:
        await session.delete(row)


SequenceLike = list[DuplicateGroup]
