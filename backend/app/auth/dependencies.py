"""FastAPI dependencies that verify Supabase JWTs and load UserAccount."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import user_from_bearer_token
from app.database.models import UserAccount
from app.database.session import get_session


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> UserAccount:
    return await user_from_bearer_token(session, authorization)


def require_admin(user: UserAccount = Depends(get_current_user)) -> UserAccount:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin_required")
    return user
