"""Tests for expert panel populations (FAS C)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services import jobs as jobs_service
from app.services.kund_store import BOLAG_DEMO_KUND_SLUG


async def _bolag_customer_id(client: AsyncClient) -> int:
    listed = await client.get("/kunder")
    assert listed.status_code == 200
    return next(row["id"] for row in listed.json() if row["slug"] == BOLAG_DEMO_KUND_SLUG)


@pytest.mark.asyncio
async def test_expert_panel_job_creates_population(client: AsyncClient):
    jobs_service.set_schedule_hook(lambda _job_id: None)
    bolag_id = await _bolag_customer_id(client)

    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    assert experts.status_code == 200
    expert_ids = [row["id"] for row in experts.json()[:2]]
    assert len(expert_ids) >= 2

    created = await client.post(
        "/jobs",
        json={
            "kind": "population_generate",
            "label": "Test panel",
            "request": {
                "name": "Test expert panel",
                "kind": "expert_panel",
                "customer_id": bolag_id,
                "recipe": {"size": len(expert_ids), "dist": {}},
                "include_persona_ids": expert_ids,
            },
        },
    )
    assert created.status_code == 202
    job_id = created.json()["id"]
    await jobs_service._run_job(job_id)

    got = await client.get(f"/jobs/{job_id}")
    assert got.status_code == 200
    payload = got.json()
    assert payload["status"] == "succeeded"
    assert payload["result"]["population_kind"] == "expert_panel"
    assert payload["result"]["member_count"] == len(expert_ids)

    pop = await client.get(f"/populations/{payload['result']['population_id']}")
    assert pop.status_code == 200
    body = pop.json()
    assert body["kind"] == "expert_panel"
    assert len(body["members"]) == len(expert_ids)


@pytest.mark.asyncio
async def test_list_expert_panels_filter(client: AsyncClient):
    jobs_service.set_schedule_hook(lambda _job_id: None)
    bolag_id = await _bolag_customer_id(client)
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    expert_id = experts.json()[0]["id"]

    created = await client.post(
        "/jobs",
        json={
            "kind": "population_generate",
            "label": "Filter panel",
            "request": {
                "name": "Filter test panel",
                "kind": "expert_panel",
                "customer_id": bolag_id,
                "recipe": {"size": 1, "dist": {}},
                "include_persona_ids": [expert_id],
            },
        },
    )
    job_id = created.json()["id"]
    await jobs_service._run_job(job_id)

    listed = await client.get("/populations", params={"kind": "expert_panel"})
    assert listed.status_code == 200
    rows = listed.json()
    assert rows
    assert all(row["kind"] == "expert_panel" for row in rows)


@pytest.mark.asyncio
async def test_dd_campaign_expert_panel_id(client: AsyncClient):
    jobs_service.set_schedule_hook(lambda _job_id: None)
    bolag_id = await _bolag_customer_id(client)
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    expert_ids = [row["id"] for row in experts.json()[:4]]

    job = await client.post(
        "/jobs",
        json={
            "kind": "population_generate",
            "label": "Campaign panel",
            "request": {
                "name": "Campaign expert panel",
                "kind": "expert_panel",
                "customer_id": bolag_id,
                "recipe": {"size": len(expert_ids), "dist": {}},
                "include_persona_ids": expert_ids,
            },
        },
    )
    await jobs_service._run_job(job.json()["id"])
    panel_id = (await client.get(f"/jobs/{job.json()['id']}")).json()["result"]["population_id"]

    campaign = await client.post("/dd/campaigns", json={"title": "Panel campaign"})
    assert campaign.status_code == 201
    campaign_id = campaign.json()["id"]

    updated = await client.patch(
        f"/dd/campaigns/{campaign_id}",
        json={"expert_panel_id": panel_id},
    )
    assert updated.status_code == 200
    assert updated.json()["expert_panel_id"] == panel_id
