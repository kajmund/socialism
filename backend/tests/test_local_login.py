"""POST /auth/local-login is off by default and only serves localhost."""

from __future__ import annotations

import pytest

from app.config import settings
from app.services.local_login import LOCAL_LOGIN_EMAIL


@pytest.fixture
def local_login_enabled():
    previous = settings.allow_local_login
    settings.allow_local_login = True
    try:
        yield
    finally:
        settings.allow_local_login = previous


@pytest.mark.asyncio
async def test_local_login_disabled_returns_404(client) -> None:
    previous = settings.allow_local_login
    settings.allow_local_login = False
    try:
        response = await client.post("/auth/local-login", headers={"Host": "localhost"})
        assert response.status_code == 404
    finally:
        settings.allow_local_login = previous


@pytest.mark.asyncio
async def test_local_login_rejects_non_local_host(client, local_login_enabled) -> None:
    response = await client.post("/auth/local-login")
    assert response.status_code == 403
    assert response.json()["detail"] == "local_login_forbidden"


@pytest.mark.asyncio
async def test_local_login_mints_token_for_devbrains_erik(
    client, local_login_enabled
) -> None:
    response = await client.post("/auth/local-login", headers={"Host": "localhost"})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == LOCAL_LOGIN_EMAIL
    assert body["kund_slug"] == "devbrains"
    token = body["access_token"]
    assert token

    me = await client.get(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    profile = me.json()
    assert profile["email"] == LOCAL_LOGIN_EMAIL
    assert profile["role"] == "admin"
    assert profile["kund_slug"] == "devbrains"
    assert "politik" in profile["available_modules"]
