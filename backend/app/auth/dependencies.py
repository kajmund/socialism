"""FastAPI dependencies that verify Supabase JWTs and load UserAccount."""

from __future__ import annotations

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import UserAccount
from app.database.session import get_session
from app.serializers import utcnow


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> UserAccount:
    if not authorization or not authorization.strip():
        raise HTTPException(status_code=401, detail="invalid_token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="invalid_token")
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid_token") from exc
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="invalid_token")
    account = await session.get(UserAccount, user_id)
    if account is None:
        # Valid Supabase token but not invited — no self-signup.
        raise HTTPException(status_code=403, detail="not_provisioned")
    account.last_seen_at = utcnow()
    await session.commit()
    return account


def require_admin(user: UserAccount = Depends(get_current_user)) -> UserAccount:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin_required")
    return user
