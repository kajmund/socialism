"""Foundation: PanelSession.panel_id + project_id (no new Panel table)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.services.kund_store import BOLAG_DEMO_KUND_SLUG, OS_DEFAULT_KUND_SLUG
from app.services.panel.schemas import PanelSessionConfig, PanelSessionCreate


async def _kund_id(client: AsyncClient, slug: str) -> int:
    listed = await client.get("/kunder")
    assert listed.status_code == 200
    return next(row["id"] for row in listed.json() if row["slug"] == slug)


async def _create_expert_panel(client: AsyncClient, *, name: str) -> int:
    bolag_id = await _kund_id(client, BOLAG_DEMO_KUND_SLUG)
    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    assert experts.status_code == 200
    expert_ids = [row["id"] for row in experts.json()[:2]]
    assert len(expert_ids) >= 2
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
    return int(created.json()["id"])


@pytest.mark.asyncio
async def test_create_session_from_panel_id_snapshots_slots(client: AsyncClient):
    panel_id = await _create_expert_panel(client, name="Scope panel A")
    created = await client.post(
        "/panel/sessions",
        json={
            "panel_id": panel_id,
            "config": {
                "protocol": "generic_panel",
                "topic": "Kör samma panel med generic_panel",
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["panel_id"] == panel_id
    assert body["project_id"] is None
    assert body["campaign_id"] is None
    slots = body["config"]["expert_slots"]
    assert len(slots) >= 2
    assert all(slot["label"] for slot in slots)

    again = await client.get(f"/panel/sessions/{body['id']}")
    assert again.status_code == 200
    assert again.json()["config"]["expert_slots"] == slots


@pytest.mark.asyncio
async def test_create_session_with_project_id(client: AsyncClient):
    os_id = await _kund_id(client, OS_DEFAULT_KUND_SLUG)
    projects = await client.get(f"/kunder/{os_id}/projekt")
    assert projects.status_code == 200
    project_id = projects.json()[0]["id"]

    created = await client.post(
        "/panel/sessions",
        json={
            "project_id": project_id,
            "config": {
                "protocol": "generic_panel",
                "topic": "Projekt-skopad session",
                "expert_slots": [
                    {"slot_id": "a", "label": "Expert A", "profile": "A"},
                ],
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["project_id"] == project_id
    assert body["panel_id"] is None
    assert body["campaign_id"] is None


@pytest.mark.asyncio
async def test_create_session_rejects_unknown_panel_and_project(client: AsyncClient):
    missing_panel = await client.post(
        "/panel/sessions",
        json={
            "panel_id": 999999,
            "config": {"protocol": "generic_panel", "topic": "Saknad panel"},
        },
    )
    assert missing_panel.status_code == 404

    missing_project = await client.post(
        "/panel/sessions",
        json={
            "project_id": 999999,
            "config": {
                "protocol": "generic_panel",
                "topic": "Saknat projekt",
                "expert_slots": [{"slot_id": "a", "label": "A"}],
            },
        },
    )
    assert missing_project.status_code == 404


@pytest.mark.asyncio
async def test_create_session_rejects_persona_population_as_panel(client: AsyncClient):
    personas = await client.get("/personas")
    assert personas.status_code == 200
    persona_id = personas.json()[0]["id"]
    pop = await client.post(
        "/populations",
        json={
            "name": "Not an expert panel",
            "include_persona_ids": [persona_id],
            "recipe": {"size": 1, "dist": {}},
        },
    )
    assert pop.status_code == 201, pop.text
    bad = await client.post(
        "/panel/sessions",
        json={
            "panel_id": pop.json()["id"],
            "config": {"protocol": "generic_panel", "topic": "Fel kind"},
        },
    )
    assert bad.status_code == 400
    assert "expert panel" in bad.json()["detail"].lower()


@pytest.mark.asyncio
async def test_dd_session_sets_panel_id_from_campaign(client: AsyncClient):
    panel_id = await _create_expert_panel(client, name="DD campaign panel")
    campaign = await client.post("/dd/campaigns", json={"title": "Panel id campaign"})
    assert campaign.status_code == 201
    campaign_id = campaign.json()["id"]
    patched = await client.patch(
        f"/dd/campaigns/{campaign_id}",
        json={"expert_panel_id": panel_id},
    )
    assert patched.status_code == 200
    sourced = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    assert sourced.status_code == 200
    candidate_id = sourced.json()["candidates"][0]["id"]

    session_resp = await client.post(
        f"/dd/campaigns/{campaign_id}/panel-sessions",
        json={"campaign_id": campaign_id, "candidate_id": candidate_id},
    )
    assert session_resp.status_code == 201, session_resp.text
    body = session_resp.json()
    assert body["panel_id"] == panel_id
    assert body["campaign_id"] == campaign_id
    assert body["project_id"] is None
    assert body["config"]["expert_slots"]


def test_create_requires_slots_or_panel_id():
    with pytest.raises(ValidationError):
        PanelSessionCreate(
            config=PanelSessionConfig(topic="Ingen panel, inga slottar"),
        )
