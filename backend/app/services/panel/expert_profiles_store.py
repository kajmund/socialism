"""Persist and seed module-scoped panel expert profile catalog rows."""

from __future__ import annotations

from typing import Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelExpertProfile
from app.serializers import utcnow
from app.services.dd.expert_keys import expert_role_key


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
    existing_keys = {row.key for row in result.scalars().all()}
    added = 0
    for index, default in enumerate(defaults):
        name = str(default["name"])
        key = str(default.get("key") or expert_role_key(name))
        if key in existing_keys:
            continue
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
                sort_order=index,
                active=True,
                updated_at=utcnow(),
            )
        )
        added += 1
        existing_keys.add(key)
    if added:
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return 0
    return added
