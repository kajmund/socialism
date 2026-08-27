"""Step 5 — optional query-param scoping on list endpoints (declarative, not auth)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database.models import Message, Persona, Projekt, Run
from app.serializers import utcnow
from app.services.kund_store import BOLAG_DEMO_KUND_SLUG, OS_DEFAULT_KUND_SLUG, default_os_customer_id


async def _tenant_ids(client: AsyncClient) -> tuple[int, int]:
    listed = await client.get("/kunder")
    assert listed.status_code == 200
    rows = listed.json()
    os_id = next(row["id"] for row in rows if row["slug"] == OS_DEFAULT_KUND_SLUG)
    bolag_id = next(row["id"] for row in rows if row["slug"] == BOLAG_DEMO_KUND_SLUG)
    return os_id, bolag_id


@pytest.mark.asyncio
async def test_list_personas_filters_by_customer_id(client_db):
    client, factory = client_db
    devbrains_id, bolag_id = await _tenant_ids(client)

    os_persona = await client.post(
        "/personas",
        json={
            "name": "OS Scoped",
            "age": 40,
            "occ": "Test",
            "district": "Centrum",
            "profile": {"name": "OS Scoped", "ort": "Centrum", "yrke": "Test", "ålder": "40"},
        },
    )
    assert os_persona.status_code == 201

    async with factory() as session:
        session.add(
            Persona(
                id="p-bolag-scope",
                customer_id=bolag_id,
                name="Bolag Scoped",
                age=35,
                occ="DD",
                district="Stockholm",
                quote="",
                origin="manuell",
                profile={"name": "Bolag Scoped"},
            )
        )
        await session.commit()

    os_list = await client.get("/personas", params={"customer_id": devbrains_id})
    assert os_list.status_code == 200
    os_names = {row["name"] for row in os_list.json()}
    assert "OS Scoped" in os_names
    assert "Bolag Scoped" not in os_names

    bolag_list = await client.get("/personas", params={"customer_id": bolag_id})
    assert bolag_list.status_code == 200
    bolag_names = {row["name"] for row in bolag_list.json()}
    assert "Bolag Scoped" in bolag_names
    assert "OS Scoped" not in bolag_names


@pytest.mark.asyncio
async def test_list_dd_campaigns_filters_by_customer_id(client: AsyncClient):
    os_id, bolag_id = await _tenant_ids(client)

    created = await client.post(
        "/dd/campaigns",
        json={"title": "Bolag filter test", "criteria": {"alder_min": 0, "alder_max": 50, "omrade": ""}},
    )
    assert created.status_code == 201
    campaign_id = created.json()["id"]

    bolag_rows = await client.get("/dd/campaigns", params={"module": "dd", "customer_id": bolag_id})
    assert bolag_rows.status_code == 200
    assert any(row["id"] == campaign_id for row in bolag_rows.json())

    os_rows = await client.get("/dd/campaigns", params={"module": "dd", "customer_id": os_id})
    assert os_rows.status_code == 200
    assert not any(row["id"] == campaign_id for row in os_rows.json())


@pytest.mark.asyncio
async def test_list_runs_and_messages_filter_by_project_id(client_db):
    client, factory = client_db
    project_id = 1

    pop = await client.post(
        "/populations",
        json={"name": "ScopeFilterPop", "recipe": {"size": 0, "slots": []}},
    )
    assert pop.status_code == 201
    pop_id = pop.json()["id"]

    run = await client.post(
        "/runs",
        json={"name": "Scoped Run", "population_id": pop_id, "status": "draft"},
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    msg = await client.post(
        "/messages",
        json={"type": "post", "title": "Scoped Msg", "body": "Hej"},
    )
    assert msg.status_code == 201
    msg_id = msg.json()["id"]

    async with factory() as session:
        os_customer = await default_os_customer_id(session)
        other = Projekt(
            customer_id=os_customer,
            name="Other project",
            slug="other-scope-test-034",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(other)
        await session.flush()
        other_project_id = int(other.id)
        session.add(
            Run(
                name="Other project run",
                project_id=other_project_id,
                status="draft",
                population_id=pop_id,
                seed="",
                updated_at=utcnow(),
            )
        )
        session.add(
            Message(
                id="msg-other-proj",
                project_id=other_project_id,
                type="post",
                title="Other project msg",
                body="Hej",
                metadata_={},
                created_at=utcnow(),
            )
        )
        await session.commit()

    runs = await client.get("/runs", params={"project_id": project_id})
    assert runs.status_code == 200
    run_ids = {row["id"] for row in runs.json()}
    assert run_id in run_ids
    assert all(row["name"] != "Other project run" for row in runs.json())

    messages = await client.get("/messages", params={"project_id": project_id})
    assert messages.status_code == 200
    msg_ids = {row["id"] for row in messages.json()}
    assert msg_id in msg_ids
    assert "msg-other-proj" not in msg_ids


@pytest.mark.asyncio
async def test_unfiltered_persona_list_includes_all_customers(client_db):
    """Omitting customer_id keeps global list behaviour (declarative filter only when set)."""
    client, factory = client_db
    _, bolag_id = await _tenant_ids(client)

    async with factory() as session:
        session.add(
            Persona(
                id="p-bolag-unfiltered",
                customer_id=bolag_id,
                name="Bolag Unfiltered",
                age=30,
                occ="DD",
                district="X",
                quote="",
                origin="manuell",
                profile={},
            )
        )
        await session.commit()

    all_rows = await client.get("/personas")
    assert all_rows.status_code == 200
    names = {row["name"] for row in all_rows.json()}
    assert "Bolag Unfiltered" in names

    os_id, _ = await _tenant_ids(client)
    os_only = await client.get("/personas", params={"customer_id": os_id})
    os_names = {row["name"] for row in os_only.json()}
    assert "Bolag Unfiltered" not in os_names
