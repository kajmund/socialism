"""Resolve UserAccount from a raw bearer token (HTTP header or WS query)."""

from __future__ import annotations

import jwt
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import UserAccount
from app.serializers import utcnow


async def user_from_bearer_token(session: AsyncSession, token: str | None) -> UserAccount:
    if not token or not token.strip():
        raise HTTPException(status_code=401, detail="invalid_token")
    raw = token.removeprefix("Bearer ").strip()
    if not raw:
        raise HTTPException(status_code=401, detail="invalid_token")
    try:
        payload = jwt.decode(
            raw,
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
        raise HTTPException(status_code=403, detail="not_provisioned")
    account.last_seen_at = utcnow()
    await session.commit()
    return account
