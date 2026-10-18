"""Unit coverage for the SME quick-draft service.

The draft must bind the fast model profile, never persist messages, and never
hold a database connection while the model call is pending.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from sqlalchemy import delete, func, select, text

from app.database.models import Persona, PersonaMessage, PromptField
from app.llm import set_text_streamer
from app.llm.runtime_override import current_resolution
from app.services.expert_reasoning import current_expert_profile
from app.services.kund_store import bolag_demo_customer_id, ensure_default_kunder
from app.services.prompt_store import ensure_default_configurations
from app.services.sme_quick_draft import (
    QUICK_DRAFT_PROMPT_KEY,
    QUICK_PROGRESS_PROMPT_KEY,
    stream_quick_draft,
    stream_quick_message,
)
from tests.test_research_connection_release import single_connection as single_connection


async def _collect(stream: AsyncIterator[str]) -> list[str]:
    return [chunk async for chunk in stream]


async def test_stream_quick_draft_releases_connection_and_binds_fast_profile(
    single_connection,
):
    engine, factory = single_connection
    async with factory() as session:
        await ensure_default_configurations(session)
        await ensure_default_kunder(session)
        customer_id = await bolag_demo_customer_id(session)
        session.add(
            Persona(
                id="qd-expert",
                kind="expert",
                customer_id=customer_id,
                name="Utkastjuristen",
                occ="Jurist",
                district="—",
                quote="Kort och konkret.",
                tools=[],
            )
        )
        await session.commit()

    entered = asyncio.Event()
    release = asyncio.Event()
    seen: dict[str, object] = {}

    async def fake_stream(_messages) -> AsyncIterator[str]:
        resolution = current_resolution()
        seen["profile"] = current_expert_profile()
        seen["prompt_key"] = None if resolution is None else resolution.prompt_key
        assert engine.pool.checkedout() == 0, (
            "draft holds a database connection during the model call"
        )
        entered.set()
        await release.wait()
        yield "Utkast"
        yield " svar."

    set_text_streamer(fake_stream)
    stream = stream_quick_draft(
        factory,
        persona_id="qd-expert",
        message="Hur skriver jag uppsägningstiden?",
    )
    try:
        consumer = asyncio.create_task(_collect(stream))
        await asyncio.wait_for(entered.wait(), timeout=5)
        # Another client must reach the pool while the model call is pending.
        async with factory() as other:
            assert await other.scalar(text("SELECT 1")) == 1
        release.set()
        chunks = await asyncio.wait_for(consumer, timeout=5)
    finally:
        await stream.aclose()

    assert chunks == ["Utkast", " svar."]
    assert seen["profile"] == "fast"
    assert seen["prompt_key"] == QUICK_DRAFT_PROMPT_KEY
    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(PersonaMessage))
        assert count == 0
    assert engine.pool.checkedout() == 0


async def test_stream_quick_draft_missing_prompt_stays_silent(single_connection):
    engine, factory = single_connection
    async with factory() as session:
        await ensure_default_configurations(session)
        await ensure_default_kunder(session)
        customer_id = await bolag_demo_customer_id(session)
        await session.execute(
            delete(PromptField).where(PromptField.key == QUICK_DRAFT_PROMPT_KEY)
        )
        session.add(
            Persona(
                id="qd-no-prompt",
                kind="expert",
                customer_id=customer_id,
                name="Utkastjuristen",
                occ="Jurist",
                district="—",
                quote="Kort och konkret.",
                tools=[],
            )
        )
        await session.commit()

    called = False

    async def fake_stream(_messages) -> AsyncIterator[str]:
        nonlocal called
        called = True
        if False:
            yield

    set_text_streamer(fake_stream)
    chunks = await _collect(
        stream_quick_draft(factory, persona_id="qd-no-prompt", message="Fråga")
    )
    assert chunks == []
    assert not called
    assert engine.pool.checkedout() == 0


async def test_stream_quick_progress_binds_fast_profile_and_said_line(single_connection):
    engine, factory = single_connection
    async with factory() as session:
        await ensure_default_configurations(session)
        await ensure_default_kunder(session)
        customer_id = await bolag_demo_customer_id(session)
        session.add(
            Persona(
                id="qd-progress",
                kind="expert",
                customer_id=customer_id,
                name="Utkastjuristen",
                occ="Jurist",
                district="—",
                quote="Kort och konkret.",
                tools=[],
            )
        )
        await session.commit()

    seen: dict[str, object] = {}

    async def fake_stream(messages) -> AsyncIterator[str]:
        resolution = current_resolution()
        seen["profile"] = current_expert_profile()
        seen["prompt_key"] = None if resolution is None else resolution.prompt_key
        seen["last"] = messages[-1]
        seen["before_last"] = messages[-2]
        yield "…arbetar fortfarande."

    set_text_streamer(fake_stream)
    chunks = await _collect(
        stream_quick_message(
            factory,
            persona_id="qd-progress",
            message="Kommentera avtalet",
            prompt_key=QUICK_PROGRESS_PROMPT_KEY,
            said="Ok, jag kollar.",
        )
    )
    assert chunks == ["…arbetar fortfarande."]
    assert seen["profile"] == "fast"
    assert seen["prompt_key"] == QUICK_PROGRESS_PROMPT_KEY
    # The progress line continues the line the expert already said.
    assert seen["before_last"] == {"role": "user", "content": "Kommentera avtalet"}
    assert seen["last"] == {"role": "assistant", "content": "Ok, jag kollar."}
    assert engine.pool.checkedout() == 0
