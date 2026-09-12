"""Atomic WordAction application claims. Domain-agnostic status machine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import WordAction

APPLICATION_PENDING = "pending"
APPLICATION_APPLYING = "applying"
APPLICATION_APPLIED = "applied"
APPLICATION_UNRESOLVED = "unresolved"
APPLICATION_DISMISSED = "dismissed"

APPLICATION_STATUSES = {
    APPLICATION_PENDING,
    APPLICATION_APPLYING,
    APPLICATION_APPLIED,
    APPLICATION_UNRESOLVED,
    APPLICATION_DISMISSED,
}

DISMISSABLE_STATUSES = (APPLICATION_PENDING, APPLICATION_UNRESOLVED)

UNRESOLVED_STALE = "stale"
UNRESOLVED_AMBIGUOUS = "ambiguous"
UNRESOLVED_MISSING = "missing"
UNRESOLVED_UNCERTAIN = "uncertain_previous_outcome"
UNRESOLVED_UNSUPPORTED = "unsupported_action"


@dataclass(frozen=True)
class ApplicationMutation:
    accepted: bool
    row: WordAction | None
    reason: Literal[
        "claimed",
        "idempotent",
        "not_claimable",
        "completed",
        "not_completable",
        "unresolved",
        "not_unresolvable",
        "dismissed",
        "not_dismissible",
        "missing",
    ]


async def _load_action(
    session: AsyncSession,
    *,
    job_id: str,
    action_id: str,
    customer_id: int,
) -> WordAction | None:
    row = await session.get(WordAction, action_id)
    if row is None or row.job_id != job_id or row.customer_id != customer_id:
        return None
    return row


async def claim_application(
    session: AsyncSession,
    *,
    job_id: str,
    action_id: str,
    application_id: str,
    customer_id: int,
) -> ApplicationMutation:
    result = await session.execute(
        update(WordAction)
        .where(
            WordAction.id == action_id,
            WordAction.job_id == job_id,
            WordAction.customer_id == customer_id,
            WordAction.status == APPLICATION_PENDING,
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
        row = await _load_action(
            session, job_id=job_id, action_id=action_id, customer_id=customer_id
        )
        return ApplicationMutation(accepted=True, row=row, reason="claimed")

    row = await _load_action(
        session, job_id=job_id, action_id=action_id, customer_id=customer_id
    )
    if row is None:
        return ApplicationMutation(accepted=False, row=None, reason="missing")
    if row.status == APPLICATION_APPLYING and row.application_id == application_id:
        return ApplicationMutation(accepted=True, row=row, reason="idempotent")
    return ApplicationMutation(accepted=False, row=row, reason="not_claimable")


async def complete_application(
    session: AsyncSession,
    *,
    job_id: str,
    action_id: str,
    application_id: str,
    word_artifact_id: str | None,
    customer_id: int,
) -> ApplicationMutation:
    values: dict[str, str | None] = {
        "status": APPLICATION_APPLIED,
        "application_error": None,
    }
    if word_artifact_id is not None:
        values["word_artifact_id"] = word_artifact_id
    result = await session.execute(
        update(WordAction)
        .where(
            WordAction.id == action_id,
            WordAction.job_id == job_id,
            WordAction.customer_id == customer_id,
            WordAction.status == APPLICATION_APPLYING,
            WordAction.application_id == application_id,
        )
        .values(**values)
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount == 1:
        await session.commit()
        row = await _load_action(
            session, job_id=job_id, action_id=action_id, customer_id=customer_id
        )
        return ApplicationMutation(accepted=True, row=row, reason="completed")

    row = await _load_action(
        session, job_id=job_id, action_id=action_id, customer_id=customer_id
    )
    if row is None:
        return ApplicationMutation(accepted=False, row=None, reason="missing")
    if row.status == APPLICATION_APPLIED and row.application_id == application_id:
        return ApplicationMutation(accepted=True, row=row, reason="idempotent")
    return ApplicationMutation(accepted=False, row=row, reason="not_completable")


async def mark_application_unresolved(
    session: AsyncSession,
    *,
    job_id: str,
    action_id: str,
    reason: str,
    application_id: str | None,
    customer_id: int,
) -> ApplicationMutation:
    if application_id:
        where = or_(
            WordAction.status == APPLICATION_PENDING,
            and_(
                WordAction.status == APPLICATION_APPLYING,
                WordAction.application_id == application_id,
            ),
        )
        values = {
            "status": APPLICATION_UNRESOLVED,
            "application_id": application_id,
            "application_error": reason,
        }
    else:
        where = WordAction.status == APPLICATION_PENDING
        values = {
            "status": APPLICATION_UNRESOLVED,
            "application_error": reason,
        }
    result = await session.execute(
        update(WordAction)
        .where(
            WordAction.id == action_id,
            WordAction.job_id == job_id,
            WordAction.customer_id == customer_id,
            where,
        )
        .values(**values)
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount == 1:
        await session.commit()
        row = await _load_action(
            session, job_id=job_id, action_id=action_id, customer_id=customer_id
        )
        return ApplicationMutation(accepted=True, row=row, reason="unresolved")

    row = await _load_action(
        session, job_id=job_id, action_id=action_id, customer_id=customer_id
    )
    if row is None:
        return ApplicationMutation(accepted=False, row=None, reason="missing")
    if row.status == APPLICATION_UNRESOLVED:
        return ApplicationMutation(accepted=True, row=row, reason="idempotent")
    return ApplicationMutation(accepted=False, row=row, reason="not_unresolvable")


async def dismiss_application(
    session: AsyncSession,
    *,
    job_id: str,
    action_id: str,
    customer_id: int,
) -> ApplicationMutation:
    result = await session.execute(
        update(WordAction)
        .where(
            WordAction.id == action_id,
            WordAction.job_id == job_id,
            WordAction.customer_id == customer_id,
            WordAction.status.in_(DISMISSABLE_STATUSES),
        )
        .values(status=APPLICATION_DISMISSED)
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount == 1:
        await session.commit()
        row = await _load_action(
            session, job_id=job_id, action_id=action_id, customer_id=customer_id
        )
        return ApplicationMutation(accepted=True, row=row, reason="dismissed")

    row = await _load_action(
        session, job_id=job_id, action_id=action_id, customer_id=customer_id
    )
    if row is None:
        return ApplicationMutation(accepted=False, row=None, reason="missing")
    if row.status == APPLICATION_DISMISSED:
        return ApplicationMutation(accepted=True, row=row, reason="idempotent")
    return ApplicationMutation(accepted=False, row=row, reason="not_dismissible")
