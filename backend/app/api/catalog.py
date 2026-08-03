"""Grunddata catalog lists for persona composer dropdowns."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CatalogList
from app.database.session import get_session
from app.schemas.domain import CatalogListOut, CatalogListUpdate, format_date
from app.serializers import utcnow
from app.services.catalog_defaults import SECTION_ORDER
from app.services.catalog_items import catalog_items_as_json, coerce_catalog_items
from app.services.catalog_store import ensure_catalog_defaults

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _serialize(row: CatalogList) -> CatalogListOut:
    return CatalogListOut(
        key=row.key,
        section=row.section,  # type: ignore[arg-type]
        title=row.title,
        items=coerce_catalog_items(row.items),
        updated_at=format_date(row.updated_at) if row.updated_at else "",
    )


def _sort_key(row: CatalogList) -> tuple[int, str]:
    try:
        section_idx = SECTION_ORDER.index(row.section)
    except ValueError:
        section_idx = len(SECTION_ORDER)
    return (section_idx, row.title)


@router.get("", response_model=list[CatalogListOut])
async def list_catalog(
    session: AsyncSession = Depends(get_session),
) -> list[CatalogListOut]:
    await ensure_catalog_defaults(session)
    result = await session.execute(select(CatalogList))
    rows = list(result.scalars().all())
    rows.sort(key=_sort_key)
    return [_serialize(row) for row in rows]


@router.get("/{key}", response_model=CatalogListOut)
async def get_catalog_list(
    key: str,
    session: AsyncSession = Depends(get_session),
) -> CatalogListOut:
    await ensure_catalog_defaults(session)
    row = await session.get(CatalogList, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Catalog list not found")
    return _serialize(row)


@router.put("/{key}", response_model=CatalogListOut)
async def update_catalog_list(
    key: str,
    body: CatalogListUpdate,
    session: AsyncSession = Depends(get_session),
) -> CatalogListOut:
    await ensure_catalog_defaults(session)
    row = await session.get(CatalogList, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Catalog list not found")
    row.items = catalog_items_as_json(body.items)
    row.updated_at = utcnow()
    await session.commit()
    await session.refresh(row)
    return _serialize(row)
