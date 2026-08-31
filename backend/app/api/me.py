"""Current authenticated user profile (role + kund modules)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.models import Kund, UserAccount
from app.database.session import get_session
from app.schemas.users import MeOut

router = APIRouter(tags=["me"])


def _modules_from_kund(kund: Kund | None) -> list[str]:
    if kund is None or not isinstance(kund.available_modules, list):
        return []
    return [item for item in kund.available_modules if isinstance(item, str)]


@router.get("/me", response_model=MeOut)
async def get_me(
    user: UserAccount = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    if user.role == "admin" and user.kund_id is None:
        result = await session.execute(select(Kund))
        kunder = list(result.scalars().all())
        seen: set[str] = set()
        modules: list[str] = []
        for kund in kunder:
            for mid in _modules_from_kund(kund):
                if mid in seen:
                    continue
                seen.add(mid)
                modules.append(mid)
        return MeOut(
            id=user.id,
            email=user.email,
            role="admin",
            kund_id=None,
            kund_slug=None,
            available_modules=modules,
        )

    kund: Kund | None = None
    if user.kund_id is not None:
        kund = await session.get(Kund, user.kund_id)
    return MeOut(
        id=user.id,
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        kund_id=user.kund_id,
        kund_slug=kund.slug if kund is not None else None,
        available_modules=_modules_from_kund(kund),
    )
