"""Persona expert avatar upload and storage."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from tests.conftest import TEST_CUSTOMER_ID, USER_USER_ID, mint_access_token


async def _enable_sme(client) -> None:
    response = await client.patch(
        f"/kunder/{TEST_CUSTOMER_ID}",
        json={"product": "sme"},
    )
    assert response.status_code == 200
    client.headers["Authorization"] = (
        f"Bearer {mint_access_token(sub=USER_USER_ID, email='user@test.local')}"
    )


@pytest.mark.asyncio
async def test_persona_avatar_upload_read_remove(client_db) -> None:
    client, _factory = client_db
    await _enable_sme(client)

    experts = await client.get("/personas", params={"kind": "expert", "customer_id": TEST_CUSTOMER_ID})
    assert experts.status_code == 200
    expert_id = experts.json()[0]["id"]
    path = f"/personas/{expert_id}/avatar"

    data = io.BytesIO()
    Image.new("RGB", (24, 24), "blue").save(data, "PNG")
    uploaded = await client.post(path, files={"file": ("avatar.png", data.getvalue(), "image/png")})
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["avatar_url"] == f"/personas/{expert_id}/avatar?v=1"

    detail = await client.get(f"/personas/{expert_id}")
    assert detail.json()["avatar_url"] == f"/personas/{expert_id}/avatar?v=1"

    read = await client.get(path)
    assert read.status_code == 200
    assert read.headers["content-type"] == "image/jpeg"

    removed = await client.delete(path)
    assert removed.status_code == 200
    assert removed.json()["avatar_url"] is None
    assert (await client.get(path)).status_code == 404


@pytest.mark.asyncio
async def test_persona_avatar_rejects_invalid_and_non_expert(client_db) -> None:
    client, _factory = client_db
    await _enable_sme(client)

    personas = await client.post(
        "/personas",
        json={
            "kind": "persona",
            "customer_id": TEST_CUSTOMER_ID,
            "name": "Test Persona",
            "age": 42,
            "occ": "Testare",
            "district": "Distrikt A",
        },
    )
    assert personas.status_code == 201, personas.text
    persona_id = personas.json()["id"]
    assert (await client.post(f"/personas/{persona_id}/avatar", files={"file": ("x.png", b"x", "image/png")})).status_code == 422

    experts = await client.get("/personas", params={"kind": "expert", "customer_id": TEST_CUSTOMER_ID})
    expert_id = experts.json()[0]["id"]
    before = (await client.get(f"/personas/{expert_id}/avatar")).status_code
    assert (
        await client.post(
            f"/personas/{expert_id}/avatar",
            files={"file": ("bad.png", b"<svg/>", "image/png")},
        )
    ).status_code == 422
    assert (await client.get(f"/personas/{expert_id}/avatar")).status_code == before
