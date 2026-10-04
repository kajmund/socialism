"""Chat discovers authorized files and freezes only the model's selected originals."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    Job,
    Kund,
    StoredObject,
    UserAccount,
)
from app.database.text_units import SharedTextChunkRecord, TextUnitRecord
from app.schemas.workspace_chat import WorkspaceChatCreate
from app.services.knowledge.units import hash_text
from app.services.prompt_store import ensure_default_configurations
from app.services.workspace_chat_documents import document_inventory, workspace_research_tool_spec
from app.services.workspace_chat_turn import workspace_chat_turn
from app.services.workspace_chats import create_chat
from app.services.workspaces import create_client_workspace, ensure_company_workspace

USER_ID = "document-selection-user"
SOURCE_TEXT = "Parkeringskvittot visar ett belopp på 85 kronor inklusive moms."


async def _seed_ready_document(session, source):
    scope = {"scope_type": "customer", "scope_key": f"customer:{source.customer_id}",
             "customer_id": source.customer_id}
    content_hash = hash_text(f"{source.filename}: {SOURCE_TEXT}")
    document_id, version_id = f"document-{source.id}", f"version-{source.id}"
    session.add(CanonicalDocumentRecord(
        id=document_id, **scope, source_object_id=source.id, source_type="uploaded_file",
        canonical_uri=f"stored-object:{source.id}", title=source.filename,
        extra={"workspace_id": source.workspace_id},
    ))
    await session.flush()
    session.add(DocumentVersionRecord(
        id=version_id, **scope, document_id=document_id, content_hash=content_hash,
        mime_type=source.content_type,
    ))
    session.add(SharedTextChunkRecord(content_hash=content_hash, text=f"{source.filename}: {SOURCE_TEXT}"))
    await session.flush()
    session.add(TextUnitRecord(
        id=f"unit-{source.id}", **scope, document_id=document_id,
        document_version_id=version_id, ordinal=0, content_hash=content_hash, locator="page:1",
    ))


async def _seed_sources(factory, workspaces):
    samples = [
        ("policy", "Policy.pdf", workspaces.common, 1, "ready"),
        ("company-pending", "Ny policy.pdf", workspaces.common, 1, "pending"),
        ("receipt", "parking_receipt_3157386478.pdf", workspaces.active, 1, "ready"),
        ("client-pending", "yttrande_ro_da_husen.pdf", workspaces.active, 1, "pending"),
        ("sibling", "Annan klients avtal.pdf", workspaces.sibling, 1, "ready"),
        ("foreign", "Annan byrås avtal.pdf", workspaces.foreign, 2, "ready"),
    ]
    async with factory.begin() as session:
        for identity, filename, workspace_id, customer_id, status in samples:
            source = StoredObject(
                id=identity, filename=filename, workspace_id=workspace_id, customer_id=customer_id,
                owner_user_id=USER_ID if customer_id == 1 else "foreign-user",
                module="dd", kind="underlag", bucket="test", object_key=identity,
                content_type="application/pdf", size_bytes=100, knowledge_status=status,
                extracted_text="Private source body must not appear in the file inventory.",
            )
            session.add(source)
            await session.flush()
            if status == "ready":
                await _seed_ready_document(session, source)


@pytest.fixture
async def document_chat(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'document-chat.db'}",
        pool_size=1, max_overflow=0, pool_timeout=0.1,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add_all([
            Kund(id=1, name="Byrån", slug="document-chat", available_modules=["dd"]),
            Kund(id=2, name="Annan byrå", slug="foreign-document-chat", available_modules=["dd"]),
            UserAccount(id=USER_ID, email="documents@test.invalid", role="user", kund_id=1),
            UserAccount(id="foreign-user", email="foreign@test.invalid", role="user", kund_id=2),
        ])
        await session.flush()
        await ensure_default_configurations(session)
        common = await ensure_company_workspace(session, customer_id=1)
        active = await create_client_workspace(session, customer_id=1, user_id=USER_ID, name="Klient A")
        sibling = await create_client_workspace(session, customer_id=1, user_id=USER_ID, name="Klient B")
        foreign = await ensure_company_workspace(session, customer_id=2)
        user = await session.get(UserAccount, USER_ID)
        chat = await create_chat(session, user, WorkspaceChatCreate(workspace_id=active.id))
        fixture = SimpleNamespace(
            engine=engine, factory=factory, chat_id=chat.id, active=active.id,
            common=common.id, sibling=sibling.id, foreign=foreign.id,
        )
        await session.commit()
    await _seed_sources(factory, fixture)
    monkeypatch.setattr("app.services.jobs.enqueue_job", lambda _identity: None)
    try:
        yield fixture
    finally:
        await engine.dispose()


async def _inventory(fixture, *, company=False):
    from app.database.workspaces import WorkspaceChat

    async with fixture.factory() as session:
        user = await session.get(UserAccount, USER_ID)
        chat = await session.get(WorkspaceChat, fixture.chat_id)
        if company:
            chat = await create_chat(session, user, WorkspaceChatCreate())
        return json.loads(await document_inventory(session, user, chat))


def _tool_reply(arguments):
    return SimpleNamespace(
        content="Jag undersöker dokumentet.",
        tool_calls=[SimpleNamespace(
            id="research-1",
            function=SimpleNamespace(name="start_research", arguments=json.dumps(arguments)),
        )],
    )


def _stub_tool(monkeypatch, arguments):
    async def with_tools(*_args, **_kwargs):
        return _tool_reply(arguments)

    async def complete(*_args, **_kwargs):
        return "Research har köats."

    monkeypatch.setattr("app.services.workspace_chat_turn.complete_with_tools", with_tools)
    monkeypatch.setattr("app.services.workspace_chat_turn.complete_text", complete)


async def _turn(fixture):
    async with fixture.factory() as session:
        user = await session.get(UserAccount, USER_ID)
        return await workspace_chat_turn(session, user, fixture.chat_id, "Vad står på kvittot?")


async def _jobs(fixture):
    async with fixture.factory() as session:
        return list(await session.scalars(select(Job)))


async def test_inventory_lists_active_and_company_status_without_other_clients(document_chat):
    inventory = await _inventory(document_chat)
    indexed = {row["source_object_id"]: row for row in inventory}
    assert set(indexed) == {"policy", "company-pending", "receipt", "client-pending"}
    assert indexed["receipt"] == {
        "source_object_id": "receipt", "filename": "parking_receipt_3157386478.pdf",
        "knowledge_status": "ready", "workspace_id": document_chat.active,
    }
    assert indexed["policy"]["workspace_id"] == document_chat.common
    assert indexed["company-pending"]["knowledge_status"] == "pending"
    assert indexed["client-pending"]["knowledge_status"] == "pending"
    assert "Private source body" not in json.dumps(inventory)


async def test_default_company_inventory_excludes_client_documents(document_chat):
    inventory = await _inventory(document_chat, company=True)
    assert {row["source_object_id"] for row in inventory} == {"policy", "company-pending"}
    assert {row["workspace_id"] for row in inventory} == {document_chat.common}


def test_workspace_tool_exposes_optional_document_selection():
    function = workspace_research_tool_spec()["function"]
    assert function["name"] == "start_research"
    selection = function["parameters"]["properties"]["source_object_ids"]
    assert selection["type"] == "array"
    assert selection["items"]["type"] == "string"
    assert "source_object_ids" not in function["parameters"]["required"]


async def test_tool_selects_ready_receipt_while_unrelated_file_pending_and_releases_pool(
    document_chat, monkeypatch
):
    started = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]
    calls = []

    async def wait_external(stage):
        assert document_chat.engine.pool.checkedout() == 0
        calls.append(stage)
        started[stage].set()
        await release[stage].wait()

    async def with_tools(messages, tools, **_kwargs):
        system = messages[0]["content"]
        assert "parking_receipt_3157386478.pdf" in system
        assert "yttrande_ro_da_husen.pdf" in system
        assert "Annan klients avtal.pdf" not in system
        assert "Annan byrås avtal.pdf" not in system
        assert "Private source body" not in system
        assert tools[0]["function"]["parameters"]["properties"]["source_object_ids"]
        await wait_external(0)
        return _tool_reply({"question": "Vad står på kvittot?", "source_object_ids": ["receipt"]})

    async def complete(*_args, **_kwargs):
        await wait_external(1)
        return "Research av kvittot har köats."

    def enqueue(_identity):
        assert document_chat.engine.pool.checkedout() == 0

    monkeypatch.setattr("app.services.workspace_chat_turn.complete_with_tools", with_tools)
    monkeypatch.setattr("app.services.workspace_chat_turn.complete_text", complete)
    monkeypatch.setattr("app.services.jobs.enqueue_job", enqueue)
    task = asyncio.create_task(_turn(document_chat))
    try:
        for stage in range(2):
            await asyncio.wait_for(started[stage].wait(), 2)
            async with document_chat.factory() as other:
                assert await asyncio.wait_for(other.scalar(text("SELECT 1")), 1) == 1
            release[stage].set()
        await task
    finally:
        for event in release:
            event.set()
        await task
    queued = await _jobs(document_chat)
    assert calls == [0, 1] and len(queued) == 1
    assert queued[0].request["entrypoint"] == "tool"
    assert queued[0].request["document_manifest"] == [{
        "source_object_id": "receipt", "document_id": "document-receipt",
        "document_version_id": "version-receipt", "workspace_id": document_chat.active,
    }]
    assert queued[0].request["readable_workspace_ids"] == [document_chat.common, document_chat.active]


@pytest.mark.parametrize("source_id", ["sibling", "foreign"])
async def test_model_cannot_select_document_outside_active_scope(document_chat, monkeypatch, source_id):
    _stub_tool(monkeypatch, {"question": "Läs avtalet", "source_object_ids": [source_id]})
    with pytest.raises(HTTPException) as failure:
        await _turn(document_chat)
    assert failure.value.status_code == 404
    assert failure.value.detail == "research_document_not_found"
    assert await _jobs(document_chat) == []


async def test_omitted_tool_selection_still_blocks_on_all_visible_pending_files(document_chat, monkeypatch):
    _stub_tool(monkeypatch, {"question": "Undersök hela workspacet"})
    with pytest.raises(HTTPException) as failure:
        await _turn(document_chat)
    assert failure.value.status_code == 409
    assert failure.value.detail == "research_documents_not_ready"
    assert await _jobs(document_chat) == []


async def test_omitted_tool_selection_freezes_all_visible_ready_files(document_chat, monkeypatch):
    async with document_chat.factory.begin() as session:
        await session.execute(delete(StoredObject).where(StoredObject.knowledge_status == "pending"))
    _stub_tool(monkeypatch, {"question": "Undersök hela workspacet"})
    await _turn(document_chat)
    queued = await _jobs(document_chat)
    assert len(queued) == 1
    assert {row["source_object_id"] for row in queued[0].request["document_manifest"]} == {"policy", "receipt"}


async def test_explicit_empty_tool_selection_stays_empty_despite_pending_files(document_chat, monkeypatch):
    _stub_tool(monkeypatch, {"question": "Undersök allmän kunskap", "source_object_ids": []})
    await _turn(document_chat)
    queued = await _jobs(document_chat)
    assert len(queued) == 1
    assert queued[0].request["document_manifest"] == []
