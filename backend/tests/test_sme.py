"""SME product shell API coverage."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.database.models import Persona, PersonaMessage, Population, PopulationMember
from app.serializers import utcnow
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
async def test_sme_expert_inbox_and_read_cursor(client_db) -> None:
    client, factory = client_db
    await _enable_sme(client)

    me = await client.get("/me")
    assert me.status_code == 200
    assert me.json()["product"] == "sme"

    inbox = await client.get("/sme/inbox", params={"filter": "all"})
    assert inbox.status_code == 200
    expert = inbox.json()[0]
    assert expert["thread_type"] == "expert"

    async with factory() as session:
        session.add(
            PersonaMessage(
                persona_id=expert["thread_id"],
                mode="interview",
                role="assistant",
                content="Ett nytt expertsvar",
                created_at=utcnow(),
            )
        )
        await session.commit()

    unread = await client.get("/sme/inbox", params={"filter": "unread"})
    assert unread.status_code == 200
    assert unread.json()[0]["unread_count"] == 1

    marked = await client.post(f"/sme/threads/expert/{expert['thread_id']}/read")
    assert marked.status_code == 200
    unread = await client.get("/sme/inbox", params={"filter": "unread"})
    assert unread.json() == []


@pytest.mark.asyncio
async def test_sme_panel_chat_returns_each_expert_response(client_db) -> None:
    client, factory = client_db
    await _enable_sme(client)

    async with factory() as session:
        expert = (
            (
                await session.execute(
                    select(Persona).where(
                        Persona.customer_id == TEST_CUSTOMER_ID,
                        Persona.kind == "expert",
                    )
                )
            )
            .scalars()
            .first()
        )
        assert expert is not None
        panel = Population(
            customer_id=TEST_CUSTOMER_ID,
            kind="expert_panel",
            name="SME-panel",
            size=1,
            versions=1,
            fingerprint=[],
            recipe={},
            updated_at=utcnow(),
        )
        session.add(panel)
        await session.flush()
        session.add(
            PopulationMember(
                population_id=panel.id,
                persona_id=expert.id,
                kind="expert",
                name=expert.name,
                initials="EX",
                age=expert.age or 40,
                occ=expert.occ,
                district=expert.district,
                trait="",
            )
        )
        await session.commit()
        panel_id = panel.id

    groups = await client.get("/sme/inbox", params={"filter": "groups"})
    assert groups.status_code == 200
    assert groups.json()[0]["thread_id"] == str(panel_id)

    sent = await client.post(
        f"/sme/panels/{panel_id}/messages",
        json={"message": "Vad bör företaget prioritera?"},
    )
    assert sent.status_code == 200
    messages = sent.json()
    assert [row["role"] for row in messages] == ["user", "assistant"]
    assert messages[1]["persona_name"] == expert.name

    thread = await client.get(f"/sme/panels/{panel_id}/messages")
    assert thread.status_code == 200
    assert len(thread.json()) == 2
