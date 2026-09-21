"""Tests for expert personas (FAS B)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.auth.scope import customer_id_for_expert_create
from app.database.models import UserAccount
from app.services.kund_store import BOLAG_DEMO_KUND_SLUG, OS_DEFAULT_KUND_SLUG
from tests.conftest import ADMIN_USER_ID


def _account(*, role: str, kund_id: int | None) -> UserAccount:
    return UserAccount(id="scope-user", email="scope@test.local", role=role, kund_id=kund_id)


def test_customer_id_for_expert_create_bound_admin_ignores_requested():
    assert customer_id_for_expert_create(_account(role="admin", kund_id=7), 2, 2) == 7


def test_customer_id_for_expert_create_unbound_admin_uses_requested_or_default():
    unbound = _account(role="admin", kund_id=None)
    assert customer_id_for_expert_create(unbound, 9, 2) == 9
    assert customer_id_for_expert_create(unbound, None, 2) == 2


def test_customer_id_for_expert_create_user_stays_on_kund():
    assert customer_id_for_expert_create(_account(role="user", kund_id=1), 2, 2) == 1


def test_customer_id_for_expert_create_user_without_kund_denied():
    with pytest.raises(HTTPException) as exc:
        customer_id_for_expert_create(_account(role="user", kund_id=None), 2, 2)
    assert exc.value.status_code == 403
    assert exc.value.detail == "kund_access_denied"


async def _kund_ids(client: AsyncClient) -> tuple[int, int]:
    listed = await client.get("/kunder")
    rows = {row["slug"]: row["id"] for row in listed.json()}
    return rows[OS_DEFAULT_KUND_SLUG], rows[BOLAG_DEMO_KUND_SLUG]


async def _expert_on_customer(client: AsyncClient, expert_id: str, customer_id: int) -> bool:
    listed = await client.get("/personas", params={"kind": "expert", "customer_id": customer_id})
    return any(row["id"] == expert_id for row in listed.json())


@pytest.mark.asyncio
async def test_create_expert_rejects_existing_id(client: AsyncClient):
    first = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "id": "expert-fixed-id",
            "name": "Skattejurist",
            "occ": "M&A-rådgivare",
            "district": "—",
            "quote": "Granskar avtal och struktur.",
        },
    )
    assert first.status_code == 201, first.text

    duplicate = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "id": "expert-fixed-id",
            "name": "Skattejurist",
            "occ": "M&A-rådgivare",
            "district": "—",
            "quote": "Granskar avtal och struktur.",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Persona id already exists"


@pytest.mark.asyncio
async def test_create_expert_assigns_sampled_name_and_age(client: AsyncClient):
    create = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "name": "Skattejurist",
            "occ": "M&A-rådgivare",
            "district": "—",
            "quote": "Granskar avtal och struktur.",
            "profile": {
                "name": "Skattejurist",
                "initials": "SJ",
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
    assert body["name"] != "Skattejurist"
    assert " " in body["name"]
    assert isinstance(body["age"], int)
    assert 30 <= body["age"] <= 60
    assert body["profile"]["age"] == str(body["age"])
    assert body["tools"] == [
        "search_companies",
        "lookup_company",
        "validate_orgnr",
        "search_duckduckgo",
        "search_wiki",
        "start_research",
        "ask_expert",
        "get_actor_context",
        "propose_actor_context_update",
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
async def test_create_and_update_persona_tools(client: AsyncClient):
    create = await client.post(
        "/personas",
        json={
            "kind": "persona",
            "name": "Sökpersona",
            "age": 42,
            "occ": "Lärare",
            "district": "Malmö",
            "tools": ["search_wiki", "search_duckduckgo", "search_wiki"],
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["kind"] == "persona"
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
async def test_persona_without_tools_defaults_to_empty(client: AsyncClient):
    create = await client.post(
        "/personas",
        json={
            "kind": "persona",
            "name": "Utan verktyg",
            "age": 30,
            "occ": "Testare",
            "district": "Göteborg",
        },
    )
    assert create.status_code == 201, create.text
    assert create.json()["tools"] == []


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


@pytest.mark.asyncio
async def test_create_expert_unbound_admin_defaults_to_bolag_demo(client: AsyncClient):
    os_id, bolag_id = await _kund_ids(client)
    create = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "name": "Unbound Admin Expert",
            "occ": "Jurist",
            "district": "—",
            "quote": "Test.",
        },
    )
    assert create.status_code == 201, create.text
    expert_id = create.json()["id"]
    assert await _expert_on_customer(client, expert_id, bolag_id)
    assert not await _expert_on_customer(client, expert_id, os_id)


@pytest.mark.asyncio
async def test_create_expert_bound_admin_uses_kund_not_body_customer_id(client_db):
    client, factory = client_db
    os_id, bolag_id = await _kund_ids(client)
    async with factory() as db:
        admin = await db.get(UserAccount, ADMIN_USER_ID)
        assert admin is not None
        admin.kund_id = os_id
        await db.commit()

    create = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "customer_id": bolag_id,
            "name": "Bound Admin Expert",
            "occ": "Jurist",
            "district": "—",
            "quote": "Test.",
        },
    )
    assert create.status_code == 201, create.text
    expert_id = create.json()["id"]
    assert await _expert_on_customer(client, expert_id, os_id)
    assert not await _expert_on_customer(client, expert_id, bolag_id)


@pytest.mark.asyncio
async def test_create_expert_user_stays_on_own_kund(user_client: AsyncClient):
    create = await user_client.post(
        "/personas",
        json={
            "kind": "expert",
            "customer_id": 2,
            "name": "User Kund Expert",
            "occ": "Jurist",
            "district": "—",
            "quote": "Test.",
        },
    )
    assert create.status_code == 201, create.text
    expert_id = create.json()["id"]
    listed = await user_client.get("/personas", params={"kind": "expert"})
    assert listed.status_code == 200
    assert any(row["id"] == expert_id for row in listed.json())
