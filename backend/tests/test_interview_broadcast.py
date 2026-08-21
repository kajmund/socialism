"""Tests for run-interview WebSocket broadcast registry."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketState

from app.realtime.interview_broadcast import (
    InterviewBroadcastRegistry,
    interview_key_tuple,
)


class FakeWebSocket:
    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_interview_broadcast_delivers_to_subscribed_socket_only():
    registry = InterviewBroadcastRegistry()
    key_a = interview_key_tuple(
        persona_id="per_a",
        run_id=1,
        attempt_id="att_1",
        variant_id="main",
        through_tick_index=0,
    )
    key_b = interview_key_tuple(
        persona_id="per_b",
        run_id=1,
        attempt_id="att_1",
        variant_id="main",
        through_tick_index=0,
    )
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()

    await registry.subscribe(key_a, ws_a)
    await registry.subscribe(key_b, ws_b)

    message = {"id": 42, "role": "user", "content": "Hej", "asked_by": "doctor"}
    await registry.publish(key_a, message)

    assert ws_a.sent == [{"type": "interview.message", "message": message}]
    assert ws_b.sent == []


@pytest.mark.asyncio
async def test_interview_broadcast_unsubscribe_on_disconnect():
    registry = InterviewBroadcastRegistry()
    key = interview_key_tuple(
        persona_id="per_a",
        run_id=1,
        attempt_id="att_1",
        variant_id="main",
        through_tick_index=0,
    )
    ws = FakeWebSocket()
    await registry.subscribe(key, ws)
    await registry.unsubscribe(ws)

    await registry.publish(key, {"id": 1, "role": "user", "content": "x"})
    assert ws.sent == []


@pytest.mark.asyncio
async def test_spindoctor_tool_loop_runs_multiple_calls_on_one_session(monkeypatch):
    from app.services.spindoctor_chat import _run_spindoctor_tool_loop
    from app.services.spindoctor_mcp_tools import SpindoctorToolContext

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async def fake_tool(session, name, _arguments, *, ctx):
        await session.execute(text("SELECT 1"))
        return f"ok:{name}"

    class FakeCall:
        def __init__(self, call_id: str, name: str) -> None:
            self.id = call_id

            class Fn:
                pass

            self.function = Fn()
            self.function.name = name
            self.function.arguments = "{}"

    class FakeMessage:
        def __init__(self) -> None:
            self.content = ""
            self.tool_calls = [
                FakeCall("call_1", "list_runs"),
                FakeCall("call_2", "list_reports"),
            ]

    round_count = 0

    async def fake_complete(_messages, _tools):
        nonlocal round_count
        round_count += 1
        if round_count == 1:
            return FakeMessage()
        empty = FakeMessage()
        empty.tool_calls = None
        return empty

    monkeypatch.setattr(
        "app.services.spindoctor_chat.complete_with_tools",
        fake_complete,
    )
    monkeypatch.setattr(
        "app.services.spindoctor_chat.run_spindoctor_mcp_tool",
        fake_tool,
    )

    ctx = SpindoctorToolContext()
    async with session_factory() as session:
        working, _widgets = await _run_spindoctor_tool_loop(
            session,
            [{"role": "system", "content": "test"}],
            ctx=ctx,
        )
    await engine.dispose()

    tool_messages = [row for row in working if row.get("role") == "tool"]
    assert [row["tool_call_id"] for row in tool_messages] == ["call_1", "call_2"]
    assert [row["content"] for row in tool_messages] == ["ok:list_runs", "ok:list_reports"]
