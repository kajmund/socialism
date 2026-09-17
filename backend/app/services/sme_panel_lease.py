"""Database-backed per-panel lease for SME panel turns."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import SmePanelTurnLease
from app.serializers import utcnow

PANEL_TURN_LEASE_SECONDS = 180
PANEL_TURN_LEASE_POLL_SECONDS = 0.05


def _lease_ttl() -> timedelta:
    return timedelta(seconds=PANEL_TURN_LEASE_SECONDS)


async def try_acquire_panel_lease(
    session: AsyncSession,
    panel_id: int,
    *,
    token: str,
) -> int | None:
    """Compare-and-set an unclaimed or expired panel lease. Returns fence or None."""
    now = utcnow()
    row = await session.get(SmePanelTurnLease, panel_id)
    if row is None:
        try:
            async with session.begin_nested():
                session.add(
                    SmePanelTurnLease(
                        panel_id=panel_id,
                        fence=1,
                        lease_token=token,
                        lease_expires_at=now + _lease_ttl(),
                        updated_at=now,
                    )
                )
                await session.flush()
            return 1
        except IntegrityError:
            return None
    result = await session.execute(
        update(SmePanelTurnLease)
        .where(
            SmePanelTurnLease.panel_id == panel_id,
            or_(
                SmePanelTurnLease.lease_token.is_(None),
                SmePanelTurnLease.lease_expires_at.is_(None),
                SmePanelTurnLease.lease_expires_at <= now,
            ),
        )
        .values(
            fence=SmePanelTurnLease.fence + 1,
            lease_token=token,
            lease_expires_at=now + _lease_ttl(),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return None
    await session.refresh(row)
    return row.fence


async def acquire_panel_lease(
    session_factory: async_sessionmaker[AsyncSession],
    panel_id: int,
    *,
    token: str,
) -> int:
    """Wait until this worker owns the panel lease. Short transactions only."""
    while True:
        async with session_factory() as session:
            fence = await try_acquire_panel_lease(session, panel_id, token=token)
            await session.commit()
        if fence is not None:
            return fence
        await asyncio.sleep(PANEL_TURN_LEASE_POLL_SECONDS)


async def panel_lease_still_held(
    session: AsyncSession,
    panel_id: int,
    *,
    token: str,
    fence: int,
) -> bool:
    result = await session.execute(
        update(SmePanelTurnLease)
        .where(
            SmePanelTurnLease.panel_id == panel_id,
            SmePanelTurnLease.lease_token == token,
            SmePanelTurnLease.fence == fence,
        )
        .values(updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


async def release_panel_lease(
    session: AsyncSession,
    panel_id: int,
    *,
    token: str,
    fence: int,
) -> None:
    await session.execute(
        update(SmePanelTurnLease)
        .where(
            SmePanelTurnLease.panel_id == panel_id,
            SmePanelTurnLease.lease_token == token,
            SmePanelTurnLease.fence == fence,
        )
        .values(
            lease_token=None,
            lease_expires_at=None,
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
