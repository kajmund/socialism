"""Tests for OKF corpus search and help chat."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key-not-real")

from app.config import settings
from app.database.base import Base
from app.database.session import get_session
from app.llm import set_text_completer, set_text_streamer, set_tools_completer
from app.main import create_app
from app.services import jobs as jobs_service
from app.services.help_chat import list_help_messages, stream_help_chat_turn
from app.services.okf_corpus import search_manual
from app.services.prompt_store import ensure_default_configurations


@pytest.fixture
def help_client():
    settings.deepseek_api_key = "test-key-not-real"

    async def _mock_text(_messages: list[dict[str, str]]) -> str:
        return "Mockat hjälpssvar."

    async def _mock_stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        for piece in ("Mockat ", "hjälpssvar."):
            yield piece

    class _MockToolMessage:
        content = "Mockat hjälpssvar."
        tool_calls = None

    tools_calls = {"count": 0}

    async def _mock_tools(_messages: list[dict[str, object]], _tools: list | None = None):
        tools_calls["count"] += 1
        return _MockToolMessage()

    set_text_completer(_mock_text)
    set_text_streamer(_mock_stream)
    set_tools_completer(_mock_tools)

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    loop = asyncio.new_event_loop()

    async def _prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as seed_session:
            await ensure_default_configurations(seed_session)

    loop.run_until_complete(_prepare())

    jobs_service.set_job_session_factory(session_factory)
    app = create_app()

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as client:
        yield client, loop, session_factory, tools_calls

    jobs_service.set_job_session_factory(None)
    set_text_completer(None)
    set_text_streamer(None)
    set_tools_completer(None)
    loop.run_until_complete(engine.dispose())
    loop.close()


def test_search_manual_finds_korning_guide():
    hits = search_manual("starta simulering körning", limit=3)
    slugs = {guide.slug for guide in hits}
    assert "starta-simulering" in slugs or "skapa-korning" in slugs


def test_help_chat_websocket_streams(help_client):
    client, _loop, _factory, tools_calls = help_client
    session_id = "test-help-session"
    view = {
        "path": "/runs",
        "view_key": "runs.list",
        "label": "Körningar — lista",
        "params": {},
        "search": {},
    }

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json(
            {
                "type": "hello",
                "scope": "help",
                "session_id": session_id,
                "locale": "sv",
                "view": view,
            }
        )
        ready = ws.receive_json()
        assert ready["type"] == "ready"

        ws.send_json({"type": "send", "message": "Hur startar jag en simulering?", "view": view})
        typing = ws.receive_json()
        assert typing == {"type": "typing", "on": True}

        tokens: list[str] = []
        done = None
        for _ in range(10):
            event = ws.receive_json()
            if event["type"] == "token":
                tokens.append(event["text"])
            elif event["type"] == "done":
                done = event
                break
            elif event["type"] == "error":
                pytest.fail(event["detail"])

        assert tokens == ["Mockat ", "hjälpssvar."]
        assert done is not None
        assert done["reply"] == "Mockat hjälpssvar."
        assert len(done["messages"]) >= 2
        assert tools_calls["count"] == 0


def test_help_chat_websocket_scb_tools_when_enabled(help_client):
    client, _loop, _factory, tools_calls = help_client
    session_id = "test-help-scb-session"
    view = {
        "path": "/populations/new",
        "view_key": "populations.new",
        "label": "Population — ny",
        "params": {},
        "search": {},
    }

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json(
            {
                "type": "hello",
                "scope": "help",
                "session_id": session_id,
                "locale": "sv",
                "view": view,
            }
        )
        assert ws.receive_json()["type"] == "ready"

        ws.send_json(
            {
                "type": "send",
                "message": "Grounda ålder för Uppsala",
                "view": view,
                "use_scb": True,
            }
        )
        assert ws.receive_json() == {"type": "typing", "on": True}

        done = None
        for _ in range(10):
            event = ws.receive_json()
            if event["type"] == "done":
                done = event
                break
            if event["type"] == "error":
                pytest.fail(event["detail"])

        assert done is not None
        assert tools_calls["count"] >= 1


def test_help_messages_rest(help_client):
    client, loop, factory, _tools_calls = help_client
    session_id = "rest-help-session"

    async def _run_turn() -> None:
        async with factory() as session:
            async for item in stream_help_chat_turn(
                session,
                session_id=session_id,
                locale="sv",
                message="Vad är en population?",
            ):
                if not isinstance(item, str):
                    assert item.reply

    loop.run_until_complete(_run_turn())

    listed = client.get("/help/messages", params={"session_id": session_id})
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) >= 2
    assert body[-1]["role"] == "assistant"

    cleared = client.delete("/help/messages", params={"session_id": session_id})
    assert cleared.status_code == 204

    async def _list_empty() -> list:
        async with factory() as session:
            return await list_help_messages(session, session_id)

    assert loop.run_until_complete(_list_empty()) == []
