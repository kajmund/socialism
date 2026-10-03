from uuid import uuid4
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Persona, UserAccount
from app.database.workspace_models import Workspace
from app.services import workspace_expert_tools as tools
from tests.conftest import ADMIN_USER_ID, TEST_CUSTOMER_ID


def test_expert_schema_includes_only_selected_tools_and_workspace_owns_research():
    persona = Persona(id="expert", name="Expert", kind="expert", tools=["search_wiki", "ask_expert", "start_research"])
    schema = tools.expert_tool_schema(persona)
    assert schema["properties"]["name"]["enum"] == ["search_wiki", "ask_expert"]
    assert {row["properties"]["name"]["const"] for row in schema["oneOf"]} == {"search_wiki", "ask_expert"}
    persona.tools = []
    assert tools.expert_tool_schema(persona)["properties"]["name"]["enum"] == []


@pytest.mark.asyncio
async def test_disabled_expert_tool_never_reaches_external_boundary(client_db, monkeypatch):
    client, factory = client_db
    workspace = (await client.post("/workspaces", json={"title": "Avtal", "idempotency_key": str(uuid4())})).json()
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("disabled tool executed")
    monkeypatch.setattr(tools, "run_live_voice_tool", forbidden)
    async with factory() as session:
        session.add(Persona(id="expert", customer_id=TEST_CUSTOMER_ID, kind="expert", name="Expert", occ="Jurist", district="", profile={}, tools=[]))
        await session.commit()
        user = await session.get(UserAccount, ADMIN_USER_ID)
        provider = SimpleNamespace(workspace_id=workspace["id"], expert_id="expert", id="session")
        with pytest.raises(HTTPException) as error:
            await tools.execute_expert_tool(session, provider=provider, user=user, arguments={"name": "search_wiki", "arguments": {"query": "Ägarkontroll"}}, idempotency_key="lookup")
        assert error.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_selected_expert_tool_replay_never_repeats_external_call(client_db, monkeypatch, fails):
    client, factory = client_db
    workspace = (await client.post("/workspaces", json={"title": "Avtal", "idempotency_key": str(uuid4())})).json()
    calls = []

    async def remote(_session, **kwargs):
        calls.append(kwargs["arguments"])
        if fails:
            raise RuntimeError("provider unavailable")
        return "Extern uppgift"

    monkeypatch.setattr(tools, "run_live_voice_tool", remote)
    async with factory() as session:
        session.add(Persona(id="expert", customer_id=TEST_CUSTOMER_ID, kind="expert", name="Expert", occ="Jurist", district="", profile={}, tools=["search_wiki"]))
        await session.commit()
        provider = SimpleNamespace(workspace_id=workspace["id"], expert_id="expert", id="session")
        arguments = {"name": "search_wiki", "arguments": {"query": "Ägarkontroll"}}
        user = await session.get(UserAccount, ADMIN_USER_ID)
        if fails:
            with pytest.raises(RuntimeError, match="provider unavailable"):
                await tools.execute_expert_tool(session, provider=provider, user=user, arguments=arguments, idempotency_key="lookup")
        else:
            first = await tools.execute_expert_tool(session, provider=provider, user=user, arguments=arguments, idempotency_key="lookup")
        user = await session.get(UserAccount, ADMIN_USER_ID)
        replay = await tools.execute_expert_tool(session, provider=provider, user=user, arguments=arguments, idempotency_key="lookup")
        assert replay["status"] == ("failed" if fails else "completed")
        if not fails:
            assert replay == first
        with pytest.raises(HTTPException) as error:
            await tools.execute_expert_tool(session, provider=provider, user=user, arguments={"name": "search_wiki", "arguments": {"query": "Ändrad fråga"}}, idempotency_key="lookup")
        assert error.value.status_code == 409
    assert calls == [{"query": "Ägarkontroll"}]


@pytest.mark.asyncio
async def test_selected_lookup_returns_connection_while_remote_pending(client_db, tmp_path, monkeypatch):
    client, source_factory = client_db
    workspace = (await client.post("/workspaces", json={"title": "Avtal", "idempotency_key": str(uuid4())})).json()
    async with source_factory() as session:
        session.add(Persona(id="expert", customer_id=TEST_CUSTOMER_ID, kind="expert", name="Expert", occ="Jurist", district="", profile={}, tools=["search_wiki"]))
        await session.commit()
        pairs = [(Workspace, workspace["id"]), (Persona, "expert"), (UserAccount, ADMIN_USER_ID)]
        copies = []
        for model, key in pairs:
            row = await session.get(model, key)
            copies.append(model(**{column.name: getattr(row, column.name) for column in model.__table__.columns}))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/expert.db", pool_size=1, max_overflow=0, pool_timeout=0.3)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add_all(copies)
        await session.commit()
    waiting = asyncio.Event()
    release = asyncio.Event()

    async def remote(session, **kwargs):
        assert not session.in_transaction()
        assert kwargs["persona"].id == "expert" and kwargs["user"].id == ADMIN_USER_ID
        assert kwargs["name"] == "search_wiki"
        waiting.set()
        await release.wait()
        return "Extern uppgift"

    monkeypatch.setattr(tools, "run_live_voice_tool", remote)
    async def run():
        async with factory() as session:
            user = await session.get(UserAccount, ADMIN_USER_ID)
            provider = SimpleNamespace(workspace_id=workspace["id"], expert_id="expert", id="session", turn_user_text="Sök", turn_previous_agent_text="")
            return await tools.execute_expert_tool(session, provider=provider, user=user, arguments={"name": "search_wiki", "arguments": {"query": "Ägarkontroll"}}, idempotency_key="lookup")
    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        async with factory() as reader:
            assert await reader.get(Workspace, workspace["id"]) is not None
    finally:
        release.set()
        result = await task
        await engine.dispose()
    assert result["status"] == "completed" and result["result"] == "Extern uppgift"
    assert result["operation_id"]
