"""Atomic Word result application claims. Domain-agnostic status machine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExpertgranskningResult

APPLICATION_PENDING = "pending"
APPLICATION_APPLYING = "applying"
APPLICATION_APPLIED = "applied"
APPLICATION_UNRESOLVED = "unresolved"

APPLICATION_STATUSES = {
    APPLICATION_PENDING,
    APPLICATION_APPLYING,
    APPLICATION_APPLIED,
    APPLICATION_UNRESOLVED,
}

UNRESOLVED_STALE = "stale"
UNRESOLVED_AMBIGUOUS = "ambiguous"
UNRESOLVED_MISSING = "missing"
UNRESOLVED_UNCERTAIN = "uncertain_previous_outcome"


@dataclass(frozen=True)
class ApplicationMutation:
    accepted: bool
    row: ExpertgranskningResult | None
    reason: Literal[
        "claimed",
        "idempotent",
        "not_claimable",
        "completed",
        "not_completable",
        "unresolved",
        "not_unresolvable",
        "missing",
    ]


async def _load_result(
    session: AsyncSession,
    *,
    job_id: str,
    result_id: str,
) -> ExpertgranskningResult | None:
    row = await session.get(ExpertgranskningResult, result_id)
    if row is None or row.job_id != job_id:
        return None
    return row


async def claim_application(
    session: AsyncSession,
    *,
    job_id: str,
    result_id: str,
    application_id: str,
) -> ApplicationMutation:
    result = await session.execute(
        update(ExpertgranskningResult)
        .where(
            ExpertgranskningResult.id == result_id,
            ExpertgranskningResult.job_id == job_id,
            ExpertgranskningResult.status == APPLICATION_PENDING,
        )
        .values(
            status=APPLICATION_APPLYING,
            application_id=application_id,
            application_error=None,
        )
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount == 1:
        await session.commit()
        row = await _load_result(session, job_id=job_id, result_id=result_id)
        return ApplicationMutation(accepted=True, row=row, reason="claimed")

    row = await _load_result(session, job_id=job_id, result_id=result_id)
    if row is None:
        return ApplicationMutation(accepted=False, row=None, reason="missing")
    if (
        row.status == APPLICATION_APPLYING
        and row.application_id == application_id
    ):
        return ApplicationMutation(accepted=True, row=row, reason="idempotent")
    return ApplicationMutation(accepted=False, row=row, reason="not_claimable")


async def complete_application(
    session: AsyncSession,
    *,
    job_id: str,
    result_id: str,
    application_id: str,
    word_artifact_id: str | None,
) -> ApplicationMutation:
    values: dict[str, str | None] = {
        "status": APPLICATION_APPLIED,
        "application_error": None,
    }
    if word_artifact_id is not None:
        values["comment_id"] = word_artifact_id
    result = await session.execute(
        update(ExpertgranskningResult)
        .where(
            ExpertgranskningResult.id == result_id,
            ExpertgranskningResult.job_id == job_id,
            ExpertgranskningResult.status == APPLICATION_APPLYING,
            ExpertgranskningResult.application_id == application_id,
        )
        .values(**values)
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount == 1:
        await session.commit()
        row = await _load_result(session, job_id=job_id, result_id=result_id)
        return ApplicationMutation(accepted=True, row=row, reason="completed")

    row = await _load_result(session, job_id=job_id, result_id=result_id)
    if row is None:
        return ApplicationMutation(accepted=False, row=None, reason="missing")
    if row.status == APPLICATION_APPLIED and row.application_id == application_id:
        return ApplicationMutation(accepted=True, row=row, reason="idempotent")
    return ApplicationMutation(accepted=False, row=row, reason="not_completable")


async def mark_application_unresolved(
    session: AsyncSession,
    *,
    job_id: str,
    result_id: str,
    reason: str,
    application_id: str | None,
) -> ApplicationMutation:
    if application_id:
        where = or_(
            ExpertgranskningResult.status == APPLICATION_PENDING,
            and_(
                ExpertgranskningResult.status == APPLICATION_APPLYING,
                ExpertgranskningResult.application_id == application_id,
            ),
        )
        values = {
            "status": APPLICATION_UNRESOLVED,
            "application_id": application_id,
            "application_error": reason,
        }
    else:
        where = ExpertgranskningResult.status == APPLICATION_PENDING
        values = {
            "status": APPLICATION_UNRESOLVED,
            "application_error": reason,
        }
    result = await session.execute(
        update(ExpertgranskningResult)
        .where(
            ExpertgranskningResult.id == result_id,
            ExpertgranskningResult.job_id == job_id,
            where,
        )
        .values(**values)
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount == 1:
        await session.commit()
        row = await _load_result(session, job_id=job_id, result_id=result_id)
        return ApplicationMutation(accepted=True, row=row, reason="unresolved")

    row = await _load_result(session, job_id=job_id, result_id=result_id)
    if row is None:
        return ApplicationMutation(accepted=False, row=None, reason="missing")
    if row.status == APPLICATION_UNRESOLVED:
        return ApplicationMutation(accepted=True, row=row, reason="idempotent")
    return ApplicationMutation(accepted=False, row=row, reason="not_unresolvable")
