"""Default customers (kunder) and projects (projekt) for data scoping."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Kund, Projekt
from app.serializers import utcnow

# Stable slugs for seed / auth mapping (no backend auth in this phase).
OS_DEFAULT_KUND_SLUG = "devbrains"
BOLAG_DEMO_KUND_SLUG = "bolag-demo"
DEFAULT_PROJEKT_SLUG = "default"

_SEED_KUNDER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (OS_DEFAULT_KUND_SLUG, "Devbrains", ("politik",)),
    (BOLAG_DEMO_KUND_SLUG, "Bolag demo", ("dd",)),
)


async def ensure_default_kunder(session: AsyncSession) -> bool:
    """Insert default kunder + a default projekt under the OS kund if missing."""
    changed = False
    now = utcnow()
    os_kund_id: int | None = None

    for slug, name, modules in _SEED_KUNDER:
        result = await session.execute(select(Kund).where(Kund.slug == slug))
        row = result.scalar_one_or_none()
        if row is None:
            session.add(
                Kund(
                    name=name,
                    slug=slug,
                    available_modules=list(modules),
                    created_at=now,
                    updated_at=now,
                )
            )
            changed = True

    if changed:
        await session.flush()

    result = await session.execute(select(Kund).where(Kund.slug == OS_DEFAULT_KUND_SLUG))
    os_kund = result.scalar_one_or_none()
    if os_kund is None:
        return changed
    os_kund_id = int(os_kund.id)

    result = await session.execute(
        select(Projekt).where(
            Projekt.customer_id == os_kund_id,
            Projekt.slug == DEFAULT_PROJEKT_SLUG,
        )
    )
    if result.scalar_one_or_none() is None:
        session.add(
            Projekt(
                customer_id=os_kund_id,
                name="Default",
                slug=DEFAULT_PROJEKT_SLUG,
                created_at=now,
                updated_at=now,
            )
        )
        changed = True

    if changed:
        await session.commit()
    return changed


async def default_os_customer_id(session: AsyncSession) -> int:
    """Primary Opinionssimulator tenant — fail loud if seed was not run."""
    await ensure_default_kunder(session)
    result = await session.execute(select(Kund).where(Kund.slug == OS_DEFAULT_KUND_SLUG))
    row = result.scalar_one_or_none()
    if row is None:
        raise RuntimeError(
            f"Default kund {OS_DEFAULT_KUND_SLUG!r} missing — run ensure_default_kunder"
        )
    return int(row.id)


async def bolag_demo_customer_id(session: AsyncSession) -> int:
    """DD bolag demo tenant — mapped from frontend bolag login in a later auth card."""
    await ensure_default_kunder(session)
    result = await session.execute(select(Kund).where(Kund.slug == BOLAG_DEMO_KUND_SLUG))
    row = result.scalar_one_or_none()
    if row is None:
        raise RuntimeError(
            f"Bolag demo kund {BOLAG_DEMO_KUND_SLUG!r} missing — run ensure_default_kunder"
        )
    return int(row.id)


async def default_os_project_id(session: AsyncSession) -> int:
    """Default project under the OS tenant — fail loud if seed was not run."""
    customer_id = await default_os_customer_id(session)
    result = await session.execute(
        select(Projekt).where(
            Projekt.customer_id == customer_id,
            Projekt.slug == DEFAULT_PROJEKT_SLUG,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise RuntimeError(
            f"Default projekt {DEFAULT_PROJEKT_SLUG!r} missing — run ensure_default_kunder"
        )
    return int(row.id)
