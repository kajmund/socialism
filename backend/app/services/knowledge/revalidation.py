"""Revalidate frozen EvidenceSets when the graph changes. Snapshots stay immutable."""

from __future__ import annotations

import hashlib
import logging
import math
import time
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
    KnowledgeClaimRecord,
    KnowledgeClaimTextUnit,
    KnowledgeGraphEventRecord,
    KnowledgeQuestionRow,
    KnowledgeRelationshipRecord,
    TextUnitRecord,
)
from app.jev.evaluation import (
    EVALUATOR_GRAPH_REVALIDATION,
    EVALUATOR_GRAPH_REVALIDATION_POLICY,
    EVALUATOR_GRAPH_REVALIDATION_VERSION,
    EvaluationRequest,
    threshold_config,
)
from app.jev.service import build_request, evaluate_many
from app.jev.system import JevSystemOne
from app.observability.research import record_graph_revalidation
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

logger = logging.getLogger(__name__)

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
        "True if this document version can materially change the frozen evidence set. "
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
    if not _impact_has_keys(impact):
        return []
    rows = await _frozen_provenance_rows(session, customer_id)
    return _sets_touching_impact(rows, impact)


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
    """Judge whether a document version can change each frozen evidence set it touches."""
    return await revalidate_after_events(session, [event], jev=jev)


async def revalidate_after_events(
    session: AsyncSession,
    events: Sequence[KnowledgeGraphEventRecord | str],
    *,
    jev: JevSystemOne,
) -> list[RevalidationDecision]:
    """One material_change call per affected evidence set. The connection is released first."""
    if not events:
        return []
    started = time.perf_counter()
    loaded: list[KnowledgeGraphEventRecord] = []
    seen: set[str] = set()
    for event in events:
        row = (
            event
            if isinstance(event, KnowledgeGraphEventRecord)
            else await session.get(KnowledgeGraphEventRecord, event)
        )
        if row is None:
            raise RevalidationError("graph event is missing")
        if row.id in seen:
            continue
        seen.add(row.id)
        loaded.append(row)
    planned: list[_PlannedRevalidation] = []
    provenance_by_customer: dict[int, Sequence[tuple[EvidenceSet, object]]] = {}
    for row in loaded:
        impact = await graph_impact_from_event(session, row)
        event_scope = scope_from_row(row)
        if event_scope.scope_type == SCOPE_CUSTOMER and event_scope.customer_id is None:
            raise KnowledgeScopeError("customer graph event is missing customer_id")
        if not _impact_has_keys(impact):
            continue
        customer_id = event_scope.customer_id
        if customer_id is None:
            raise KnowledgeScopeError("revalidation of customer graph events requires customer_id")
        if customer_id not in provenance_by_customer:
            provenance_by_customer[customer_id] = await _frozen_provenance_rows(
                session, customer_id
            )
        sets = _sets_touching_impact(provenance_by_customer[customer_id], impact)
        if not sets:
            continue
        planned.append(
            _PlannedRevalidation(
                event_id=row.id,
                impact=impact,
                evidence_set_ids=tuple(item.id for item in sets),
                question_key=impact.question_keys[0] if impact.question_keys else None,
                knowledge_question_id=await _knowledge_question_id(
                    session, impact.question_keys, event_scope
                ),
                security_scope=event_scope.scope_key,
            )
        )
    # One material_change per (document version, evidence set, validation version).
    # Provenance is already in memory. JEV must not keep the connection.
    lookup_started = time.perf_counter()
    claim_versions, unit_versions = await _version_index(session, planned)
    judgments = _group_set_judgments(planned, claim_versions, unit_versions)
    requests = [
        material_change_request(
            document_version_id=judgment.document_version_id,
            evidence_set_id=judgment.evidence_set_id,
            security_scope=judgment.security_scope,
        )
        for judgment in judgments
    ]
    lookup_ms = (time.perf_counter() - lookup_started) * 1000
    jev_started = time.perf_counter()
    outcomes = await evaluate_many(
        jev,
        requests,
        session=session,
        timeout_seconds=settings.jev_timeout_seconds,
        required_signals=("material_change",),
        pool="graph_revalidation",
        before_http=lambda: _release_db_connection(session),
    )
    jev_ms = (time.perf_counter() - jev_started) * 1000
    persist_started = time.perf_counter()
    decisions: list[RevalidationDecision] = []
    skipped = 0
    for judgment, outcome in zip(judgments, outcomes, strict=True):
        if outcome.reused:
            skipped += 1
            logger.info(
                "graph_revalidation_skipped_processed document_version_id=%s "
                "evidence_set_id=%s security_scope=%s evaluation_key=%s",
                judgment.document_version_id,
                judgment.evidence_set_id,
                outcome.artifact.security_scope if outcome.artifact is not None else "",
                outcome.artifact.evaluation_key if outcome.artifact is not None else "",
            )
        if outcome.artifact is None:
            noul = None
            state = REVALIDATION_UNKNOWN
        else:
            noul = outcome.artifact.signals["material_change"]
            state = classify_revalidation_state(
                noul,
                impact_threshold=settings.revalidation_impact_threshold,
                clear_threshold=settings.revalidation_clear_threshold,
            )
        await _persist_revalidation(
            session,
            evidence_set_id=judgment.evidence_set_id,
            graph_event_id=judgment.anchor_event_id,
            question_key=judgment.question_key,
            knowledge_question_id=judgment.knowledge_question_id,
            state=state,
            impact_noul=noul,
        )
        decisions.append(
            RevalidationDecision(
                evidence_set_id=judgment.evidence_set_id,
                graph_event_id=judgment.anchor_event_id,
                state=state,
                impact_noul=noul,
                question_key=judgment.question_key,
                knowledge_question_id=judgment.knowledge_question_id,
            )
        )
    await _release_db_connection(session)
    persist_ms = (time.perf_counter() - persist_started) * 1000
    record_graph_revalidation(
        candidates=len(loaded),
        skipped=skipped,
        jev_required=len(judgments) - skipped,
        completed=len(judgments),
        total_ms=(time.perf_counter() - started) * 1000,
        lookup_ms=lookup_ms,
        jev_ms=jev_ms,
        persistence_ms=persist_ms,
    )
    return decisions


