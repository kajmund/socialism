"""GET /me returns role + kund modules for the authenticated user."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_me_admin_returns_union_modules(client) -> None:
    response = await client.get("/me")
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["kund_id"] is None
    assert body["kund_slug"] is None
    assert "politik" in body["available_modules"]
    assert "dd" in body["available_modules"]
    assert "expertgranskning" in body["available_modules"]


@pytest.mark.asyncio
async def test_me_admin_keeps_expertgranskning_if_unchecked(client) -> None:
    listed = await client.get("/kunder")
    assert listed.status_code == 200
    for row in listed.json():
        modules = [mid for mid in row["available_modules"] if mid != "expertgranskning"]
        patched = await client.patch(
            f"/kunder/{row['id']}",
            json={"available_modules": modules or ["politik"]},
        )
        assert patched.status_code == 200
    response = await client.get("/me")
    assert response.status_code == 200
    assert "expertgranskning" in response.json()["available_modules"]


@pytest.mark.asyncio
async def test_me_user_returns_kund_modules(user_client) -> None:
    response = await user_client.get("/me")
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "user"
    assert body["kund_id"] == 1
    assert body["kund_slug"] == "devbrains"
    assert body["available_modules"] == ["politik", "expertgranskning"]


@pytest.mark.asyncio
async def test_me_requires_auth(client) -> None:
    client.headers.pop("Authorization", None)
    response = await client.get("/me")
    assert response.status_code == 401
