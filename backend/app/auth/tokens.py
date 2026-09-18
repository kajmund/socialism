"""Resolve UserAccount from a raw bearer token (HTTP header or WS query)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import UserAccount
from app.serializers import utcnow

_TOKEN_ALGORITHM = "HS256"
_TOKEN_AUDIENCE = "authenticated"
_LAST_SEEN_MIN_INTERVAL = timedelta(minutes=1)

logger = logging.getLogger(__name__)


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
    return await _touch_last_seen_best_effort(session, account)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def should_touch_last_seen(account: UserAccount, *, now: datetime | None = None) -> bool:
    seen = account.last_seen_at
    if seen is None:
        return True
    current = now or utcnow()
    return current - _aware(seen) >= _LAST_SEEN_MIN_INTERVAL


async def _touch_last_seen_best_effort(session: AsyncSession, account: UserAccount) -> UserAccount:
    """Telemetry write. Lock or commit failure must not fail a valid auth read."""
    if not should_touch_last_seen(account):
        return account
    account_id = account.id
    account.last_seen_at = utcnow()
    try:
        await session.commit()
        return account
    except Exception as exc:
        if isinstance(exc, OperationalError) and "database is locked" in str(exc).lower():
            logger.info(
                "user_accounts.last_seen_at skipped because sqlite is busy account_id=%s",
                account_id,
            )
        else:
            logger.warning(
                "user_accounts.last_seen_at update failed account_id=%s",
                account_id,
                exc_info=True,
            )
        await session.rollback()
        restored = await session.get(UserAccount, account_id)
        return restored if restored is not None else account