@dataclass(frozen=True)
class _PlannedRevalidation:
    event_id: str
    impact: GraphImpact
    evidence_set_ids: tuple[str, ...]
    question_key: str | None
    knowledge_question_id: str | None
    security_scope: str


@dataclass(frozen=True)
class _SetJudgment:
    document_version_id: str
    evidence_set_id: str
    anchor_event_id: str
    question_key: str | None
    knowledge_question_id: str | None
    security_scope: str


def _impact_has_keys(impact: GraphImpact) -> bool:
    return bool(impact.question_keys or impact.claim_ids or impact.text_unit_ids)


async def _frozen_provenance_rows(
    session: AsyncSession,
    customer_id: int | None,
) -> list[tuple[EvidenceSet, object]]:
    if customer_id is None:
        raise KnowledgeScopeError("revalidation of customer graph events requires customer_id")
    # EvidenceSetItem entities select-in passages, domain results, raw sources and claims.
    rows = await session.execute(
        select(EvidenceSet, EvidenceSetItem.provenance)
        .join(ExecutionRun, ExecutionRun.id == EvidenceSet.run_id)
        .join(EvidenceSetItem, EvidenceSetItem.evidence_set_id == EvidenceSet.id)
        .where(
            EvidenceSet.status == "frozen",
            ExecutionRun.customer_id == customer_id,
        )
    )
    return list(rows.all())


def _sets_touching_impact(
    rows: Sequence[tuple[EvidenceSet, object]],
    impact: GraphImpact,
) -> list[EvidenceSet]:
    affected: dict[str, EvidenceSet] = {}
    for evidence_set, provenance in rows:
        if evidence_set.id not in affected and _provenance_touches_impact(provenance, impact):
            affected[evidence_set.id] = evidence_set
    return list(affected.values())


async def _release_db_connection(session: AsyncSession) -> None:
    if session.in_transaction():
        await session.commit()


def _provenance_touches_impact(provenance: object, impact: GraphImpact) -> bool:
    provenance = provenance if isinstance(provenance, dict) else {}
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


def material_change_validation_version() -> str:
    """Evaluator definition that may cause a new material_change call."""
    return "|".join(
        (
            EVALUATOR_GRAPH_REVALIDATION,
            EVALUATOR_GRAPH_REVALIDATION_VERSION,
            EVALUATOR_GRAPH_REVALIDATION_POLICY,
            settings.jev_model,
            f"{settings.revalidation_impact_threshold:.6f}",
            f"{settings.revalidation_clear_threshold:.6f}",
        )
    )


