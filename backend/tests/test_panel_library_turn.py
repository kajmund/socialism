"""Panel turns stay in the panel chat and still update the expert's memory."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Persona, PersonaMessage
from app.llm import set_text_streamer
from app.schemas.domain import PersonaChatResponse
from app.services.persona_chat import stream_library_chat_turn
from app.services.prompt_store import ensure_default_configurations


@pytest.fixture
async def sessions():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        await ensure_default_configurations(session)
        session.add(
            Persona(
                id="exp-panel",
                customer_id=1,
                kind="expert",
                name="Klas",
                age=45,
                occ="Analytiker",
                district="Stockholm",
                profile={"name": "Klas"},
                tools=[],
            )
        )
        await session.commit()
    yield factory
    await engine.dispose()


async def _reply(factory, monkeypatch, *, panel: bool) -> str:
    seen: dict[str, str] = {}

    def capture(_persona, **kwargs):
        seen["source"] = kwargs["source"]

    monkeypatch.setattr("app.services.persona_chat.schedule_expert_memory_update", capture)

    async def stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        yield "Svar i panelen."

    set_text_streamer(stream)
    try:
        async with factory() as session:
            items: list[object] = []
            async for item in stream_library_chat_turn(
                session,
                persona_id="exp-panel",
                mode="character",
                message="Titta igen.",
                group_history=[] if panel else None,
            ):
                items.append(item)
        done = next(item for item in items if isinstance(item, PersonaChatResponse))
        assert seen["source"] == ("panel_chat" if panel else "persona_chat")
        return done.reply
    finally:
        set_text_streamer(None)


@pytest.mark.asyncio
async def test_a_panel_turn_updates_memory_without_a_private_message(sessions, monkeypatch):
    reply = await _reply(sessions, monkeypatch, panel=True)
    assert reply == "Svar i panelen."
    async with sessions() as session:
        rows = list(await session.scalars(select(PersonaMessage)))
    assert rows == []


@pytest.mark.asyncio
async def test_a_private_turn_still_lands_in_the_expert_chat(sessions, monkeypatch):
    await _reply(sessions, monkeypatch, panel=False)
    async with sessions() as session:
        rows = list(await session.scalars(select(PersonaMessage)))
    assert [row.role for row in rows] == ["user", "assistant"]
