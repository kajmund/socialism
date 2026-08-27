"""Tests for DD sourcing and campaigns."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.dd.allabolag_mock import search_companies
from app.services.dd.schemas import DdSourcingCriteria


@pytest.mark.asyncio
async def test_sourcing_deterministic():
    criteria = DdSourcingCriteria(alder_min=5, alder_max=30, omrade="Stockholm", resultat="vinst")
    a = search_companies(criteria)
    b = search_companies(criteria)
    assert len(a) >= 5
    assert len(a) <= 10
    assert [c.id for c in a] == [c.id for c in b]


@pytest.mark.asyncio
async def test_dd_campaign_crud_and_sourcing_run(client: AsyncClient):
    create = await client.post(
        "/dd/campaigns",
        json={"title": "Test DD", "criteria": {"alder_min": 0, "alder_max": 50, "omrade": ""}},
    )
    assert create.status_code == 201
    campaign_id = create.json()["id"]

    run = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "sourcing"
    assert len(body["candidates"]) >= 5

    listed = await client.get("/dd/campaigns?module=dd")
    assert listed.status_code == 200
    assert any(row["id"] == campaign_id for row in listed.json())
