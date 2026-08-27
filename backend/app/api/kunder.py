"""Customer (kund) and project (projekt) read API — scoping foundation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Kund, Projekt
from app.database.session import get_session
from app.schemas.kund import KundOut, ProjektOut
from app.services.kund_store import ensure_default_kunder

router = APIRouter(prefix="/kunder", tags=["kunder"])


def _serialize_projekt(row: Projekt) -> ProjektOut:
    return ProjektOut(
        id=row.id,
        customer_id=row.customer_id,
        name=row.name,
        slug=row.slug,
    )


def _serialize_kund(row: Kund, *, include_projekt: bool) -> KundOut:
    projekt = [_serialize_projekt(p) for p in row.projekt] if include_projekt else []
    return KundOut(id=row.id, name=row.name, slug=row.slug, projekt=projekt)


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
