"""Opt-in module gate for Tabular Review."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scope import customer_id_for_user
from app.database.models import Kund, UserAccount

MODULE_ID = "tabular_review"


def module_enabled(kund: Kund | None) -> bool:
    if kund is None or not isinstance(kund.available_modules, list):
        return False
    return MODULE_ID in kund.available_modules


async def require_tabular_review_kund(session: AsyncSession, user: UserAccount) -> Kund:
    customer_id = await customer_id_for_user(session, user)
    kund = await session.get(Kund, customer_id)
    if not module_enabled(kund):
        raise HTTPException(status_code=403, detail="tabular_review_disabled")
    if kund is None:
        raise HTTPException(status_code=403, detail="tabular_review_disabled")
    return kund
