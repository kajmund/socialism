"""Configuration ssr_temperature field for report SSR."""

from __future__ import annotations

import pytest

from app.schemas.domain import DEFAULT_SSR_TEMPERATURE


@pytest.mark.asyncio
async def test_list_configurations_includes_ssr_temperature(client):
    res = await client.get("/configurations")
    assert res.status_code == 200
    rows = res.json()
    assert rows
    assert rows[0]["ssr_temperature"] == DEFAULT_SSR_TEMPERATURE


@pytest.mark.asyncio
async def test_patch_ssr_temperature(client):
    configs = (await client.get("/configurations")).json()
    cfg_id = configs[0]["id"]
    res = await client.patch(
        f"/configurations/{cfg_id}",
        json={"ssr_temperature": 0.001},
    )
    assert res.status_code == 200, res.text
    assert res.json()["ssr_temperature"] == 0.001
    again = await client.get(f"/configurations/{cfg_id}")
    assert again.json()["ssr_temperature"] == 0.001


@pytest.mark.asyncio
async def test_patch_rejects_non_positive_temperature(client):
    configs = (await client.get("/configurations")).json()
    cfg_id = configs[0]["id"]
    res = await client.patch(
        f"/configurations/{cfg_id}",
        json={"ssr_temperature": 0},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_configuration_with_ssr_temperature(client):
    res = await client.post(
        "/configurations",
        json={
            "name": "Temp probe",
            "language": "sv",
            "ssr_temperature": 0.05,
            "is_active": False,
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["ssr_temperature"] == 0.05
