"""Ensure the local-dev operator account (Devbrains / erik@fremred.se)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UserAccount
from app.services.kund_store import OS_DEFAULT_KUND_SLUG, default_os_customer_id

LOCAL_LOGIN_EMAIL = "erik@fremred.se"
LOCAL_LOGIN_USER_ID = "7b297aef-09cb-4bef-b93c-622f537aa775"


async def ensure_local_login_account(session: AsyncSession) -> UserAccount:
    """Return erik@fremred.se, creating them as Devbrains admin if missing."""
    result = await session.execute(
        select(UserAccount).where(UserAccount.email == LOCAL_LOGIN_EMAIL)
    )
    account = result.scalar_one_or_none()
    customer_id = await default_os_customer_id(session)
    if account is None:
        existing_id = await session.get(UserAccount, LOCAL_LOGIN_USER_ID)
        if existing_id is not None:
            raise RuntimeError(
                f"Local login user id {LOCAL_LOGIN_USER_ID} is taken by another account"
            )
        account = UserAccount(
            id=LOCAL_LOGIN_USER_ID,
            email=LOCAL_LOGIN_EMAIL,
            role="admin",
            kund_id=customer_id,
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)
        return account

    if account.kund_id is None:
        account.kund_id = customer_id
        await session.commit()
        await session.refresh(account)
    return account


def local_login_kund_slug() -> str:
    return OS_DEFAULT_KUND_SLUG
