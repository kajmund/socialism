"""Resolve UserAccount from a raw bearer token (HTTP header or WS query)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import UserAccount
from app.serializers import utcnow

_TOKEN_ALGORITHM = "HS256"
_TOKEN_AUDIENCE = "authenticated"


def mint_access_token(
    *,
    user_id: str,
    email: str,
    expires_delta: timedelta = timedelta(days=7),
) -> str:
    """HS256 access token accepted by user_from_bearer_token (same secret as Supabase)."""
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "email": email,
        "aud": _TOKEN_AUDIENCE,
        "role": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.supabase_jwt_secret, algorithm=_TOKEN_ALGORITHM)


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
            algorithms=[_TOKEN_ALGORITHM],
            audience=_TOKEN_AUDIENCE,
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
