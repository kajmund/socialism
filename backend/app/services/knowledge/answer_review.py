"""TTL schedules for immutable question/claim answer versions, not validity dates."""

from __future__ import annotations

import calendar
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Select, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.answer_review import KnowledgeAnswerReview
from app.jev.system import JevClientError

ReviewTTL = Literal["soon", "later", "never"]
REVIEW_MONTHS = {"soon": 3, "later": 6, "never": None}
REVIEW_TTL_QUESTION = {
    "type": "choice",
    "instructions": (
        "When should an answer to this question, grounded in the relevant supplied "
        "passages, next be considered for improvement? This is a review reminder, "
        "not an expiry or legal validity date. More knowledge can nuance an answer "
        "without invalidating it. Judge stability and gaps, not just source age."
    ),
    "criteria": {
        "soon": "Review in 3 months: changing facts or a thin, uncertain basis.",
        "later": "Review in 6 months: reasonably stable, but useful refinement is likely.",
        "never": (
            "No scheduled review: stable, well-established or historical knowledge; "
            "age alone does not warrant reconsideration. It can still be updated."
        ),
    },
}


@dataclass(frozen=True)
class AnswerReviewDecision:
    ttl: ReviewTTL

    def __post_init__(self) -> None:
        if self.ttl not in REVIEW_MONTHS:
            raise ValueError(f"Unknown answer review TTL: {self.ttl!r}")


def parse_review_decision(answers: dict) -> AnswerReviewDecision:
    answer = answers.get("review_ttl")
    choice = answer.get("choice") if isinstance(answer, dict) else None
    if not isinstance(choice, str) or choice not in REVIEW_MONTHS:
        raise JevClientError("Jev response has invalid review_ttl", category="schema_validation")
    return AnswerReviewDecision(choice)


def review_after(created_at: datetime, ttl: ReviewTTL) -> datetime | None:
    months = REVIEW_MONTHS[ttl]
    if months is None:
        return None
    if created_at.tzinfo is None:
        raise ValueError("answer creation time must be timezone-aware")
    stamp = created_at.astimezone(UTC)
    year, month = divmod(stamp.year * 12 + stamp.month - 1 + months, 12)
    month += 1
    day = min(stamp.day, calendar.monthrange(year, month)[1])
    return stamp.replace(year=year, month=month, day=day)


async def schedule_answer_review(
    session: AsyncSession,
    *,
    customer_id: int,
    question_key: str,
    question: str,
    claim_ids: list[str],
    decision: AnswerReviewDecision,
    created_at: datetime | None = None,
) -> str:
    """Called with grounded, tenant-validated claims in their write transaction.

    The same question and claim set is the same answer version across retries and
    reuse. Rediscovery must not reset its clock or reopen a completed candidate.
    """
    claims = sorted(set(claim_ids))
    if not claims:
        raise ValueError("answer review requires grounded claims")
    payload = json.dumps([customer_id, question_key, claims], separators=(",", ":"))
    answer_id = hashlib.sha256(payload.encode()).hexdigest()
    stamp = created_at or datetime.now(UTC)
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    await session.execute(
        insert(KnowledgeAnswerReview)
        .values(
            id=answer_id,
            customer_id=customer_id,
            question_key=question_key,
            question=question,
            claim_ids=claims,
            ttl=decision.ttl,
            created_at=stamp,
            review_after=review_after(stamp, decision.ttl),
            status="scheduled",
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    return answer_id


def due_review_ids(now: datetime, limit: int) -> Select:
    if not 1 <= limit <= 500:
        raise ValueError("batch limit must be between 1 and 500")
    return (
        select(KnowledgeAnswerReview.id)
        .where(
            KnowledgeAnswerReview.status == "scheduled",
            KnowledgeAnswerReview.review_after <= now,
        )
        .order_by(KnowledgeAnswerReview.review_after, KnowledgeAnswerReview.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


async def enqueue_due_reviews(
    session: AsyncSession, *, now: datetime | None = None, limit: int = 100
) -> list[str]:
    """One bounded indexed update; safe for repeated/concurrent invocations."""
    stamp = now or datetime.now(UTC)
    # Freeze the batch before updating: PostgreSQL may otherwise rescan a
    # SKIP LOCKED subquery as rows leave the scheduled set, exceeding LIMIT.
    due = (
        due_review_ids(stamp, limit)
        .cte("due_reviews")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    result = await session.execute(
        update(KnowledgeAnswerReview)
        .where(
            KnowledgeAnswerReview.id.in_(select(due.c.id)),
            KnowledgeAnswerReview.status == "scheduled",
        )
        .values(status="candidate", candidate_at=stamp)
        .returning(KnowledgeAnswerReview.id)
        .execution_options(synchronize_session=False)
    )
    return list(result.scalars())


async def list_review_candidates(
    session: AsyncSession, *, customer_id: int, limit: int = 100
) -> list[KnowledgeAnswerReview]:
    if not 1 <= limit <= 500:
        raise ValueError("batch limit must be between 1 and 500")
    result = await session.execute(
        select(KnowledgeAnswerReview)
        .where(
            KnowledgeAnswerReview.customer_id == customer_id,
            KnowledgeAnswerReview.status == "candidate",
        )
        .order_by(KnowledgeAnswerReview.review_after, KnowledgeAnswerReview.id)
        .limit(limit)
    )
    return list(result.scalars())


async def complete_review(session: AsyncSession, *, customer_id: int, answer_id: str) -> bool:
    result = await session.execute(
        update(KnowledgeAnswerReview)
        .where(
            KnowledgeAnswerReview.id == answer_id,
            KnowledgeAnswerReview.customer_id == customer_id,
            KnowledgeAnswerReview.status == "candidate",
        )
        .values(status="completed", completed_at=datetime.now(UTC))
        .returning(KnowledgeAnswerReview.id)
    )
    return result.scalar_one_or_none() is not None
