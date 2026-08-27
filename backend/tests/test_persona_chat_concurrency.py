"""Concurrency and persistence tests for persona chat turns."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Persona, PersonaMessage
from app.llm import set_structured_completer, set_text_streamer
from app.schemas.domain import FollowUpQuestions
from app.services.persona_chat import stream_library_chat_turn
from app.services.prompt_store import ensure_default_configurations


@pytest.fixture
async def chat_sessions():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as seed_session:
        await ensure_default_configurations(seed_session)
        seed_session.add(
            Persona(
                id="p-concurrent",
                customer_id=1,
                name="Test Persona",
                age=40,
                occ="Vård",
                district="Centrum",
                profile={"name": "Test Persona", "ort": "Centrum", "yrke": "Vård", "ålder": "40"},
            )
        )
        await seed_session.commit()
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_library_chat_turns_are_serialized(chat_sessions):
    """Two simultaneous turns must not both read the same pre-turn history."""
    gate = asyncio.Event()
    release = asyncio.Event()
    call = 0

    async def _slow_stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        nonlocal call
        call += 1
        current = call
        gate.set()
        if current == 1:
            await release.wait()
        yield f"reply-{current}"

    async def _mock_structured(_messages: list[dict[str, str]], response_model: type):
        if response_model is FollowUpQuestions:
            return FollowUpQuestions(questions=["A?", "B?", "C?"])
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_text_streamer(_slow_stream)
    set_structured_completer(_mock_structured)
    try:

        async def _turn(message: str) -> None:
            async with chat_sessions() as session:
                async for item in stream_library_chat_turn(
                    session,
                    persona_id="p-concurrent",
                    mode="interview",
                    message=message,
                ):
                    if isinstance(item, str):
                        continue

        first = asyncio.create_task(_turn("first"))
        await gate.wait()
        second = asyncio.create_task(_turn("second"))
        await asyncio.sleep(0.05)
        release.set()
        await asyncio.gather(first, second)

        async with chat_sessions() as session:
            rows = await session.execute(
                select(PersonaMessage)
                .where(PersonaMessage.persona_id == "p-concurrent")
                .order_by(PersonaMessage.id.asc())
            )
            messages = rows.scalars().all()
        assert len(messages) == 4
        assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]
        assert messages[1].content == "reply-1"
        assert messages[3].content == "reply-2"
    finally:
        set_text_streamer(None)
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_user_message_persisted_before_assistant_stream(chat_sessions):
    """User row survives if streaming stops before assistant commit."""

    async def _partial_stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        yield "partial"
        raise asyncio.CancelledError()

    set_text_streamer(_partial_stream)
    try:
        async with chat_sessions() as session:
            stream = stream_library_chat_turn(
                session,
                persona_id="p-concurrent",
                mode="interview",
                message="orphan user",
            )
            with pytest.raises(asyncio.CancelledError):
                async for _item in stream:
                    pass

            rows = await session.execute(
                select(PersonaMessage).where(PersonaMessage.persona_id == "p-concurrent")
            )
            messages = rows.scalars().all()
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "orphan user"
    finally:
        set_text_streamer(None)
