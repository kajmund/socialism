"""Admin /users invite API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import TEST_CUSTOMER_ID, mint_access_token, USER_USER_ID


@pytest.mark.asyncio
async def test_non_admin_cannot_list_users(user_client) -> None:
    response = await user_client.get("/users")
    assert response.status_code == 403
    assert response.json()["detail"] == "admin_required"


@pytest.mark.asyncio
async def test_admin_lists_seeded_users(client) -> None:
    response = await client.get("/users")
    assert response.status_code == 200
    emails = {row["email"] for row in response.json()}
    assert "admin@test.local" in emails
    assert "user@test.local" in emails


@pytest.mark.asyncio
async def test_admin_invite_creates_user_account(client, client_db) -> None:
    invited_id = "11111111-1111-4111-8111-111111111111"
    with patch(
        "app.api.users.invite_user_by_email",
        new=AsyncMock(return_value={"id": invited_id, "email": "invitee@example.com"}),
    ):
        response = await client.post(
            "/users/invite",
            json={
                "email": "invitee@example.com",
                "role": "user",
                "kund_id": TEST_CUSTOMER_ID,
            },
        )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == invited_id
    assert body["email"] == "invitee@example.com"
    assert body["role"] == "user"
    assert body["kund_id"] == TEST_CUSTOMER_ID


@pytest.mark.asyncio
async def test_invite_admin_rejects_kund_id(client) -> None:
    response = await client.post(
        "/users/invite",
        json={"email": "boss@example.com", "role": "admin", "kund_id": 1},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invite_user_requires_kund_id(client) -> None:
    response = await client.post(
        "/users/invite",
        json={"email": "no-kund@example.com", "role": "user"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_user_role(client) -> None:
    response = await client.patch(
        f"/users/{USER_USER_ID}",
        json={"role": "bolag", "kund_id": TEST_CUSTOMER_ID},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "bolag"


@pytest.mark.asyncio
async def test_non_admin_cannot_invite(user_client) -> None:
    response = await user_client.post(
        "/users/invite",
        json={"email": "x@example.com", "role": "user", "kund_id": TEST_CUSTOMER_ID},
    )
    assert response.status_code == 403
