"""Customer (kund) and project (projekt) read API — scoping foundation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user, require_admin
from app.auth.scope import assert_kund_access
from app.database.models import Kund, Projekt, UserAccount
from app.database.session import get_session
from app.modules.registry import MODULE_REGISTRY
from app.schemas.kund import KundCreate, KundOut, KundUpdate, ProjektOut
from app.serializers import utcnow
from app.services.dd.default_experts import ensure_default_expert_personas
from app.services.kund_store import DEFAULT_PROJEKT_SLUG, ensure_default_kunder
from app.services.object_storage import ObjectStorageError
from app.services.panel.module_defaults import ensure_module_panel_defaults
from app.services.stored_objects import ensure_kund_bucket

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


def _normalize_slug(raw: str) -> str:
    slug = raw.strip().lower().replace(" ", "-")
    cleaned = "".join(ch for ch in slug if ch.isalnum() or ch == "-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


@router.get("", response_model=list[KundOut])
async def list_kunder(
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[KundOut]:
    await ensure_default_kunder(session)
    stmt = select(Kund).options(selectinload(Kund.projekt)).order_by(Kund.id.asc())
    if user.role != "admin":
        assert_kund_access(user, user.kund_id)
        stmt = stmt.where(Kund.id == user.kund_id)
    result = await session.execute(stmt)
    rows = list(result.scalars().unique().all())
    return [_serialize_kund(row, include_projekt=True) for row in rows]


@router.post("", response_model=KundOut, status_code=201)
async def create_kund(
    body: KundCreate,
    session: AsyncSession = Depends(get_session),
    _admin: UserAccount = Depends(require_admin),
) -> KundOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    slug = _normalize_slug(body.slug)
    if not slug:
        raise HTTPException(status_code=400, detail="slug is required")
    existing = await session.execute(select(Kund).where(Kund.slug == slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="slug already exists")
    modules = _normalize_available_modules(body.available_modules)
    now = utcnow()
    row = Kund(
        name=name,
        slug=slug,
        available_modules=modules,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    session.add(
        Projekt(
            customer_id=row.id,
            name="Default",
            slug=DEFAULT_PROJEKT_SLUG,
            created_at=now,
            updated_at=now,
        )
    )
    try:
        await ensure_kund_bucket(row)
    except ObjectStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await ensure_module_panel_defaults(session, customer_id=row.id)
    await ensure_default_expert_personas(session, customer_id=row.id)
    await session.commit()
    result = await session.execute(
        select(Kund).where(Kund.id == row.id).options(selectinload(Kund.projekt))
    )
    created = result.scalar_one()
    return _serialize_kund(created, include_projekt=True)


@router.get("/{kund_id}", response_model=KundOut)
async def get_kund(
    kund_id: int,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> KundOut:
    assert_kund_access(user, kund_id)
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
    _admin: UserAccount = Depends(require_admin),
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
    try:
        await ensure_kund_bucket(row)
    except ObjectStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(row)
    return _serialize_kund(row, include_projekt=True)


@router.get("/{kund_id}/projekt", response_model=list[ProjektOut])
async def list_projekt_for_kund(
    kund_id: int,
    session: AsyncSession = Depends(get_session),
    user: UserAccount = Depends(get_current_user),
) -> list[ProjektOut]:
    assert_kund_access(user, kund_id)
    await ensure_default_kunder(session)
    kund = await session.get(Kund, kund_id)
    if kund is None:
        raise HTTPException(status_code=404, detail="Kund not found")
    result = await session.execute(
        select(Projekt).where(Projekt.customer_id == kund_id).order_by(Projekt.id.asc())
    )
    return [_serialize_projekt(row) for row in result.scalars().all()]
