"""Persist and serialize generic WordAction rows."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import WordAction
from app.services.word.anchors import WordAnchor
from app.services.word.application import APPLICATION_PENDING
from app.services.word.schemas import (
    SUPPORTED_WORD_ACTION_TYPES,
    WordActionOut,
    WordActionSource,
    WordActionType,
    WordAnchorOut,
)

SOURCE_TYPE_EXPERT_REVIEW_RESULT = "expert_review_result"


def new_word_action_id() -> str:
    return f"wa_{secrets.token_hex(8)}"


def word_anchor_payload(anchor: WordAnchor | None) -> dict | None:
    if anchor is None:
        return None
    return {
        "paragraph_index": anchor.paragraph_index,
        "unique_local_id": anchor.unique_local_id,
        "reviewed_text": anchor.reviewed_text,
        "text_hash": anchor.text_hash,
        "previous_text_hash": anchor.previous_text_hash,
        "next_text_hash": anchor.next_text_hash,
        "word_session_id": anchor.word_session_id,
    }


def _created_at(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def serialize_word_action(row: WordAction) -> WordActionOut:
    anchor = None if row.anchor is None else WordAnchorOut.model_validate(row.anchor)
    return WordActionOut(
        id=row.id,
        job_id=row.job_id,
        action_type=row.action_type,
        anchor=anchor,
        content=row.content,
        explanation=row.explanation,
        status=row.status,
        application_id=row.application_id,
        application_error=row.application_error,
        word_artifact_id=row.word_artifact_id,
        source=WordActionSource(
            type=row.source_type,
            id=row.source_id,
            ordinal=row.source_ordinal,
        ),
        created_at=_created_at(row.created_at),
    )


async def load_word_action(
    session: AsyncSession,
    *,
    job_id: str,
    action_id: str,
    customer_id: int,
) -> WordAction | None:
    row = await session.get(WordAction, action_id)
    if row is None:
        return None
    if row.job_id != job_id or row.customer_id != customer_id:
        return None
    return row


async def load_word_action_by_source(
    session: AsyncSession,
    *,
    source_type: str,
    source_id: str,
    source_ordinal: int,
) -> WordAction | None:
    result = await session.execute(
        select(WordAction).where(
            WordAction.source_type == source_type,
            WordAction.source_id == source_id,
            WordAction.source_ordinal == source_ordinal,
        )
    )
    return result.scalar_one_or_none()


async def load_word_actions(
    session: AsyncSession, job_id: str, *, customer_id: int | None = None
) -> list[WordAction]:
    stmt = (
        select(WordAction)
        .where(WordAction.job_id == job_id)
        .order_by(WordAction.created_at, WordAction.id)
    )
    if customer_id is not None:
        stmt = stmt.where(WordAction.customer_id == customer_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def persist_word_action(
    session: AsyncSession,
    *,
    customer_id: int,
    job_id: str,
    source_type: str,
    source_id: str,
    source_ordinal: int,
    action_type: WordActionType,
    content: str,
    explanation: str | None,
    anchor: WordAnchor | None,
    created_at: datetime,
) -> WordAction:
    if action_type not in SUPPORTED_WORD_ACTION_TYPES:
        raise ValueError(f"unsupported action_type: {action_type}")
    text = content.strip()
    if not text:
        raise ValueError("word action content is required")
    rationale = None if explanation is None else explanation.strip() or None
    row = WordAction(
        id=new_word_action_id(),
        customer_id=customer_id,
        job_id=job_id,
        source_type=source_type,
        source_id=source_id,
        source_ordinal=source_ordinal,
        action_type=action_type,
        anchor=word_anchor_payload(anchor),
        content=text,
        explanation=rationale,
        status=APPLICATION_PENDING,
        created_at=created_at,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        existing = await load_word_action_by_source(
            session,
            source_type=source_type,
            source_id=source_id,
            source_ordinal=source_ordinal,
        )
        if existing is None:
            raise
        return existing
    return row
