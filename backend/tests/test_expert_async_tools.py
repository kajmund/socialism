"""Expert chat says it is looking something up, then delivers the tool result later."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Persona, PersonaMessage
from app.llm import set_text_completer, set_tools_completer
from app.schemas.domain import PersonaChatResponse
from app.services.expert_async_tools import (
    PlannedCall,
    _threads,
    begin_library_tools,
    reset_library_tool_threads,
    wait_library_tool_tasks,
)
from app.services.jobs import set_job_session_factory
from app.services.persona_chat import stream_library_chat_turn
from app.services.prompt_store import ensure_default_configurations


def _tool_call(name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


@pytest.mark.asyncio
async def test_ack_returns_before_tool_and_idle_expert_writes_the_result(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'tools.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=1,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    release = asyncio.Event()
    probed = asyncio.Event()
    composed: list[str] = []

    async def company_tool(_name, _arguments):
        await release.wait()
        async with factory() as probe:
            assert await probe.scalar(select(Persona.id)) == "e-lookup"
        probed.set()
        return "Omsättning 12"

    async def tools(_messages, _specs=None):
        return SimpleNamespace(
            content="Jag kollar upp det.",
            tool_calls=[_tool_call("lookup_company", '{"orgnr":"5567037485"}')],
        )

    async def weave(messages, *, model=None):
        composed.append(str(messages[-1]["content"]))
        return "Omsättningen är 12."

    monkeypatch.setattr("app.services.expert_async_tools.run_company_tool", company_tool)
    monkeypatch.setattr(
        "app.services.persona_chat.schedule_expert_memory_update",
        lambda *args, **kwargs: None,
    )
    set_job_session_factory(factory)
    set_tools_completer(tools)
    set_text_completer(weave)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            await ensure_default_configurations(session)
            session.add(
                Persona(
                    id="e-lookup",
                    customer_id=1,
                    kind="expert",
                    name="Finansexpert",
                    age=50,
                    occ="Analytiker",
                    district="Stockholm",
                    profile={"name": "Finansexpert"},
                    tools=["lookup_company"],
                )
            )
            await session.commit()
            reply = ""
            async for item in stream_library_chat_turn(
                session,
                persona_id="e-lookup",
                mode="interview",
                message="Vad omsätter bolaget?",
            ):
                if isinstance(item, str):
                    reply += item
                elif isinstance(item, PersonaChatResponse):
                    reply = item.reply
                    release.set()
                    await wait_library_tool_tasks()
        assert reply == "Jag kollar upp det."
        assert probed.is_set()
        assert any("Omsättning 12" in text for text in composed)
        async with factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(PersonaMessage)
                        .where(PersonaMessage.persona_id == "e-lookup")
                        .order_by(PersonaMessage.id.asc())
                    )
                ).all()
            )
        assert [row.content for row in rows] == [
            "Vad omsätter bolaget?",
            "Jag kollar upp det.",
            "Omsättningen är 12.",
        ]
    finally:
        set_tools_completer(None)
        set_text_completer(None)
        set_job_session_factory(None)
        reset_library_tool_threads()
        await engine.dispose()


@pytest.mark.asyncio
async def test_next_turn_weaves_the_result_instead_of_a_separate_wake(monkeypatch):
    release = asyncio.Event()

    async def company_tool(_name, _arguments):
        await release.wait()
        return "Omsättning 12"

    monkeypatch.setattr("app.services.expert_async_tools.run_company_tool", company_tool)
    scope = begin_library_tools(
        persona_id="e-next",
        mode="interview",
        actor_user_id=None,
        history=[],
        user_message="Vad omsätter bolaget?",
        enabled=True,
    )
    try:
        await scope.enter()
        scope.defer((PlannedCall("call_1", "lookup_company", {"orgnr": "5567037485"}),))
        await scope.finish(deliver=True)
        thread = _threads[("e-next", "interview")]
        assert thread.inflight == 1
        nxt = begin_library_tools(
            persona_id="e-next",
            mode="interview",
            actor_user_id=None,
            history=[],
            user_message="Och vinsten?",
            enabled=True,
        )
        async def take_result() -> None:
            await nxt.enter()
            assert "Omsättning 12" in nxt.pending_result
            await nxt.finish(deliver=False)

        waiting = asyncio.create_task(take_result())
        for _ in range(20):
            if thread.busy >= 1 and not waiting.done():
                break
            await asyncio.sleep(0)
        assert thread.busy >= 1
        release.set()
        await waiting
        await wait_library_tool_tasks()
    finally:
        reset_library_tool_threads()
