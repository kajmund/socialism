"""Tests for expert panel populations (FAS C)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.kund_store import BOLAG_DEMO_KUND_SLUG


async def _bolag_customer_id(client: AsyncClient) -> int:
    listed = await client.get("/kunder")
    assert listed.status_code == 200
    return next(row["id"] for row in listed.json() if row["slug"] == BOLAG_DEMO_KUND_SLUG)


async def _create_expert_panel(
    client: AsyncClient,
    *,
    name: str,
    expert_ids: list[str],
) -> dict:
    created = await client.post(
        "/populations",
        json={
            "kind": "expert_panel",
            "name": name,
            "include_persona_ids": expert_ids,
            "recipe": {"size": len(expert_ids), "dist": {}},
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


@pytest.mark.asyncio
async def test_create_expert_panel_is_synchronous(client: AsyncClient):
    bolag_id = await _bolag_customer_id(client)

    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    assert experts.status_code == 200
    expert_ids = [row["id"] for row in experts.json()[:2]]
    assert len(expert_ids) >= 2

    body = await _create_expert_panel(
        client,
        name="Test expert panel",
        expert_ids=expert_ids,
    )
    assert body["kind"] == "expert_panel"
    assert len(body["members"]) == len(expert_ids)
    assert {member["id"] for member in body["members"]} == set(expert_ids)


@pytest.mark.asyncio
async def test_create_expert_panel_requires_experts(client: AsyncClient):
    created = await client.post(
        "/populations",
        json={
            "kind": "expert_panel",
            "name": "Empty panel",
            "include_persona_ids": [],
            "recipe": {"size": 1, "dist": {}},
        },
    )
    assert created.status_code == 400


@pytest.mark.asyncio
async def test_expert_panel_modules_tag_and_filter(client: AsyncClient):
    bolag_id = await _bolag_customer_id(client)
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    expert_id = experts.json()[0]["id"]

    tagged = await client.post(
        "/populations",
        json={
            "kind": "expert_panel",
            "name": "Tagged expertgranskning panel",
            "include_persona_ids": [expert_id],
            "recipe": {
                "size": 1,
                "dist": {},
                "modules": ["expertgranskning", "dd", "expertgranskning"],
            },
        },
    )
    assert tagged.status_code == 201, tagged.text
    assert tagged.json()["modules"] == ["expertgranskning", "dd"]

    untagged = await _create_expert_panel(
        client, name="Untagged filter panel", expert_ids=[expert_id]
    )
    assert untagged["modules"] == []

    listed = await client.get(
        "/populations",
        params={"kind": "expert_panel", "module": "expertgranskning"},
    )
    assert listed.status_code == 200
    ids = {row["id"] for row in listed.json()}
    assert tagged.json()["id"] in ids
    assert untagged["id"] not in ids
    assert all(row["kind"] == "expert_panel" for row in listed.json())
    assert all("expertgranskning" in row["modules"] for row in listed.json())

    updated = await client.put(
        f"/populations/{untagged['id']}",
        json={"modules": ["expertgranskning"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["modules"] == ["expertgranskning"]

    blocked = await client.put(
        f"/populations/{untagged['id']}",
        json={"modules": ["politik"]},
    )
    assert blocked.status_code == 400

    recipe_blocked = await client.put(
        f"/populations/{untagged['id']}",
        json={"recipe": {"size": 1, "dist": {}, "modules": ["dd"]}},
    )
    assert recipe_blocked.status_code == 400


@pytest.mark.asyncio
async def test_list_expert_panels_filter(client: AsyncClient):
    bolag_id = await _bolag_customer_id(client)
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    expert_id = experts.json()[0]["id"]

    await _create_expert_panel(client, name="Filter test panel", expert_ids=[expert_id])

    listed = await client.get("/populations", params={"kind": "expert_panel"})
    assert listed.status_code == 200
    rows = listed.json()
    assert rows
    assert all(row["kind"] == "expert_panel" for row in rows)


@pytest.mark.asyncio
async def test_dd_campaign_expert_panel_id(client: AsyncClient):
    bolag_id = await _bolag_customer_id(client)
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    expert_ids = [row["id"] for row in experts.json()[:4]]

    panel = await _create_expert_panel(
        client,
        name="Campaign expert panel",
        expert_ids=expert_ids,
    )
    panel_id = panel["id"]

    campaign = await client.post("/dd/campaigns", json={"title": "Panel campaign"})
    assert campaign.status_code == 201
    campaign_id = campaign.json()["id"]

    updated = await client.patch(
        f"/dd/campaigns/{campaign_id}",
        json={"expert_panel_id": panel_id},
    )
    assert updated.status_code == 200
    assert updated.json()["expert_panel_id"] == panel_id


@pytest.mark.asyncio
async def test_dd_campaign_panel_assignments(client: AsyncClient):
    bolag_id = await _bolag_customer_id(client)
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    expert_ids = [row["id"] for row in experts.json()[:2]]

    panel = await _create_expert_panel(
        client,
        name="Assignment expert panel",
        expert_ids=expert_ids,
    )
    panel_id = panel["id"]

    campaign = await client.post(
        "/dd/campaigns",
        json={"title": "Assignment campaign", "criteria": {"alder_min": 0, "alder_max": 50, "omrade": ""}},
    )
    assert campaign.status_code == 201
    campaign_id = campaign.json()["id"]
    sourced = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    assert sourced.status_code == 200
    candidate_id = sourced.json()["candidates"][0]["id"]

    updated = await client.patch(
        f"/dd/campaigns/{campaign_id}",
        json={"panel_assignments": {candidate_id: panel_id}},
    )
    assert updated.status_code == 200
    assert updated.json()["panel_assignments"] == {candidate_id: panel_id}

    session_resp = await client.post(
        f"/dd/campaigns/{campaign_id}/panel-sessions",
        json={"campaign_id": campaign_id, "candidate_id": candidate_id},
    )
    assert session_resp.status_code == 201
    labels = [slot["label"] for slot in session_resp.json()["config"]["expert_slots"]]
    assert labels

    bad = await client.patch(
        f"/dd/campaigns/{campaign_id}",
        json={"panel_assignments": {candidate_id: 999999}},
    )
    assert bad.status_code == 400
