"""Admin user management — list, invite, patch. Entire router is admin-only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_admin
from app.database.models import Kund, UserAccount
from app.database.session import get_session
from app.schemas.users import UserAccountOut, UserAccountUpdate, UserInviteRequest
from app.services.supabase_admin import SupabaseInviteError, invite_user_by_email

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_admin)],
)


def _serialize(row: UserAccount) -> UserAccountOut:
    kund_name = row.kund.name if row.kund is not None else None
    return UserAccountOut(
        id=row.id,
        email=row.email,
        role=row.role,  # type: ignore[arg-type]
        kund_id=row.kund_id,
        kund_name=kund_name,
        invited_at=row.invited_at,
        last_seen_at=row.last_seen_at,
    )


@router.get("", response_model=list[UserAccountOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _admin: UserAccount = Depends(require_admin),
) -> list[UserAccountOut]:
    result = await session.execute(
        select(UserAccount)
        .options(selectinload(UserAccount.kund))
        .order_by(UserAccount.email.asc())
    )
    return [_serialize(row) for row in result.scalars().all()]


@router.post("/invite", response_model=UserAccountOut, status_code=201)
async def invite_user(
    body: UserInviteRequest,
    session: AsyncSession = Depends(get_session),
    _admin: UserAccount = Depends(require_admin),
) -> UserAccountOut:
    existing = await session.execute(
        select(UserAccount).where(UserAccount.email == body.email)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="email_already_provisioned")

    if body.kund_id is not None:
        kund = await session.get(Kund, body.kund_id)
        if kund is None:
            raise HTTPException(status_code=400, detail="kund_not_found")

    try:
        invited = await invite_user_by_email(body.email)
    except SupabaseInviteError as exc:
        status = 502
        if exc.status_code == 422:
            status = 409
        elif exc.status_code is not None and 400 <= exc.status_code < 500:
            status = exc.status_code
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    user_id = str(invited["id"])
    account = UserAccount(
        id=user_id,
        email=body.email,
        role=body.role,
        kund_id=body.kund_id,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    result = await session.execute(
        select(UserAccount)
        .options(selectinload(UserAccount.kund))
        .where(UserAccount.id == account.id)
    )
    return _serialize(result.scalar_one())


@router.patch("/{user_id}", response_model=UserAccountOut)
async def patch_user(
    user_id: str,
    body: UserAccountUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: UserAccount = Depends(require_admin),
) -> UserAccountOut:
    account = await session.get(UserAccount, user_id)
    if account is None:
        raise HTTPException(status_code=404, detail="user_not_found")

    new_role = body.role if body.role is not None else account.role
    # kund_id: explicit null only when role becomes admin; otherwise keep or set.
    if body.role == "admin":
        new_kund_id: int | None = None
    elif "kund_id" in body.model_fields_set:
        new_kund_id = body.kund_id
    else:
        new_kund_id = account.kund_id

    if new_role == "admin":
        new_kund_id = None
    elif new_kund_id is None:
        raise HTTPException(status_code=400, detail=f"{new_role} requires kund_id")

    if new_kund_id is not None:
        kund = await session.get(Kund, new_kund_id)
        if kund is None:
            raise HTTPException(status_code=400, detail="kund_not_found")

    account.role = new_role
    account.kund_id = new_kund_id
    await session.commit()

    result = await session.execute(
        select(UserAccount)
        .options(selectinload(UserAccount.kund))
        .where(UserAccount.id == user_id)
    )
    return _serialize(result.scalar_one())
