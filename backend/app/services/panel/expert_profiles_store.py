"""Persist and seed panel expert profile catalog rows shared across modules."""

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


def _row_modules(row: PanelExpertProfile) -> list[str]:
    raw = row.modules
    if not raw:
        return []
    return [str(item) for item in raw]


def row_belongs_to_module(row: PanelExpertProfile, module: str) -> bool:
    return module in _row_modules(row)


async def get_expert_profiles(
    session: AsyncSession,
    module: str,
    *,
    customer_id: int,
    active_only: bool = True,
) -> list[PanelExpertProfile]:
    """Return this customer's expert profiles that include ``module``.

    Membership is filtered in Python — the catalog is small, and SQLite JSON
    contains-queries are not worth a dialect-specific path.
    """
    stmt = select(PanelExpertProfile).where(
        PanelExpertProfile.customer_id == customer_id
    )
    if active_only:
        stmt = stmt.where(PanelExpertProfile.active.is_(True))
    result = await session.execute(stmt)
    matched = [row for row in result.scalars().all() if row_belongs_to_module(row, module)]
    return sorted(matched, key=lambda row: (row.sort_order, row.key))


async def get_expert_profile(session: AsyncSession, row_id: int) -> PanelExpertProfile | None:
    return await session.get(PanelExpertProfile, row_id)


async def unused_expert_profile_key(
    session: AsyncSession, *, customer_id: int, name: str
) -> str:
    """Next free catalog key for this customer (module-independent)."""
    base = expert_role_key(name)
    result = await session.execute(
        select(PanelExpertProfile.key).where(PanelExpertProfile.customer_id == customer_id)
    )
    taken = set(result.scalars().all())
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


async def get_expert_profile_by_key(
    session: AsyncSession,
    key: str,
    *,
    customer_id: int,
) -> PanelExpertProfile | None:
    result = await session.execute(
        select(PanelExpertProfile).where(
            PanelExpertProfile.customer_id == customer_id,
            PanelExpertProfile.key == key,
        )
    )
    return result.scalar_one_or_none()


async def next_expert_profile_sort_order(
    session: AsyncSession, *, customer_id: int
) -> int:
    result = await session.execute(
        select(PanelExpertProfile.sort_order).where(
            PanelExpertProfile.customer_id == customer_id
        )
    )
    orders = list(result.scalars().all())
    if not orders:
        return 0
    return max(orders) + 1


async def create_expert_profile(
    session: AsyncSession,
    *,
    customer_id: int,
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
        customer_id=customer_id,
        modules=[module],
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
    *,
    customer_id: int,
) -> int:
    """Insert missing keys for ``customer_id``, or attach ``module`` to an existing row.

    A later provider that seeds the same ``key`` for the same customer adds
    its module to the existing row instead of inserting a duplicate. Fields
    on an existing row are never overwritten.

    Each default mapping must include name, description, kompetensomrade,
    radgivningsstil, yrkesbakgrund, professionell_anekdot. key is derived
    from name via expert_role_key when not provided.
    """
    result = await session.execute(
        select(PanelExpertProfile).where(PanelExpertProfile.customer_id == customer_id)
    )
    existing_rows = list(result.scalars().all())
    by_key = {row.key: row for row in existing_rows}
    taken_orders = {row.sort_order for row in existing_rows}
    changed = 0
    for index, default in enumerate(defaults):
        name = str(default["name"])
        key = str(default.get("key") or expert_role_key(name))
        row = by_key.get(key)
        if row is None:
            sort_order = _unused_sort_order(taken_orders, index)
            row = PanelExpertProfile(
                customer_id=customer_id,
                modules=[module],
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
            session.add(row)
            by_key[key] = row
            taken_orders.add(sort_order)
            changed += 1
        elif module not in _row_modules(row):
            row.modules = [*_row_modules(row), module]
            changed += 1
    if changed:
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            return 0
    return changed
