"""Local-only login shortcut. Disabled unless ALLOW_LOCAL_LOGIN is set."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import mint_access_token
from app.config import settings
from app.database.session import get_session
from app.schemas.users import LocalLoginOut
from app.services.local_login import (
    LOCAL_LOGIN_EMAIL,
    ensure_local_login_account,
    local_login_kund_slug,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _request_host(request: Request) -> str:
    raw = (request.headers.get("host") or "").strip().lower()
    if raw.startswith("["):
        end = raw.find("]")
        return raw[1:end] if end != -1 else raw
    return raw.split(":")[0]


def _require_local_login(request: Request) -> None:
    if not settings.allow_local_login:
        raise HTTPException(status_code=404, detail="not_found")
    if _request_host(request) not in _LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="local_login_forbidden")


@router.post("/local-login", response_model=LocalLoginOut)
async def local_login(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LocalLoginOut:
    _require_local_login(request)
    account = await ensure_local_login_account(session)
    token = mint_access_token(user_id=account.id, email=account.email)
    return LocalLoginOut(
        access_token=token,
        email=LOCAL_LOGIN_EMAIL,
        user_id=account.id,
        kund_slug=local_login_kund_slug(),
    )
