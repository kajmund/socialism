"""Tests for expert personas (FAS B)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.kund_store import BOLAG_DEMO_KUND_SLUG


@pytest.mark.asyncio
async def test_create_expert_without_age(client: AsyncClient):
    create = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "name": "Test Expert",
            "occ": "M&A-rådgivare",
            "district": "—",
            "quote": "Granskar avtal och struktur.",
            "profile": {
                "name": "Test Expert",
                "initials": "TE",
                "kompetensomrade": "Legal risk",
                "radgivningsstil": "Försiktig",
                "yrkesbakgrund": "M&A-rådgivare",
                "professionell_anekdot": "Har granskat tio LOI:er.",
                "beskrivning": "Granskar avtal och struktur.",
            },
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["kind"] == "expert"
    assert body["age"] is None
    assert body["tools"] == [
        "search_companies",
        "lookup_company",
        "validate_orgnr",
        "search_duckduckgo",
        "search_wiki",
    ]


@pytest.mark.asyncio
async def test_list_experts_filters_by_kind(client: AsyncClient):
    listed = await client.get("/kunder")
    bolag_id = next(row["id"] for row in listed.json() if row["slug"] == BOLAG_DEMO_KUND_SLUG)

    experts = await client.get("/personas", params={"kind": "expert", "customer_id": bolag_id})
    assert experts.status_code == 200
    rows = experts.json()
    assert len(rows) >= 4
    assert all(row["kind"] == "expert" for row in rows)


@pytest.mark.asyncio
async def test_persona_kind_still_requires_age(client: AsyncClient):
    missing_age = await client.post(
        "/personas",
        json={
            "kind": "persona",
            "name": "No Age",
            "occ": "Testare",
            "district": "Stockholm",
        },
    )
    assert missing_age.status_code == 422


@pytest.mark.asyncio
async def test_create_and_update_expert_tools(client: AsyncClient):
    create = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "name": "Sökexpert",
            "occ": "Analytiker",
            "district": "—",
            "quote": "Söker fakta.",
            "tools": ["search_wiki", "search_duckduckgo", "search_wiki"],
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["tools"] == ["search_wiki", "search_duckduckgo"]

    updated = await client.put(
        f"/personas/{body['id']}",
        json={"tools": ["lookup_company"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["tools"] == ["lookup_company"]

    cleared = await client.put(
        f"/personas/{body['id']}",
        json={"tools": []},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["tools"] == []


@pytest.mark.asyncio
async def test_reject_unknown_expert_tool(client: AsyncClient):
    create = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "name": "Felverktyg",
            "occ": "Analytiker",
            "district": "—",
            "tools": ["search_wiki", "not_a_tool"],
        },
    )
    assert create.status_code == 422
