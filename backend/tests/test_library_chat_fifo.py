from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import PersonaMessage
from app.serializers import utcnow
from app.services.library_chat_fifo import trim_and_commit_library_chat
from tests.test_gemini_live import _create_expert


@pytest.mark.asyncio
async def test_library_chat_drops_the_oldest_message_past_forty(client_db):
    client: AsyncClient
    factory: async_sessionmaker[AsyncSession]
    client, factory = client_db
    expert = await _create_expert(client)
    persona_id = str(expert["id"])
    created_at = datetime(2026, 10, 2, tzinfo=UTC)

    async with factory() as session:
        session.add(
            PersonaMessage(
                persona_id=persona_id,
                mode="interview",
                role="user",
                content="run-rad",
                created_at=created_at,
                run_id=1,
            )
        )
        for index in range(41):
            session.add(
                PersonaMessage(
                    persona_id=persona_id,
                    mode="interview",
                    role="user" if index % 2 == 0 else "assistant",
                    content=f"rad-{index}",
                    created_at=created_at,
                )
            )
        await session.commit()

    listed = await client.get(f"/personas/{persona_id}/messages")
    assert listed.status_code == 200, listed.text
    assert [row["content"] for row in listed.json()] == [f"rad-{index}" for index in range(1, 41)]

    async with factory() as session:
        session.add(
            PersonaMessage(
                persona_id=persona_id,
                mode="interview",
                role="user",
                content="rad-41",
                created_at=utcnow(),
            )
        )
        await trim_and_commit_library_chat(session, persona_id, "interview")
        run_row = await session.scalar(
            select(PersonaMessage).where(PersonaMessage.content == "run-rad")
        )
        assert run_row is not None

    again = await client.get(f"/personas/{persona_id}/messages")
    assert [row["content"] for row in again.json()] == [f"rad-{index}" for index in range(2, 42)]
