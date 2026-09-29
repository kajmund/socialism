"""Bounded Jev TTL classification outside research and outside DB transactions."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database.answer_review import KnowledgeAnswerReview
from app.jev.system import HttpJevSystemOne, JevClientError, JevSystemOne
from app.services.knowledge.answer_review import (
    REVIEW_TTL_QUESTION,
    AnswerReviewDecision,
    parse_review_decision,
    review_after,
)


MAX_CLASSIFICATION_ATTEMPTS = 5
_RETRY_BASE = timedelta(minutes=5)
_RETRY_CAP = timedelta(hours=6)


def retry_delay(attempts: int) -> timedelta:
    """Exponential backoff: 5 min, 10, 20, ... capped at 6 h."""
    return min(_RETRY_BASE * 2 ** min(max(attempts - 1, 0), 10), _RETRY_CAP)


def classification_state(basis: dict) -> dict:
    """All-source overview with bounded detail and explicit truncation metadata."""
    rows = basis["evidence"]
    state = {
        "question": basis["question"][:1000],
        "source_types": sorted({row["source_type"] for row in rows}),
        "evidence_count": len(rows),
        "assessments": json.dumps(basis["assessments"], ensure_ascii=False)[:1000],
        "evidence": [
            {
                "source_type": row["source_type"],
                "provider": row.get("provider"),
                "excerpt": (row.get("excerpt") or "")[:500],
                "interpretation": json.dumps(row.get("interpretation"), ensure_ascii=False)[:500],
            }
            for row in rows[:32]
        ],
        "detail_is_compacted": True,
        "omitted_evidence_count": max(0, len(rows) - 32),
    }
    while len(json.dumps(state, ensure_ascii=False)) > settings.jev_state_char_budget:
        if not state["evidence"]:
            raise JevClientError("Answer overview exceeds Jev budget", category="invalid_request")
        state["evidence"].pop()
        state["omitted_evidence_count"] += 1
    return state


async def claim_ttl_classification(session: AsyncSession, *, now: datetime) -> dict | None:
    due = (
        select(KnowledgeAnswerReview.id)
        .where(
            KnowledgeAnswerReview.status == "awaiting_ttl",
            KnowledgeAnswerReview.next_classification_at <= now,
            KnowledgeAnswerReview.classification_attempts < MAX_CLASSIFICATION_ATTEMPTS,
        )
        .order_by(KnowledgeAnswerReview.next_classification_at, KnowledgeAnswerReview.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .cte("ttl_batch")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    token = uuid4().hex
    result = await session.execute(
        update(KnowledgeAnswerReview)
        .where(
            KnowledgeAnswerReview.id.in_(select(due.c.id)),
            KnowledgeAnswerReview.status == "awaiting_ttl",
        )
        .values(
            classification_token=token,
            next_classification_at=now + timedelta(minutes=2),
            # Counted at claim time so a worker crash also consumes an attempt.
            classification_attempts=KnowledgeAnswerReview.classification_attempts + 1,
        )
        .returning(
            KnowledgeAnswerReview.id,
            KnowledgeAnswerReview.classification_attempts,
            KnowledgeAnswerReview.answer_basis,
            KnowledgeAnswerReview.created_at,
            KnowledgeAnswerReview.classification_token,
        )
        .execution_options(synchronize_session=False)
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def finish_ttl_classification(
    session: AsyncSession,
    *,
    claim: dict,
    decision: AnswerReviewDecision,
) -> bool:
    created = claim["created_at"]
    if created.tzinfo is None:  # SQLite drops timezone metadata; stored timestamps are UTC.
        created = created.replace(tzinfo=UTC)
    result = await session.execute(
        update(KnowledgeAnswerReview)
        .where(
            KnowledgeAnswerReview.id == claim["id"],
            KnowledgeAnswerReview.classification_token == claim["classification_token"],
            KnowledgeAnswerReview.status == "awaiting_ttl",
        )
        .values(
            ttl=decision.ttl,
            review_after=review_after(created, decision.ttl),
            status="scheduled",
            classification_token=None,
            next_classification_at=None,
            last_error=None,
        )
        .returning(KnowledgeAnswerReview.id)
    )
    return result.scalar_one_or_none() is not None


async def classify_pending_reviews(
    factory: async_sessionmaker[AsyncSession],
    *,
    jev: JevSystemOne | None = None,
    limit: int = 100,
) -> dict:
    if not 1 <= limit <= 500:
        raise ValueError("batch limit must be between 1 and 500")
    client = jev or HttpJevSystemOne()
    completed, failed = [], []
    for _ in range(limit):
        async with factory.begin() as session:
            claim = await claim_ttl_classification(session, now=datetime.now(UTC))
        if claim is None:
            break
        # The claim transaction has committed and returned its connection before HTTP.
        try:
            result = await client.ask(
                state=classification_state(claim["answer_basis"]),
                questions={"review_ttl": REVIEW_TTL_QUESTION},
                model=settings.jev_model,
                timeout_seconds=settings.jev_timeout_seconds,
            )
            decision = parse_review_decision(result.answers)
        except Exception as exc:  # noqa: BLE001 - one bad row must not stall the queue
            category = str(getattr(exc, "category", None) or type(exc).__name__)[:64]
            await _record_failure(factory, claim=claim, category=category)
            failed.append({"id": claim["id"], "error": category})
            continue
        async with factory.begin() as session:
            if await finish_ttl_classification(session, claim=claim, decision=decision):
                completed.append(claim["id"])
    return {"classified_ids": completed, "failed": failed}


async def _record_failure(
    factory: async_sessionmaker[AsyncSession], *, claim: dict, category: str
) -> None:
    """Release the lease with backoff; park (no next attempt) after the last try."""
    attempts = claim["classification_attempts"]
    parked = attempts >= MAX_CLASSIFICATION_ATTEMPTS
    async with factory.begin() as session:
        await session.execute(
            update(KnowledgeAnswerReview)
            .where(
                KnowledgeAnswerReview.id == claim["id"],
                KnowledgeAnswerReview.classification_token == claim["classification_token"],
            )
            .values(
                last_error=category,
                classification_token=None,
                next_classification_at=(
                    None if parked else datetime.now(UTC) + retry_delay(attempts)
                ),
            )
        )
