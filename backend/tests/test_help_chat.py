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
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-supabase-jwt-secret-not-real")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-supabase-service-role-not-real")

from app.config import settings
from app.database.base import Base
from app.database.models import UserAccount
from app.database.session import get_session
from app.llm import set_text_completer, set_text_streamer, set_tools_completer
from app.main import create_app
from app.services import jobs as jobs_service
from app.services.help_chat import (
    ChatTurnError,
    list_help_messages,
    looks_like_leaked_tool_markup,
    stream_help_chat_turn,
)
from app.services.okf_corpus import search_manual
from app.services.prompt_store import ensure_default_configurations
from tests.conftest import ADMIN_USER_ID, TEST_JWT_SECRET, mint_access_token


def test_looks_like_leaked_tool_markup_detects_dsml_and_invoke():
    assert looks_like_leaked_tool_markup(
        "Låt mig hämta metadata.\n\n<invoke name=\"scb_get_table_meta\">"
    )
    assert looks_like_leaked_tool_markup("… DSML tool_calls …")
    assert not looks_like_leaked_tool_markup(
        "Norrköping har ungefär lika många kvinnor och män enligt SCB."
    )


@pytest.fixture
def help_client():
    settings.deepseek_api_key = "test-key-not-real"
    settings.supabase_jwt_secret = TEST_JWT_SECRET

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
            seed_session.add(
                UserAccount(
                    id=ADMIN_USER_ID,
                    email="admin@test.local",
                    role="admin",
                    kund_id=None,
                )
            )
            await seed_session.commit()

    loop.run_until_complete(_prepare())

    jobs_service.set_job_session_factory(session_factory)
    app = create_app()

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    admin_token = mint_access_token(sub=ADMIN_USER_ID, email="admin@test.local")
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {admin_token}"
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

    token = mint_access_token(sub=ADMIN_USER_ID, email="admin@test.local")
    with client.websocket_connect(f"/ws/chat?access_token={token}") as ws:
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

        assert tokens == ["Mockat hjälpssvar."]
        assert done is not None
        assert done["reply"] == "Mockat hjälpssvar."
        assert len(done["messages"]) >= 2
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


def test_help_chat_rejects_leaked_tool_markup_as_final_reply(help_client):
    _client, loop, factory, _tools_calls = help_client
    session_id = "leak-help-session"
    leaked = (
        "Jag måste få rätt variabelnamn.\n"
        '<invoke name="scb_get_table_meta">'
        '<parameter name="table_id">TAB6570</parameter>'
        "</invoke>"
    )

    class _LeakedToolMessage:
        content = leaked
        tool_calls = None

    async def _leaked_tools(_messages: list[dict[str, object]], _tools: list | None = None):
        return _LeakedToolMessage()

    async def _leaked_stream(_messages: list[dict[str, str]]):
        yield leaked

    set_tools_completer(_leaked_tools)
    set_text_streamer(_leaked_stream)

    async def _run() -> None:
        async with factory() as session:
            with pytest.raises(ChatTurnError, match="invalid reply"):
                async for _ in stream_help_chat_turn(
                    session,
                    session_id=session_id,
                    locale="sv",
                    message="hur är norrköping fördelat enligt scb?",
                ):
                    pass

    try:
        loop.run_until_complete(_run())
    finally:
        # fixture teardown also clears injectors; restore safe defaults for later tests
        async def _mock_tools(_messages: list[dict[str, object]], _tools: list | None = None):
            class _Ok:
                content = "Mockat hjälpssvar."
                tool_calls = None

            return _Ok()

        async def _mock_stream(_messages: list[dict[str, str]]):
            yield "Mockat hjälpssvar."

        set_tools_completer(_mock_tools)
        set_text_streamer(_mock_stream)


def test_help_chat_streams_clean_reply_when_tool_turn_leaked(help_client):
    _client, loop, factory, _tools_calls = help_client
    session_id = "leak-recover-session"

    class _LeakedToolMessage:
        content = 'Låt mig kolla.\n<invoke name="scb_population_dist"></invoke>'
        tool_calls = None

    async def _leaked_tools(_messages: list[dict[str, object]], _tools: list | None = None):
        return _LeakedToolMessage()

    async def _clean_stream(_messages: list[dict[str, str]]):
        yield "Norrköping: ungefär 50/50 kön enligt SCB."

    set_tools_completer(_leaked_tools)
    set_text_streamer(_clean_stream)

    async def _run() -> str:
        reply = ""
        async with factory() as session:
            async for item in stream_help_chat_turn(
                session,
                session_id=session_id,
                locale="sv",
                message="hur är norrköping fördelat?",
            ):
                if isinstance(item, str):
                    reply += item
                else:
                    reply = item.reply
        return reply

    try:
        reply = loop.run_until_complete(_run())
        assert "Norrköping" in reply
        assert "<invoke" not in reply
    finally:
        async def _mock_tools(_messages: list[dict[str, object]], _tools: list | None = None):
            class _Ok:
                content = "Mockat hjälpssvar."
                tool_calls = None

            return _Ok()

        async def _mock_stream(_messages: list[dict[str, str]]):
            yield "Mockat hjälpssvar."

        set_tools_completer(_mock_tools)
        set_text_streamer(_mock_stream)
