"""Customer (kund) and project (projekt) read API — scoping foundation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Kund, Projekt
from app.database.session import get_session
from app.modules.registry import MODULE_REGISTRY
from app.schemas.kund import KundOut, KundUpdate, ProjektOut
from app.serializers import utcnow
from app.services.kund_store import ensure_default_kunder

router = APIRouter(prefix="/kunder", tags=["kunder"])


def _serialize_projekt(row: Projekt) -> ProjektOut:
    return ProjektOut(
        id=row.id,
        customer_id=row.customer_id,
        name=row.name,
        slug=row.slug,
    )


def _available_modules(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str)]


def _serialize_kund(row: Kund, *, include_projekt: bool) -> KundOut:
    projekt = [_serialize_projekt(p) for p in row.projekt] if include_projekt else []
    return KundOut(
        id=row.id,
        name=row.name,
        slug=row.slug,
        available_modules=_available_modules(row.available_modules),
        projekt=projekt,
    )


def _normalize_available_modules(ids: list[str]) -> list[str]:
    known = set(MODULE_REGISTRY)
    seen: set[str] = set()
    out: list[str] = []
    unknown: list[str] = []
    for raw in ids:
        item = raw.strip()
        if not item:
            raise HTTPException(status_code=400, detail="available_modules contains an empty id")
        if item not in known:
            unknown.append(item)
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown module id(s): {', '.join(unknown)}",
        )
    return out


@router.get("", response_model=list[KundOut])
async def list_kunder(
    session: AsyncSession = Depends(get_session),
) -> list[KundOut]:
    await ensure_default_kunder(session)
    result = await session.execute(
        select(Kund)
        .options(selectinload(Kund.projekt))
        .order_by(Kund.id.asc())
    )
    rows = list(result.scalars().unique().all())
    return [_serialize_kund(row, include_projekt=True) for row in rows]


@router.get("/{kund_id}", response_model=KundOut)
async def get_kund(
    kund_id: int,
    session: AsyncSession = Depends(get_session),
) -> KundOut:
    await ensure_default_kunder(session)
    result = await session.execute(
        select(Kund)
        .where(Kund.id == kund_id)
        .options(selectinload(Kund.projekt))
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Kund not found")
    return _serialize_kund(row, include_projekt=True)


@router.patch("/{kund_id}", response_model=KundOut)
async def patch_kund(
    kund_id: int,
    body: KundUpdate,
    session: AsyncSession = Depends(get_session),
) -> KundOut:
    await ensure_default_kunder(session)
    result = await session.execute(
        select(Kund)
        .where(Kund.id == kund_id)
        .options(selectinload(Kund.projekt))
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Kund not found")
    if body.available_modules is None:
        raise HTTPException(status_code=400, detail="PATCH body must include available_modules")
    row.available_modules = _normalize_available_modules(body.available_modules)
    row.updated_at = utcnow()
    await session.commit()
    await session.refresh(row)
    return _serialize_kund(row, include_projekt=True)


@router.get("/{kund_id}/projekt", response_model=list[ProjektOut])
async def list_projekt_for_kund(
    kund_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[ProjektOut]:
    await ensure_default_kunder(session)
    kund = await session.get(Kund, kund_id)
    if kund is None:
        raise HTTPException(status_code=404, detail="Kund not found")
    result = await session.execute(
        select(Projekt).where(Projekt.customer_id == kund_id).order_by(Projekt.id.asc())
    )
    return [_serialize_projekt(row) for row in result.scalars().all()]
