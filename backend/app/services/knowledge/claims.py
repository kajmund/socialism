"""Domain-neutral claims grounded in TextUnits.

A claim is an assertion. Support is SUPPORTED_BY one or more TextUnits.
Adapters choose predicate strings; this module does not interpret them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    CanonicalDocumentRecord,
    KnowledgeClaimAnswer,
    KnowledgeClaimRecord,
    KnowledgeClaimTextUnit,
    KnowledgeQuestionRow,
    TextUnitRecord,
)
from app.services.knowledge.events import (
    CLAIM_ADDED,
    CLAIM_SUPERSEDED,
    record_graph_event,
    utc_now,
)
from app.services.knowledge.scope import (
    SCOPE_CUSTOMER,
    KnowledgeScopeError,
    KnowledgeTenantScope,
    assert_not_promoted,
    persist_scope_fields,
    require_persist_scope,
    scope_from_row,
    visible_to,
    visible_to_customer_clause,
)

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
    document_id: str
    document_version_id: str
    predicate: str
    value: dict[str, object]
    supporting_text_unit_ids: tuple[str, ...]
    scope_type: str = SCOPE_CUSTOMER

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
    document_version_id: str,
    predicate: str,
    value: dict[str, object],
) -> str:
    payload = f"{document_version_id}\0{predicate}\0{_canonical_json(value)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


async def persist_knowledge_claims(
    session: AsyncSession,
    claims: Sequence[KnowledgeClaim],
) -> list[KnowledgeClaimRecord]:
    rows: list[KnowledgeClaimRecord] = []
    for claim in claims:
        rows.append(await persist_knowledge_claim(session, claim))
    return rows


async def persist_knowledge_claim(
    session: AsyncSession,
    claim: KnowledgeClaim,
) -> KnowledgeClaimRecord:
    if not claim.supporting_text_unit_ids:
        raise KnowledgeClaimError(f"claim {claim.id} has no SUPPORTED_BY TextUnits")
    row = await session.get(KnowledgeClaimRecord, claim.id)
    if row is not None and row.superseded_at is not None:
        raise KnowledgeClaimError(f"claim {claim.id} is superseded")
    await _assert_claim_grounding_scope(session, claim)
    if row is None:
        now = utc_now()
        row = KnowledgeClaimRecord(
            id=claim.id,
            document_id=claim.document_id,
            document_version_id=claim.document_version_id,
            predicate=claim.predicate,
            value=claim.value,
            valid_from=now,
            created_at=now,
            **persist_scope_fields(claim.scope),
        )
        session.add(row)
        await session.flush()
        await record_graph_event(
            session,
            scope=claim.scope,
            event_type=CLAIM_ADDED,
            node_kind="claim",
            node_id=claim.id,
            payload={"predicate": claim.predicate},
            created_at=now,
        )
    elif scope_from_row(row) != claim.scope:
        raise KnowledgeClaimError(
            f"claim {claim.id} already exists in a different knowledge scope"
        )
    await session.execute(
        delete(KnowledgeClaimTextUnit).where(KnowledgeClaimTextUnit.claim_id == claim.id)
    )
    for ordinal, unit_id in enumerate(claim.supporting_text_unit_ids):
        session.add(
            KnowledgeClaimTextUnit(
                claim_id=claim.id,
                text_unit_id=unit_id,
                ordinal=ordinal,
                relation=SUPPORTED_BY,
            )
        )
    await session.flush()
    return row


async def supersede_knowledge_claim(
    session: AsyncSession,
    claim_id: str,
    *,
    successor: KnowledgeClaim | None = None,
    at: datetime | None = None,
    valid_to: datetime | None = None,
) -> KnowledgeClaimRecord:
    """Close valid/system time on a claim. History stays queryable."""
    row = await session.get(KnowledgeClaimRecord, claim_id)
    if row is None:
        raise KnowledgeClaimError(f"claim {claim_id} is missing")
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
    existing = {
        row[0]
        for row in (
            await session.execute(
                select(KnowledgeClaimAnswer.claim_id).where(
                    KnowledgeClaimAnswer.research_need_id == research_need_id,
                    KnowledgeClaimAnswer.claim_id.in_(list(claim_ids)),
                )
            )
        ).all()
    }
    for claim_id in claim_ids:
        if claim_id in existing:
            continue
        session.add(
            KnowledgeClaimAnswer(
                claim_id=claim_id,
                research_need_id=research_need_id,
                question_key=question_key,
                source_type=source_type,
                knowledge_question_id=question_id,
                relation=ANSWERED_BY,
                **persist_scope_fields(claim_scope),
            )
        )
    await session.flush()


async def claim_answers_for_question_key(
    session: AsyncSession,
    *,
    customer_id: int,
    question_key: str,
) -> list[KnowledgeClaimAnswerHit]:
    """Reuse: grounded claims that already answer this question key."""
    rows = (
        await session.execute(
            select(KnowledgeClaimRecord, KnowledgeClaimAnswer)
            .join(
                KnowledgeClaimAnswer,
                KnowledgeClaimAnswer.claim_id == KnowledgeClaimRecord.id,
            )
            .where(
                visible_to_customer_clause(
                    KnowledgeClaimRecord.scope_type,
                    KnowledgeClaimRecord.customer_id,
                    customer_id,
                ),
                visible_to_customer_clause(
                    KnowledgeClaimAnswer.scope_type,
                    KnowledgeClaimAnswer.customer_id,
                    customer_id,
                ),
                KnowledgeClaimRecord.superseded_at.is_(None),
                KnowledgeClaimAnswer.question_key == question_key,
                KnowledgeClaimAnswer.relation == ANSWERED_BY,
            )
            .order_by(KnowledgeClaimRecord.predicate, KnowledgeClaimRecord.id)
        )
    ).all()
    seen: set[str] = set()
    hits: list[KnowledgeClaimAnswerHit] = []
    for record, answer in rows:
        if record.id in seen:
            continue
        if not answer.source_type.strip():
            raise KnowledgeClaimError(
                f"ANSWERED_BY row for claim {record.id} is missing source_type"
            )
        seen.add(record.id)
        support = await supporting_text_unit_ids_for_claim(session, record.id)
        if not support:
            raise KnowledgeClaimError(f"claim {record.id} has no SUPPORTED_BY TextUnits")
        hits.append(
            KnowledgeClaimAnswerHit(
                claim=KnowledgeClaim(
                    id=record.id,
                    customer_id=scope_from_row(record).customer_id,
                    scope_type=scope_from_row(record).scope_type,
                    document_id=record.document_id,
                    document_version_id=record.document_version_id,
                    predicate=record.predicate,
                    value=record.value,
                    supporting_text_unit_ids=tuple(support),
                ),
                source_type=answer.source_type,
                knowledge_question_id=answer.knowledge_question_id,
                created_at=record.created_at,
            )
        )
    return hits


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
    row = await session.get(KnowledgeClaimRecord, claim_id)
    if row is None:
        raise KnowledgeClaimError(f"claim {claim_id} is missing")
    return scope_from_row(row)


async def _assert_claim_grounding_scope(
    session: AsyncSession,
    claim: KnowledgeClaim,
) -> None:
    document = await session.get(CanonicalDocumentRecord, claim.document_id)
    if document is None:
        raise KnowledgeClaimError(f"claim {claim.id} document {claim.document_id} is missing")
    document_scope = scope_from_row(document)
    try:
        assert_not_promoted(source=document_scope, target=claim.scope)
    except KnowledgeScopeError as exc:
        raise KnowledgeClaimError(str(exc)) from exc
    if document_scope.scope_type == SCOPE_CUSTOMER and claim.scope != document_scope:
        raise KnowledgeClaimError("customer claim must stay in the document tenant scope")
    for unit_id in claim.supporting_text_unit_ids:
        unit = await session.get(TextUnitRecord, unit_id)
        if unit is None:
            raise KnowledgeClaimError(f"SUPPORTED_BY TextUnit {unit_id} is missing")
        unit_scope = scope_from_row(unit)
        try:
            assert_not_promoted(source=unit_scope, target=claim.scope)
        except KnowledgeScopeError as exc:
            raise KnowledgeClaimError(str(exc)) from exc
        if unit_scope.scope_type == SCOPE_CUSTOMER and claim.scope != unit_scope:
            raise KnowledgeClaimError("customer claim cannot ground in another tenant TextUnit")
        if claim.scope.scope_type == SCOPE_CUSTOMER and unit_scope.scope_type == SCOPE_CUSTOMER:
            if not visible_to(owned=unit_scope, reader_customer_id=claim.scope.customer_id):
                raise KnowledgeClaimError("customer claim cannot ground in another tenant TextUnit")


async def supporting_text_unit_ids_for_claim(
    session: AsyncSession,
    claim_id: str,
) -> list[str]:
    rows = (
        await session.execute(
            select(KnowledgeClaimTextUnit.text_unit_id)
            .where(KnowledgeClaimTextUnit.claim_id == claim_id)
            .order_by(KnowledgeClaimTextUnit.ordinal, KnowledgeClaimTextUnit.text_unit_id)
        )
    ).all()
    return [row[0] for row in rows]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _compact(value: str) -> str:
    return " ".join(value.split())
