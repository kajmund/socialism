"""Expert chat says it is looking something up, then delivers the tool result later."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Persona, PersonaMessage
from app.llm import set_tools_completer
from app.realtime.library_chat_broadcast import library_chat_broadcast
from app.schemas.domain import PersonaChatResponse
from app.services.expert_async_tools import (
    PlannedCall,
    ToolWork,
    _threads,
    begin_library_tools,
    reset_library_tool_threads,
    wait_library_tool_tasks,
)
from app.services.expert_reasoning_episode import (
    ExpertEpisode,
    continue_expert_episode,
    history_message,
    wait_model_traces,
)
from app.services.expert_tool_followup import _compose_followup, _maybe_escalate
from app.services.persona_chat import _history_triples, serialize_persona_message
from app.services.jobs import set_job_session_factory
from app.services.persona_chat import stream_library_chat_turn
from app.services.prompt_store import ensure_default_configurations


def _trace_capture(traced: list[dict]):
    async def capture(event: dict) -> None:
        if event.get("type") == "model_trace":
            traced.append(event)

    return capture


def _assert_model_trace(traced: list[dict]) -> None:
    assert [event["kind"] for event in traced] == [
        "message", "tool_call", "tool_result", "message",
    ]
    assert traced[0]["text"] == "Jag kollar upp det."
    assert traced[1]["name"] == "lookup_company"
    assert "Omsättning 12" in traced[2]["text"]
    assert traced[3]["text"] == "Omsättningen är 12."
    assert all("reasoning_content" not in event for event in traced)


def _company_tool(factory, release: asyncio.Event, probed: asyncio.Event):
    async def company_tool(_name, _arguments):
        await release.wait()
        async with factory() as probe:
            assert await probe.scalar(select(Persona.id)) == "e-lookup"
        probed.set()
        return "Omsättning 12"

    return company_tool


def _scripted_tools(seen: list[list[dict]]):
    async def tools(messages, _specs=None):
        seen.append(messages)
        if any(message.get("role") == "tool" for message in messages):
            return SimpleNamespace(content="Omsättningen är 12.", tool_calls=None, reasoning_content="after")
        return SimpleNamespace(
            content="Jag kollar upp det.",
            tool_calls=[_tool_call("lookup_company", '{"orgnr":"5567037485"}')],
            reasoning_content="before",
        )

    return tools


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
    seen: list[list[dict]] = []
    traced: list[dict] = []
    capture = _trace_capture(traced)
    monkeypatch.setattr(
        "app.services.expert_async_tools.run_company_tool",
        _company_tool(factory, release, probed),
    )
    monkeypatch.setattr(
        "app.services.persona_chat.schedule_expert_memory_update",
        lambda *args, **kwargs: None,
    )
    set_job_session_factory(factory)
    set_tools_completer(_scripted_tools(seen))
    await library_chat_broadcast.subscribe_customer(1, capture)
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
                    await wait_model_traces()
        assert reply == "Jag kollar upp det."
        assert probed.is_set()
        continued = seen[-1]
        assert continued[-1]["role"] == "tool"
        assert "Omsättning 12" in continued[-1]["content"]
        assert continued[-2]["reasoning_content"] == "before"
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
        assert [row.reasoning_content for row in rows] == [None, "before", "after"]
        _assert_model_trace(traced)
    finally:
        await library_chat_broadcast.unsubscribe(capture)
        set_tools_completer(None)
        set_job_session_factory(None)
        reset_library_tool_threads()
        await engine.dispose()


@pytest.mark.asyncio
async def test_workspace_followup_opens_the_named_document(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'open.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=1,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    events: list[dict] = []

    async def capture(event: dict) -> None:
        events.append(event)

    calls = {"n": 0}

    async def tools(messages, specs=None):
        names = [spec["function"]["name"] for spec in (specs or [])]
        assert names == ["show_document"]
        calls["n"] += 1
        if calls["n"] == 1:
            assert messages[-1]["role"] == "tool"
            assert "avtal" in messages[-1]["content"]
            return SimpleNamespace(
                content="Avtalet är öppet.",
                tool_calls=[_tool_call("show_document", '{"source_id":"avtal"}')],
            )
        return SimpleNamespace(content="Avtalet är öppet.", tool_calls=None)

    set_job_session_factory(factory)
    set_tools_completer(tools)
    await library_chat_broadcast.subscribe_customer(1, capture)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            await ensure_default_configurations(session)
            session.add(
                Persona(
                    id="e-open",
                    customer_id=1,
                    kind="expert",
                    name="Avtalsexpert",
                    age=50,
                    occ="Jurist",
                    district="Stockholm",
                    profile={"name": "Avtalsexpert"},
                )
            )
            await session.commit()
        result = '{"items":[{"source_id":"avtal","filename":"Avtal.pdf"}]}'
        show_document = {"type": "function", "function": {"name": "show_document", "parameters": {}}}
        text, _reasoning = await _compose_followup(
            ToolWork(
                persona_id="e-open",
                mode="interview",
                actor_user_id=None,
                history=[],
                user_message="öppna avtalet med ateles som kund",
                calls=(PlannedCall("call_search", "search_knowledge", {}),),
                workspace_id="canvas",
                workspace_state={"documents": []},
                episode=ExpertEpisode(
                    messages=(
                        {"role": "user", "content": "öppna avtalet med ateles som kund"},
                        {
                            "role": "assistant",
                            "content": "",
                            "reasoning_content": "find the file",
                            "tool_calls": [{
                                "id": "call_search",
                                "type": "function",
                                "function": {"name": "search_knowledge", "arguments": "{}"},
                            }],
                        },
                    ),
                    specs=(show_document,),
                    prompt_key="chat.mode.interview",
                    reasoning_content="find the file",
                ),
            ),
            result,
            (result,),
        )
        assert text == "Avtalet är öppet."
        assert events == [{
            "type": "workspace_tool",
            "thread_type": "expert",
            "thread_id": "e-open",
            "mode": "interview",
            "name": "show_document",
            "arguments": {"source_id": "avtal"},
        }]
    finally:
        await library_chat_broadcast.unsubscribe(capture)
        set_tools_completer(None)
        set_job_session_factory(None)
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


def test_reasoning_is_replayed_for_the_model_and_hidden_from_the_client():
    row = PersonaMessage(
        id=1,
        persona_id="e",
        mode="interview",
        role="assistant",
        content="Hej",
        reasoning_content="plan",
    )
    role, content, image, reasoning = _history_triples([row])[0]
    assert history_message(role, content, image, reasoning)["reasoning_content"] == "plan"
    assert "reasoning_content" not in serialize_persona_message(row).model_dump()


@pytest.mark.asyncio
async def test_deep_episode_does_not_reassess(monkeypatch):
    async def assess(**_kwargs):
        raise AssertionError("Jev ran inside a deep episode")

    monkeypatch.setattr("app.services.expert_tool_followup.assess_expert_reasoning", assess)
    profile, _decision, reason = await _maybe_escalate(
        ToolWork(
            persona_id="e",
            mode="interview",
            actor_user_id=None,
            history=[],
            user_message="markera alla",
            calls=(PlannedCall("c", "lookup_company", {}),),
            reasoning_profile="deep",
        ),
        {},
        "result",
    )
    assert profile == "deep"
    assert reason is None


@pytest.mark.asyncio
async def test_balanced_episode_can_still_escalate(monkeypatch):
    async def assess(**_kwargs):
        return SimpleNamespace(profile="deep", reason="set_operation")

    monkeypatch.setattr("app.services.expert_tool_followup.assess_expert_reasoning", assess)
    profile, _decision, reason = await _maybe_escalate(
        ToolWork(
            persona_id="e",
            mode="interview",
            actor_user_id=None,
            history=[],
            user_message="markera alla",
            calls=(PlannedCall("c", "lookup_company", {}),),
            reasoning_profile="balanced",
        ),
        {},
        "result",
    )
    assert profile == "deep"
    assert reason == "set_operation"


@pytest.mark.asyncio
async def test_tool_error_stays_in_the_episode():
    seen: list[dict] = []

    async def tools(messages, _specs=None):
        seen.append(messages[-1])
        return SimpleNamespace(content="Inte alla.", tool_calls=None, reasoning_content="checked")

    async def unused_call(_call, _work):
        raise AssertionError("result was already recorded")

    async def unused_publish(_calls):
        raise AssertionError("no new client call")

    set_tools_completer(tools)
    try:
        text, reasoning = await continue_expert_episode(
            ToolWork(
                persona_id="e",
                mode="interview",
                actor_user_id=None,
                history=[],
                user_message="markera alla",
                calls=(PlannedCall("c1", "lookup_company", {}),),
                episode=ExpertEpisode(
                    messages=(
                        {"role": "user", "content": "markera alla"},
                        {
                            "role": "assistant",
                            "content": "",
                            "reasoning_content": "plan",
                            "tool_calls": [{
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "lookup_company", "arguments": "{}"},
                            }],
                        },
                    ),
                    specs=(),
                    prompt_key=None,
                    reasoning_content="plan",
                ),
            ),
            ("boom",),
            run_call=unused_call,
            publish=unused_publish,
        )
    finally:
        set_tools_completer(None)
    assert text == "Inte alla."
    assert reasoning == "checked"
    assert seen[-1]["content"] == "boom"
