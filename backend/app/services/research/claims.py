"""Database-backed research claim/lease. Not a second Attempt status."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import ExecutionAttempt, ExecutionResearchClaim
from app.services.execution.service import get_attempt, new_id, utc_now

CLAIMABLE_ATTEMPT_STATUSES = frozenset({"created", "researching"})


def lease_ttl() -> timedelta:
    return timedelta(seconds=settings.research_claim_lease_seconds)


def start_request_payload(
    *,
    research_objective: str | None,
    research_context: dict[str, object],
    research_plan: dict[str, object] | None,
) -> dict[str, object]:
    return {
        "research_objective": research_objective,
        "research_context": dict(research_context),
        "research_plan": research_plan,
    }


async def get_research_claim(
    session: AsyncSession, attempt_id: str
) -> ExecutionResearchClaim | None:
    return await session.get(ExecutionResearchClaim, attempt_id)


async def enqueue_research_claim(
    session: AsyncSession,
    attempt_id: str,
    *,
    start_request: dict[str, object],
) -> ExecutionResearchClaim:
    """Idempotent: one claim row per Attempt. Does not change Attempt.status."""
    await get_attempt(session, attempt_id)
    existing = await get_research_claim(session, attempt_id)
    if existing is not None:
        return existing
    claim = ExecutionResearchClaim(
        attempt_id=attempt_id,
        start_request=dict(start_request),
    )
    try:
        async with session.begin_nested():
            session.add(claim)
            await session.flush()
    except IntegrityError:
        loaded = await get_research_claim(session, attempt_id)
        if loaded is None:
            raise
        return loaded
    return claim


async def claim_research_lease(
    session: AsyncSession,
    attempt_id: str,
    *,
    worker_id: str,
) -> ExecutionResearchClaim | None:
    """Compare-and-set an unclaimed or expired lease. One owner at a time."""
    attempt = await get_attempt(session, attempt_id)
    if attempt.status not in CLAIMABLE_ATTEMPT_STATUSES:
        return None
    now = utc_now()
    token = new_id()
    result = await session.execute(
        update(ExecutionResearchClaim)
        .where(
            ExecutionResearchClaim.attempt_id == attempt_id,
            or_(
                ExecutionResearchClaim.worker_id.is_(None),
                ExecutionResearchClaim.lease_expires_at.is_(None),
                ExecutionResearchClaim.lease_expires_at <= now,
            ),
        )
        .values(
            worker_id=worker_id,
            lease_token=token,
            lease_expires_at=now + lease_ttl(),
            claimed_at=now,
        )
    )
    if result.rowcount != 1:
        return None
    claim = await get_research_claim(session, attempt_id)
    if claim is None:
        return None
    await session.refresh(claim)
    return claim


async def renew_research_lease(
    session: AsyncSession,
    attempt_id: str,
    *,
    lease_token: str,
) -> bool:
    now = utc_now()
    result = await session.execute(
        update(ExecutionResearchClaim)
        .where(
            ExecutionResearchClaim.attempt_id == attempt_id,
            ExecutionResearchClaim.lease_token == lease_token,
        )
        .values(lease_expires_at=now + lease_ttl())
    )
    return result.rowcount == 1


async def release_research_lease(
    session: AsyncSession,
    attempt_id: str,
    *,
    lease_token: str,
) -> None:
    await session.execute(
        update(ExecutionResearchClaim)
        .where(
            ExecutionResearchClaim.attempt_id == attempt_id,
            ExecutionResearchClaim.lease_token == lease_token,
        )
        .values(
            worker_id=None,
            lease_token=None,
            lease_expires_at=None,
        )
    )


async def list_claimable_attempt_ids(session: AsyncSession) -> list[str]:
    now = utc_now()
    result = await session.execute(
        select(ExecutionResearchClaim.attempt_id)
        .join(
            ExecutionAttempt,
            ExecutionAttempt.id == ExecutionResearchClaim.attempt_id,
        )
        .where(
            ExecutionAttempt.status.in_(tuple(CLAIMABLE_ATTEMPT_STATUSES)),
            or_(
                ExecutionResearchClaim.worker_id.is_(None),
                ExecutionResearchClaim.lease_expires_at.is_(None),
                ExecutionResearchClaim.lease_expires_at <= now,
            ),
        )
        .order_by(ExecutionResearchClaim.created_at, ExecutionResearchClaim.attempt_id)
    )
    return list(result.scalars().all())
