"""Domain-neutral claims grounded in TextUnits.

A claim is an assertion. Support is SUPPORTED_BY one or more TextUnits.
Adapters choose predicate strings; this module does not interpret them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    KnowledgeClaimAnswer,
    KnowledgeClaimRecord,
    KnowledgeClaimTextUnit,
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
    customer_id: int
    document_id: str
    document_version_id: str
    predicate: str
    value: dict[str, object]
    supporting_text_unit_ids: tuple[str, ...]


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
    if row is None:
        row = KnowledgeClaimRecord(
            id=claim.id,
            customer_id=claim.customer_id,
            document_id=claim.document_id,
            document_version_id=claim.document_version_id,
            predicate=claim.predicate,
            value=claim.value,
        )
        session.add(row)
        await session.flush()
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


async def answer_research_need(
    session: AsyncSession,
    *,
    research_need_id: str,
    question_key: str,
    claim_ids: Sequence[str],
) -> None:
    """ResearchNeed → ANSWERED_BY → Claim. Reuse looks up question_key."""
    if not research_need_id.strip():
        raise KnowledgeClaimError("research_need_id is required")
    if not question_key.strip():
        raise KnowledgeClaimError("question_key is required")
    if not claim_ids:
        raise KnowledgeClaimError("ANSWERED_BY requires at least one claim")
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
                relation=ANSWERED_BY,
            )
        )
    await session.flush()


async def claims_answering_question_key(
    session: AsyncSession,
    *,
    customer_id: int,
    question_key: str,
) -> list[KnowledgeClaim]:
    """Reuse: claims that already answer this question key for the tenant."""
    rows = (
        await session.execute(
            select(KnowledgeClaimRecord, KnowledgeClaimAnswer)
            .join(
                KnowledgeClaimAnswer,
                KnowledgeClaimAnswer.claim_id == KnowledgeClaimRecord.id,
            )
            .where(
                KnowledgeClaimRecord.customer_id == customer_id,
                KnowledgeClaimAnswer.question_key == question_key,
                KnowledgeClaimAnswer.relation == ANSWERED_BY,
            )
            .order_by(KnowledgeClaimRecord.predicate, KnowledgeClaimRecord.id)
        )
    ).all()
    seen: set[str] = set()
    claims: list[KnowledgeClaim] = []
    for record, _answer in rows:
        if record.id in seen:
            continue
        seen.add(record.id)
        support = await supporting_text_unit_ids_for_claim(session, record.id)
        claims.append(
            KnowledgeClaim(
                id=record.id,
                customer_id=record.customer_id,
                document_id=record.document_id,
                document_version_id=record.document_version_id,
                predicate=record.predicate,
                value=record.value,
                supporting_text_unit_ids=tuple(support),
            )
        )
    return claims


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