def material_change_state(*, document_version_id: str, evidence_set_id: str) -> dict[str, str]:
    """The only fields that distinguish one material_change call from another."""
    return {
        "document_version_id": document_version_id,
        "evidence_set_id": evidence_set_id,
        "validation_version": material_change_validation_version(),
    }


def material_change_request(
    *,
    document_version_id: str,
    evidence_set_id: str,
    security_scope: str,
) -> EvaluationRequest:
    return build_request(
        evaluator_id=EVALUATOR_GRAPH_REVALIDATION,
        evaluator_version=EVALUATOR_GRAPH_REVALIDATION_VERSION,
        model=settings.jev_model,
        questions={"material_change": _IMPACT_QUESTION},
        state=material_change_state(
            document_version_id=document_version_id,
            evidence_set_id=evidence_set_id,
        ),
        security_scope=security_scope,
        policy_version=EVALUATOR_GRAPH_REVALIDATION_POLICY,
        model_config=threshold_config(
            impact_threshold=settings.revalidation_impact_threshold,
            clear_threshold=settings.revalidation_clear_threshold,
        ),
    )


async def _version_index(
    session: AsyncSession,
    planned: Sequence[_PlannedRevalidation],
) -> tuple[dict[str, str], dict[str, str]]:
    claim_ids = sorted({claim_id for plan in planned for claim_id in plan.impact.claim_ids})
    unit_ids = sorted({unit_id for plan in planned for unit_id in plan.impact.text_unit_ids})
    claim_versions: dict[str, str] = {}
    if claim_ids:
        rows = (
            await session.execute(
                select(
                    KnowledgeClaimRecord.id,
                    KnowledgeClaimRecord.document_version_id,
                ).where(KnowledgeClaimRecord.id.in_(claim_ids))
            )
        ).all()
        claim_versions = {row[0]: row[1] for row in rows if row[1]}
    unit_versions: dict[str, str] = {}
    if unit_ids:
        rows = (
            await session.execute(
                select(TextUnitRecord.id, TextUnitRecord.document_version_id).where(
                    TextUnitRecord.id.in_(unit_ids)
                )
            )
        ).all()
        unit_versions = {row[0]: row[1] for row in rows if row[1]}
    return claim_versions, unit_versions


def _plan_versions(
    plan: _PlannedRevalidation,
    claim_versions: dict[str, str],
    unit_versions: dict[str, str],
) -> tuple[str, ...]:
    versions: list[str] = []
    for claim_id in plan.impact.claim_ids:
        version_id = claim_versions.get(claim_id)
        if version_id and version_id not in versions:
            versions.append(version_id)
    if not versions:
        for unit_id in plan.impact.text_unit_ids:
            version_id = unit_versions.get(unit_id)
            if version_id and version_id not in versions:
                versions.append(version_id)
    if versions:
        return tuple(versions)
    return (f"unversioned:{plan.event_id}",)


def _group_set_judgments(
    planned: Sequence[_PlannedRevalidation],
    claim_versions: dict[str, str],
    unit_versions: dict[str, str],
) -> list[_SetJudgment]:
    grouped: dict[tuple[str, str, str], _SetJudgment] = {}
    for plan in planned:
        for version_id in _plan_versions(plan, claim_versions, unit_versions):
            for evidence_set_id in plan.evidence_set_ids:
                key = (plan.security_scope, version_id, evidence_set_id)
                current = grouped.get(key)
                if current is not None and plan.event_id >= current.anchor_event_id:
                    continue
                grouped[key] = _SetJudgment(
                    document_version_id=version_id,
                    evidence_set_id=evidence_set_id,
                    anchor_event_id=plan.event_id,
                    question_key=plan.question_key,
                    knowledge_question_id=plan.knowledge_question_id,
                    security_scope=plan.security_scope,
                )
    return sorted(
        grouped.values(),
        key=lambda item: (
            item.security_scope,
            item.document_version_id,
            item.evidence_set_id,
        ),
    )


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
        if existing.state == state and existing.impact_noul == impact_noul:
            return existing
        existing.state = state
        existing.impact_noul = impact_noul
        await session.flush()
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
