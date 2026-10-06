"""Provider/session boundaries tested without network or a second dialogue model."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database.models import Persona, PersonaMessage, PromptField, PromptOverride
from app.database.base import Base
from app.database.session import get_session
from app.database.workspace_conversations import WorkspaceConversationEvent, WorkspaceConversationSession
from app.database.workspace_models import VoiceWorkspace
from app.services.elevenlabs_agents import ElevenLabsAgentsClient, ElevenLabsError, get_elevenlabs_client
from app.services.prompt_fields_store import clear_prompt_cache
from app.services.expertgranskning.memory import set_expert_memory_factory
from tests.conftest import NoopExpertMemory


@pytest.fixture
async def provider(client_db, monkeypatch):
    client, factory = client_db
    monkeypatch.setattr(settings, "elevenlabs_api_key", "private-test-key-never-persist")
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice-fixture")
    monkeypatch.setattr(settings, "elevenlabs_agent_id", "agent-fixture")
    requests = []
    procedures = {}
    connection_sequence = 0

    def transport(request):
        nonlocal connection_sequence
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        path = request.url.path
        if path == "/v1/convai/llm/list":
            result = {"llms": [{"llm": settings.elevenlabs_llm, "deprecation_info": None}]}
        elif path == "/v1/convai/tools":
            result = {"tools": []} if request.method == "GET" else {"id": "tool-" + body["tool_config"]["name"]}
            assert request.method == "GET" or body["tool_config"]["type"] == "client"
        elif path == "/v1/convai/agents/create":
            assert body["platform_settings"]["auth"]["enable_auth"]
            assert body["conversation_config"]["agent"]["prompt"]["backup_llm_config"] == {"preference": "disabled"}
            assert body["conversation_config"]["agent"]["prompt"]["knowledge_base"] == []
            result = {"agent_id": "agent-fixture"}
        elif request.method == "GET" and path == "/v1/convai/agents/agent-fixture":
            result = {"main_branch_id": "branch-fixture", "conversation_config": {"agent": {
                "prompt": {"prompt": "", "llm": "stale-dashboard-model", "tool_ids": ["tool-existing"]}},
                "tts": {"voice_id": "stale-voice"}}}
        elif path.endswith("/procedures"):
            key = "procedure-" + body["name"]
            procedures[key] = {"version_id": "v1"}
            result = {"procedure_id": key}
        elif request.method == "PATCH":
            result = {"version_id": "version-fixture", "procedures": procedures}
        elif path == "/v1/convai/conversation/token":
            connection_sequence += 1
            result = {"token": "private-voice-token", "conversation_id": f"conversation-{connection_sequence}"}
        elif path == "/v1/convai/conversation/get-signed-url":
            connection_sequence += 1
            assert request.url.params["include_conversation_id"] == "true"
            result = {"signed_url": f"wss://provider.test/conversation?conversation_id=conversation-{connection_sequence}&conversation_signature=private-signature"}
        else:
            raise AssertionError(path)
        return httpx.Response(200, json=result)

    async with httpx.AsyncClient(base_url="https://provider.test", transport=httpx.MockTransport(transport)) as http:
        async def mock_client():
            yield ElevenLabsAgentsClient(http)
        client._transport.app.dependency_overrides[get_elevenlabs_client] = mock_client
        async with factory() as db:
            expert = (await db.execute(select(Persona).where(Persona.kind == "expert", Persona.customer_id == 1))).scalars().first()
        created = await client.post("/voice-workspaces?customer_id=1", json={"title": "VoiceWorkspace fixture", "idempotency_key": str(uuid4())})
        assert created.status_code == 201, created.text
        workspace_id = created.json()["id"]
        yield client, factory, workspace_id, expert.id, requests


async def bootstrap(provider, mode="voice"):
    client, _, workspace_id, expert_id, _ = provider
    response = await client.post(f"/workspace-chat/{workspace_id}/sessions", json={"expert_id": expert_id, "mode": mode})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def tool_url(provider, connection):
    return f"/workspace-chat/{provider[2]}/sessions/{connection['session_id']}/tools/read_source"


def tool_body(connection, arguments="{}"):
    return {"conversation_id": connection["conversation_id"], "agent_turn": 1,
            "turn_event_key": "u1", "arguments_json": arguments}


@pytest.mark.asyncio
async def test_private_text_voice_generation_and_revocation(provider):
    client, factory, workspace_id, _, requests = provider
    voice = await bootstrap(provider)
    text = await bootstrap(provider, "text")
    assert voice["connection_type"] == "webrtc" and text["connection_type"] == "websocket"
    assert text["generation"] == voice["generation"] + 1
    assert voice["agent_id"] == text["agent_id"] == "agent-fixture"
    assert sum(path == "/v1/convai/agents/create" for _, path, _ in requests) == 0
    denied = await client.post(tool_url(provider, voice), json=tool_body(voice))
    assert denied.status_code == 401
    wrong = {**tool_body(text), "conversation_id": "unrelated-provider-conversation"}
    denied = await client.post(tool_url(provider, text), json=wrong)
    assert denied.status_code == 401
    denied = await client.post(f"/workspace-chat/{workspace_id}/sessions/{text['session_id']}/bind", json={"conversation_id": voice["conversation_id"]})
    assert denied.status_code == 409
    revoked = await client.delete(f"/workspace-chat/{workspace_id}/sessions/{text['session_id']}")
    assert revoked.status_code == 200
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(WorkspaceConversationSession).where(WorkspaceConversationSession.status == "active")) == 0


@pytest.mark.asyncio
async def test_spoofed_expired_and_other_owner_sessions_are_denied(provider, user_token):
    client, factory, workspace_id, _, _ = provider
    connection = await bootstrap(provider)
    spoofed = {**tool_body(connection), "conversation_id": "unbound"}
    response = await client.post(tool_url(provider, connection), json=spoofed)
    assert response.status_code == 401
    response = await client.get(f"/workspace-chat/{workspace_id}/threads/{provider[3]}/messages", headers={"Authorization": "Bearer " + user_token})
    assert response.status_code == 404
    async with factory() as db:
        row = await db.get(WorkspaceConversationSession, connection["session_id"])
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    response = await client.post(tool_url(provider, connection), json=tool_body(connection))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_transcript_dedup_correction_and_final_memory(provider):
    client, factory, workspace_id, expert_id, _ = provider
    calls = []
    class Memory(NoopExpertMemory):
        async def add_chat_turn(self, **kwargs):
            calls.append(kwargs)
            return []
    set_expert_memory_factory(Memory)
    connection = await bootstrap(provider)
    url = f"/workspace-chat/{workspace_id}/sessions/{connection['session_id']}/events"
    user = {"event_key": "u1", "kind": "user", "text": "Förklara detta"}
    agent = {"event_key": "a1", "kind": "agent", "text": "Detta är det kompletta osagda svaret"}
    assert (await client.post(url, json=user)).status_code == 200
    assert (await client.post(url, json=agent)).status_code == 200
    assert calls == []
    correction = {"event_key": "c1", "kind": "correction", "text": "Detta är", "original_event_key": "a1"}
    fixed = await client.post(url, json=correction)
    assert fixed.status_code == 200
    assert (await client.post(url, json=agent)).json()["duplicate"]
    complete = {"event_key": "done1", "kind": "complete", "original_event_key": "a1"}
    assert (await client.post(url, json=complete)).status_code == 200
    assert (await client.post(url, json=complete)).json()["duplicate"]
    assert len(calls) == 1
    assert calls[0]["assistant_message"] == "Detta är"
    assert calls[0]["customer_id"] == 1
    history = await client.get(f"/workspace-chat/{workspace_id}/threads/{expert_id}/messages")
    assert [row["content"] for row in history.json()["messages"]] == ["Förklara detta", "Detta är"]
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(PersonaMessage)) == 2
        assert await db.scalar(select(func.count()).select_from(WorkspaceConversationEvent).where(WorkspaceConversationEvent.kind != "init")) == 4


@pytest.mark.asyncio
async def test_session_tool_uses_frozen_user_selection_and_stable_operation_identity(provider, monkeypatch):
    from app.api import workspace_conversations as api
    client, factory, workspace_id, _, _ = provider
    connection = await bootstrap(provider)
    url = f"/workspace-chat/{workspace_id}/sessions/{connection['session_id']}/events"
    assert (await client.post(url, json={"event_key": "u1", "kind": "user", "text": "Visa relationerna"})).status_code == 200
    async with factory() as db:
        workspace = await db.get(VoiceWorkspace, workspace_id)
        workspace.state = {**workspace.state, "view": "relations"}
        workspace.revision += 1
        await db.commit()
    captured = []
    async def execute(_session, **kwargs):
        captured.append(kwargs)
        return {"status": "completed", "operation_id": "op1"}
    monkeypatch.setattr(api, "execute_workspace_tool", execute)
    for _ in range(2):
        response = await client.post(tool_url(provider, connection), json=tool_body(connection, '{"source_id":"source-fixture"}'))
        assert response.status_code == 200, response.text
    assert captured[0]["idempotency_key"] == captured[1]["idempotency_key"]
    assert captured[0]["agent_session"].turn_state["view"] == "evidence"
    assert captured[0]["user"].id == captured[0]["agent_session"].user_id


@pytest.mark.asyncio
async def test_provider_secret_never_reaches_transcript(provider):
    client, _, workspace_id, _, _ = provider
    connection = await bootstrap(provider)
    token = settings.elevenlabs_api_key
    url = f"/workspace-chat/{workspace_id}/sessions/{connection['session_id']}/events"
    response = await client.post(url, json={"event_key": "u1", "kind": "user", "text": "Token: " + token})
    assert response.status_code == 200
    history = await client.get(f"/workspace-chat/{workspace_id}/threads/{provider[3]}/messages")
    assert token not in history.text and "<REDACTED>" in history.text


@pytest.fixture
async def single_connection_provider(provider, tmp_path):
    client, source_factory, workspace_id, expert_id, requests = provider
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'voice.db'}",
                                 pool_size=1, max_overflow=0, pool_timeout=0.2)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with source_factory() as source:
        data = [(table, list((await source.execute(select(table))).mappings()))
                for table in Base.metadata.sorted_tables]
    async with factory.begin() as target:
        for table, rows in data:
            if rows:
                await target.execute(table.insert(), [dict(row) for row in rows])
    async def get_single_session():
        async with factory() as session:
            yield session
    app = client._transport.app
    previous = app.dependency_overrides[get_session]
    app.dependency_overrides[get_session] = get_single_session
    try:
        yield (client, factory, workspace_id, expert_id, requests), engine
    finally:
        app.dependency_overrides[get_session] = previous
        await engine.dispose()


async def probe_connection(factory, workspace_id):
    async with factory() as reader:
        assert await reader.get(VoiceWorkspace, workspace_id) is not None


def probing_memory(factory, workspace_id, gate, boundary):
    class Memory(NoopExpertMemory):
        async def search(self, **kwargs):
            await probe_connection(factory, workspace_id)
            if boundary in {"bootstrap_memory", "user_memory"}:
                await gate()
            return []

        async def add_chat_turn(self, **kwargs):
            await probe_connection(factory, workspace_id)
            if boundary == "completion_memory":
                await gate()
            return []
    return Memory


async def prepare_pending_call(provider, boundary):
    if boundary in {"native", "bootstrap_memory"}:
        return bootstrap(provider)
    connection = await bootstrap(provider)
    client, _, workspace_id, _, _ = provider
    url = f"/workspace-chat/{workspace_id}/sessions/{connection['session_id']}/events"
    if boundary == "user_memory":
        return client.post(url, json={"event_key": "u1", "kind": "user", "text": "Vad är risken?"})
    await client.post(url, json={"event_key": "u1", "kind": "user", "text": "Vad är risken?"})
    await client.post(url, json={"event_key": "a1", "kind": "agent", "text": "Detta är svaret."})
    return client.post(url, json={"event_key": "done1", "kind": "complete", "original_event_key": "a1"})


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["native", "bootstrap_memory", "user_memory", "completion_memory"])
async def test_external_phases_release_single_connection(single_connection_provider, boundary):
    provider, engine = single_connection_provider
    client, factory, workspace_id, _, _ = provider
    waiting, release = asyncio.Event(), asyncio.Event()
    armed = boundary in {"native", "bootstrap_memory"}
    async def gate():
        if armed:
            waiting.set()
            await release.wait()
    original = client._transport.app.dependency_overrides[get_elevenlabs_client]
    class ProbingClient(ElevenLabsAgentsClient):
        async def request(self, *args, **kwargs):
            await probe_connection(factory, workspace_id)
            if boundary == "native":
                await gate()
            return await super().request(*args, **kwargs)
    async def dependency():
        async for native in original():
            yield ProbingClient(native.http)
    client._transport.app.dependency_overrides[get_elevenlabs_client] = dependency
    set_expert_memory_factory(probing_memory(factory, workspace_id, gate, boundary))
    call = await prepare_pending_call(provider, boundary)
    armed = True
    task = asyncio.create_task(call)
    try:
        await asyncio.wait_for(waiting.wait(), 3)
        assert engine.pool.checkedout() == 0
        await probe_connection(factory, workspace_id)
    finally:
        release.set()
        result = await task
        client._transport.app.dependency_overrides[get_elevenlabs_client] = original
    if boundary in {"user_memory", "completion_memory"}:
        assert result.status_code == 200, result.text


@pytest.mark.asyncio
async def test_late_correction_updates_completed_transcript_and_memory(provider):
    client, _, workspace_id, expert_id, _ = provider
    calls = []
    class Memory(NoopExpertMemory):
        async def add_chat_turn(self, **kwargs):
            calls.append(kwargs["assistant_message"])
            return []
    set_expert_memory_factory(Memory)
    connection = await bootstrap(provider)
    url = f"/workspace-chat/{workspace_id}/sessions/{connection['session_id']}/events"
    events = [
        {"event_key": "u1", "kind": "user", "text": "Förklara."},
        {"event_key": "a1", "kind": "agent", "text": "Hela svaret"},
        {"event_key": "d1", "kind": "complete", "original_event_key": "a1"},
        {"event_key": "c1", "kind": "correction", "original_event_key": "a1", "text": "Hela"},
    ]
    for event in events:
        response = await client.post(url, json=event)
        assert response.status_code == 200, response.text
    assert calls == ["Hela svaret", "Hela"]
    history = await client.get(f"/workspace-chat/{workspace_id}/threads/{expert_id}/messages")
    assert [message["content"] for message in history.json()["messages"]] == ["Förklara.", "Hela"]


@pytest.mark.asyncio
async def test_prompt_override_keeps_the_configured_agent(provider):
    client, factory, workspace_id, _, requests = provider
    first = await bootstrap(provider)
    async with factory() as db:
        field_id = await db.scalar(select(PromptField.id).where(PromptField.key == "workspace.voice.system"))
        db.add(PromptOverride(customer_id=1, language="sv", prompt_field_id=field_id,
                              text="Testversion för {expert_name}. {expert_profile}"))
        await db.commit()
    clear_prompt_cache()
    second = await bootstrap(provider)
    assert first["prompt_version"] != second["prompt_version"]
    assert first["agent_id"] == second["agent_id"] == "agent-fixture"
    assert sum(path == "/v1/convai/agents/create" for _, path, _ in requests) == 0
    patches = [body for method, path, body in requests if method == "PATCH" and path == "/v1/convai/agents/agent-fixture" and body and "conversation_config" in body]
    applied = patches[-1]["conversation_config"]
    assert applied["agent"]["prompt"]["llm"] == settings.elevenlabs_llm
    assert applied["agent"]["prompt"]["prompt"].startswith("Testversion")
    assert "tool-read_source" in applied["agent"]["prompt"]["tool_ids"]
    assert "tool-search_knowledge" in applied["agent"]["prompt"]["tool_ids"]
    assert "tool-existing" not in applied["agent"]["prompt"]["tool_ids"]
    assert applied["tts"]["voice_id"] == settings.elevenlabs_voice_id
    denied = await client.post(tool_url(provider, first), json=tool_body(first))
    assert denied.status_code == 401
    assert second["generation"] > first["generation"]
    assert second["context"] and workspace_id in second["context"]


@pytest.mark.asyncio
async def test_provider_failure_leaves_failed_generation_and_no_credentials(provider):
    client, factory, workspace_id, _, _ = provider
    class FailingClient:
        async def request(self, *_args, **_kwargs):
            raise ElevenLabsError("elevenlabs_request_failed")

        async def connection(self, **_kwargs):
            raise ElevenLabsError("elevenlabs_request_failed")
    async def failed():
        yield FailingClient()
    client._transport.app.dependency_overrides[get_elevenlabs_client] = failed
    response = await client.post(f"/workspace-chat/{workspace_id}/sessions",
                                 json={"expert_id": provider[3], "mode": "text"})
    assert response.status_code == 502
    assert response.json() == {"detail": "elevenlabs_request_failed"}
    async with factory() as db:
        rows = list((await db.execute(select(WorkspaceConversationSession))).scalars())
        assert len(rows) == 1 and rows[0].status == "failed"
        assert rows[0].conversation_id is None
    assert settings.elevenlabs_api_key not in response.text


@pytest.mark.asyncio
async def test_unsigned_or_unbound_text_connection_is_rejected():
    async with httpx.AsyncClient(base_url="https://provider.test",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"signed_url": "wss://provider.test/public"}))) as http:
        with pytest.raises(ElevenLabsError, match="elevenlabs_missing_conversation_binding"):
            await ElevenLabsAgentsClient(http).connection(agent_id="a", agent_version="v", mode="text")


@pytest.mark.asyncio
async def test_private_workspace_literals_do_not_enter_legacy_history(provider, user_token):
    from app.services.persona_chat import _library_history
    client, factory, workspace_id, expert_id, _ = provider
    connection = await bootstrap(provider)
    url = f"/workspace-chat/{workspace_id}/sessions/{connection['session_id']}/events"
    stored = await client.post(url, json={"event_key": "u1", "kind": "user", "text": "Privat dokumentutdrag"})
    assert stored.status_code == 200
    legacy = await client.get(f"/personas/{expert_id}/messages", headers={"Authorization": "Bearer " + user_token})
    assert legacy.status_code == 200 and legacy.json() == []
    async with factory() as db:
        assert await _library_history(db, expert_id, "interview") == []
    denied = await client.delete(f"/personas/{expert_id}/messages/{stored.json()['message_id']}",
                                 headers={"Authorization": "Bearer " + user_token})
    assert denied.status_code == 404
    history = await client.get(f"/workspace-chat/{workspace_id}/threads/{expert_id}/messages")
    assert [message["content"] for message in history.json()["messages"]] == ["Privat dokumentutdrag"]


@pytest.mark.asyncio
async def test_delayed_tool_uses_its_original_user_turn(provider, monkeypatch):
    from app.api import workspace_conversations as api
    client, factory, workspace_id, _, _ = provider
    connection = await bootstrap(provider)
    url = f"/workspace-chat/{workspace_id}/sessions/{connection['session_id']}/events"
    await client.post(url, json={"event_key": "u1", "kind": "user", "text": "Visa den här."})
    async with factory() as db:
        workspace = await db.get(VoiceWorkspace, workspace_id)
        workspace.state = {**workspace.state, "view": "relations"}
        workspace.revision += 1
        await db.commit()
    await client.post(url, json={"event_key": "u2", "kind": "user", "text": "Och den andra."})
    captured = []
    async def execute(_session, **kwargs):
        captured.append((kwargs["agent_session"].turn_state["view"], kwargs["agent_session"].turn_user_text))
        return {"status": "completed"}
    monkeypatch.setattr(api, "execute_workspace_tool", execute)
    first = await client.post(tool_url(provider, connection), json=tool_body(connection))
    second_body = {**tool_body(connection), "agent_turn": 2, "turn_event_key": "u2"}
    second = await client.post(tool_url(provider, connection), json=second_body)
    assert first.status_code == second.status_code == 200
    assert captured == [("evidence", "Visa den här."), ("relations", "Och den andra.")]
