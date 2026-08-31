"""Persist and seed module-scoped panel expert profile catalog rows."""

from __future__ import annotations

from typing import Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelExpertProfile
from app.serializers import utcnow
from app.services.dd.expert_keys import expert_role_key


def _unused_sort_order(taken: set[int], preferred: int) -> int:
    if preferred not in taken:
        return preferred
    return max(taken) + 1


async def get_expert_profiles(
    session: AsyncSession,
    module: str,
    *,
    active_only: bool = True,
) -> list[PanelExpertProfile]:
    """Return expert profiles for a module, ordered by sort_order then key."""
    stmt = select(PanelExpertProfile).where(PanelExpertProfile.module == module)
    if active_only:
        stmt = stmt.where(PanelExpertProfile.active.is_(True))
    stmt = stmt.order_by(PanelExpertProfile.sort_order, PanelExpertProfile.key)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_expert_profile(session: AsyncSession, row_id: int) -> PanelExpertProfile | None:
    return await session.get(PanelExpertProfile, row_id)


async def next_expert_profile_sort_order(session: AsyncSession, module: str) -> int:
    rows = await get_expert_profiles(session, module, active_only=False)
    if not rows:
        return 0
    return max(row.sort_order for row in rows) + 1


async def create_expert_profile(
    session: AsyncSession,
    *,
    module: str,
    key: str,
    name: str,
    description: str = "",
    kompetensomrade: str = "",
    radgivningsstil: str = "",
    yrkesbakgrund: str = "",
    professionell_anekdot: str = "",
    sort_order: int,
    active: bool = True,
) -> PanelExpertProfile:
    row = PanelExpertProfile(
        module=module,
        key=key,
        name=name,
        description=description,
        kompetensomrade=kompetensomrade,
        radgivningsstil=radgivningsstil,
        yrkesbakgrund=yrkesbakgrund,
        professionell_anekdot=professionell_anekdot,
        sort_order=sort_order,
        active=active,
        updated_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def update_expert_profile(
    session: AsyncSession,
    row: PanelExpertProfile,
    *,
    name: str | None = None,
    description: str | None = None,
    kompetensomrade: str | None = None,
    radgivningsstil: str | None = None,
    yrkesbakgrund: str | None = None,
    professionell_anekdot: str | None = None,
    sort_order: int | None = None,
    active: bool | None = None,
) -> PanelExpertProfile:
    if name is not None:
        row.name = name
    if description is not None:
        row.description = description
    if kompetensomrade is not None:
        row.kompetensomrade = kompetensomrade
    if radgivningsstil is not None:
        row.radgivningsstil = radgivningsstil
    if yrkesbakgrund is not None:
        row.yrkesbakgrund = yrkesbakgrund
    if professionell_anekdot is not None:
        row.professionell_anekdot = professionell_anekdot
    if sort_order is not None:
        row.sort_order = sort_order
    if active is not None:
        row.active = active
    row.updated_at = utcnow()
    await session.flush()
    await session.refresh(row)
    return row


async def ensure_expert_profile_defaults(
    session: AsyncSession,
    module: str,
    defaults: list[Mapping[str, str]] | tuple[Mapping[str, str], ...],
) -> int:
    """Insert missing (module, key) rows. Does not overwrite existing rows.

    Each default mapping must include name, description, kompetensomrade,
    radgivningsstil, yrkesbakgrund, professionell_anekdot. key is derived
    from name via expert_role_key when not provided.
    """
    result = await session.execute(
        select(PanelExpertProfile).where(PanelExpertProfile.module == module)
    )
    existing_rows = list(result.scalars().all())
    existing_keys = {row.key for row in existing_rows}
    taken_orders = {row.sort_order for row in existing_rows}
    added = 0
    for index, default in enumerate(defaults):
        name = str(default["name"])
        key = str(default.get("key") or expert_role_key(name))
        if key in existing_keys:
            continue
        sort_order = _unused_sort_order(taken_orders, index)
        session.add(
            PanelExpertProfile(
                module=module,
                key=key,
                name=name,
                description=str(default.get("description") or ""),
                kompetensomrade=str(default.get("kompetensomrade") or ""),
                radgivningsstil=str(default.get("radgivningsstil") or ""),
                yrkesbakgrund=str(default.get("yrkesbakgrund") or ""),
                professionell_anekdot=str(default.get("professionell_anekdot") or ""),
                sort_order=sort_order,
                active=True,
                updated_at=utcnow(),
            )
        )
        added += 1
        existing_keys.add(key)
        taken_orders.add(sort_order)
    if added:
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return 0
    return added
