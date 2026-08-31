"""Supabase Auth Admin invite via HTTP (service_role key)."""

from __future__ import annotations

import httpx

from app.config import settings


class SupabaseInviteError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


async def invite_user_by_email(email: str) -> dict:
    """
    POST {SUPABASE_URL}/auth/v1/invite

    Contract (GoTrue Admin): body ``{email, data?}``, headers
    Authorization Bearer service_role + apikey service_role.
    Returns the created User object including ``id``.
    """
    base = settings.supabase_url.rstrip("/")
    url = f"{base}/auth/v1/invite"
    headers = {
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "apikey": settings.supabase_service_role_key,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json={"email": email})
    if response.status_code >= 400:
        detail = response.text
        try:
            body = response.json()
            detail = str(body.get("msg") or body.get("error_description") or body.get("message") or detail)
        except Exception:
            pass
        raise SupabaseInviteError(detail, status_code=response.status_code)
    data = response.json()
    if not isinstance(data, dict) or not data.get("id"):
        raise SupabaseInviteError("invite response missing user id")
    return data
