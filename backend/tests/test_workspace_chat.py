"""Chat entry points freeze one scope; external work releases its input transaction."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Job, Kund, StoredObject, UserAccount
from app.database.workspaces import WorkspaceChatMessage
from app.schemas.workspace_chat import WorkspaceChatCreate
from app.services import jobs
from app.services.prompt_store import ensure_default_configurations
from app.services.research.workspace_context import research_context_from_run
from app.services.workspace_chat_turn import workspace_chat_turn
from app.services.workspace_chats import create_chat
from app.services.workspace_research_answer import _answer_items, _source_labels
from tests.conftest import USER_USER_ID


@pytest.fixture(autouse=True)
def hold_jobs(monkeypatch):
    monkeypatch.setattr(jobs, "enqueue_job", lambda _identity: None)


def test_source_ownership_uses_provenance_before_content_type():
    workspace = SimpleNamespace(id="client-a", kind="client")
    items = [
        SimpleNamespace(
            id="a",
            source_type="domain_knowledge",
            title="Avtal",
            provenance={"workspace_id": "client-a", "scope_type": "shared"},
        ),
        SimpleNamespace(
            id="b",
            source_type="swedish_law",
            title="Policy",
            provenance={"source_object_id": "private", "workspace_id": "company"},
        ),
        SimpleNamespace(
            id="c",
            source_type="domain_knowledge",
            title="Global",
            provenance={"scope_type": "shared"},
        ),
    ]
    refs = {f"E{index}": SimpleNamespace(item_id=item.id) for index, item in enumerate(items, 1)}
    assert _source_labels(items, refs, workspace).splitlines() == [
        "[E1] Klientens dokument: Avtal",
        "[E2] Företagets privata kunskap: Policy",
        "[E3] Global kunskap: Global",
    ]


def test_research_reply_cites_original_sources_instead_of_intermediate_answers():
    rows = [
        SimpleNamespace(
            id="original",
            status="found",
            source_type="case_knowledge",
            source_url=None,
            provenance={"document_version_id": "v1", "text_unit_id": "u1"},
        ),
        SimpleNamespace(
            id="summary", status="found", source_type="derived", source_url=None, provenance={}
        ),
        SimpleNamespace(
            id="linked-summary",
            status="found",
            source_type="derived",
            source_url="https://example.org",
            provenance={"document_version_id": "v1", "text_unit_id": "u1"},
        ),
        SimpleNamespace(
            id="law",
            status="found",
            source_type="swedish_law",
            source_url="https://lagen.nu/2000:1",
            provenance={"scope_type": "shared"},
        ),
        SimpleNamespace(
            id="gap",
            status="unavailable",
            source_type="swedish_case_law",
            source_url=None,
            provenance={},
        ),
    ]
    assert [row.id for row in _answer_items(rows)] == ["original", "law", "gap"]


async def test_chat_defaults_and_does_not_switch_workspace(client, user_token):
    client.headers["Authorization"] = f"Bearer {user_token}"
    common = (await client.get("/workspaces")).json()[0]
    first = (await client.post("/workspace-chats", json={})).json()
    assert first["workspace_id"] == common["id"] and first["persona_id"] is None
    workspace = (await client.post("/workspaces", json={"name": "Klient A"})).json()
    second = (await client.post("/workspace-chats", json={"workspace_id": workspace["id"]})).json()
    assert (await client.get("/workspace-chats")).json() == [first]
    assert (
        await client.get("/workspace-chats", params={"workspace_id": workspace["id"]})
    ).json() == [second]
    assert (await client.get(f"/workspace-chats/{first['id']}")).json()["workspace_id"] == common[
        "id"
    ]


async def test_chat_upload_keeps_scope_after_storage_releases_session(client_db, user_token):
    client, factory = client_db
    client.headers["Authorization"] = f"Bearer {user_token}"
    workspace = (await client.post("/workspaces", json={"name": "Klient A"})).json()["id"]
    chat = (await client.post("/workspace-chats", json={"workspace_id": workspace})).json()
    response = await client.post(
        f"/workspace-chats/{chat['id']}/files",
        files={"file": ("contract.txt", b"Private agreement", "text/plain")},
    )
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["workspace_id"] == workspace
    assert [
        row["id"] for row in (await client.get(f"/workspace-chats/{chat['id']}/files")).json()
    ] == [document["id"]]
    async with factory() as session:
        source = await session.get(StoredObject, document["id"])
        job = await session.get(Job, source.knowledge_job_id)
        assert job.request["workspace_id"] == workspace
    blocked = await client.post(
        f"/workspace-chats/{chat['id']}/research",
        json={"question": "Vad säger avtalet?", "source_object_ids": [document["id"]]},
    )
    assert blocked.status_code == 409


async def test_modal_freezes_empty_selection_and_blocks_sibling(client, user_token):
    client.headers["Authorization"] = f"Bearer {user_token}"
    chat = (await client.post("/workspace-chats", json={})).json()
    queued = await client.post(
        f"/workspace-chats/{chat['id']}/research",
        json={"question": "Vilka källor finns?", "source_object_ids": []},
    )
    assert queued.status_code == 202, queued.text
    payload = queued.json()["request"]
    assert payload["document_manifest"] == [] and payload["workspace_id"] == chat["workspace_id"]
    rejected = await client.post(
        f"/workspace-chats/{chat['id']}/research",
        json={"question": "Läs den andra klienten", "source_object_ids": ["sibling-document"]},
    )
    assert rejected.status_code == 404


@pytest.mark.parametrize("tool", [False, True])
async def test_chat_llm_and_tool_release_single_connection(tmp_path, monkeypatch, tool):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}", pool_size=1, max_overflow=0, pool_timeout=0.1
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=1, name="Byrån", slug="chat-proof", available_modules=["dd"]))
        session.add(UserAccount(id=USER_USER_ID, email="user@test.local", role="user", kund_id=1))
        await session.flush()
        await ensure_default_configurations(session)
        await session.commit()
    async with factory() as session:
        user = await session.get(UserAccount, USER_USER_ID)
        chat = await create_chat(session, user, WorkspaceChatCreate())
        identity = chat.id
        await session.commit()
    calls = []

    async def external(*_args, **_kwargs):
        assert engine.pool.checkedout() == 0
        async with factory() as probe:
            assert await probe.get(Kund, 1)
        calls.append("llm")
        return "Research har köats." if tool else "Svar i företagets workspace."

    async def with_tools(*args, **kwargs):
        content = await external(*args, **kwargs)
        call = SimpleNamespace(
            id="tool-1",
            function=SimpleNamespace(
                name="start_research", arguments='{"question":"Undersök avtalet"}'
            ),
        )
        return SimpleNamespace(content=content, tool_calls=[call] if tool else [])

    monkeypatch.setattr("app.services.workspace_chat_turn.complete_with_tools", with_tools)
    monkeypatch.setattr("app.services.workspace_chat_turn.complete_text", external)
    try:
        async with factory() as session:
            user = await session.get(UserAccount, USER_USER_ID)
            await workspace_chat_turn(session, user, identity, "Undersök avtalet")
        assert len(calls) == (2 if tool else 1)
        async with factory() as session:
            messages = list(
                await session.scalars(
                    select(WorkspaceChatMessage).where(WorkspaceChatMessage.chat_id == identity)
                )
            )
            assert messages[-1].role == "assistant"
            queued = list(await session.scalars(select(Job)))
            assert len(queued) == int(tool)
            if tool:
                assert queued[0].request["entrypoint"] == "tool"
                assert queued[0].request["document_manifest"] == []
    finally:
        await engine.dispose()


def test_workspace_scope_refuses_missing_manifest_and_keeps_explicit_empty_selection():
    run = SimpleNamespace(customer_id=1, module="dd", context={"workspace_id": "active"})
    with pytest.raises(ValueError, match="manifest"):
        research_context_from_run(run)
    run.context.update({"document_manifest": [], "readable_workspace_ids": ["company", "active"]})
    scope = research_context_from_run(run).scope
    assert scope.allowed_source_object_ids == scope.allowed_document_version_ids == ()
    assert scope.readable_workspace_ids == ("company", "active")


@pytest.mark.parametrize("field", ["document_manifest", "readable_workspace_ids"])
def test_workspace_scope_never_ignores_an_unbound_selection(field):
    run = SimpleNamespace(customer_id=1, module="dd", context={field: []})
    with pytest.raises(ValueError, match="resolved workspace"):
        research_context_from_run(run)
