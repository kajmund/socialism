"""SME expert-thread clearing: character chat only, never interviews."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.database.models import PersonaMessage
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
async def test_clear_expert_messages_leaves_interviews_and_other_experts(client_db) -> None:
    client, factory = client_db
    await _enable_sme(client)
    inbox = await client.get("/sme/inbox", params={"filter": "all"})
    expert_ids = [
        row["thread_id"] for row in inbox.json() if row["thread_type"] == "expert"
    ]
    assert len(expert_ids) >= 2
    cleared_id, other_id = expert_ids[:2]
    async with factory() as session:
        session.add_all([
            PersonaMessage(
                persona_id=cleared_id, mode="character", role="user",
                content="Första frågan", created_at=utcnow(),
            ),
            PersonaMessage(
                persona_id=cleared_id, mode="character", role="assistant",
                content="Första svaret", created_at=utcnow(),
            ),
            PersonaMessage(
                persona_id=cleared_id, mode="interview", role="user",
                content="Intervjufråga", created_at=utcnow(),
            ),
            PersonaMessage(
                persona_id=other_id, mode="character", role="user",
                content="Annan expert", created_at=utcnow(),
            ),
        ])
        await session.commit()

    cleared = await client.delete(f"/sme/experts/{cleared_id}/messages")
    assert cleared.status_code == 204
    async with factory() as session:
        remaining = (
            await session.execute(
                select(PersonaMessage.persona_id, PersonaMessage.content)
            )
        ).all()
    assert [(row.persona_id, row.content) for row in remaining] == [
        (cleared_id, "Intervjufråga"),
        (other_id, "Annan expert"),
    ]
