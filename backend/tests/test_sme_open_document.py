"""The open agreement is loaded in a short transaction before any model call."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund, StoredObject, UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceArtifact, WorkspaceReference
from app.schemas.workspace import DocumentMention, WorkspaceDocumentSet, WorkspaceDocumentTab, WorkspaceState
from app.services.expert_async_tools import LibraryToolScope, PlannedCall
from app.services.library_workspace_turn import finish_workspace_turn, prepare_workspace_chat
from app.services.sme_open_document import (
    attach_shown_reminder,
    format_created_documents,
    format_open_documents,
    format_relation_maps,
    format_workspace_documents,
    publish_speaker_tools,
    workspace_tool_delivery_key,
    load_open_workspace,
    publish_document_open,
    with_open_document,
)
from app.services.workspace_agent_deployment import CLIENT_TOOLS, SERVER_TOOLS
from app.services.workspace_document_context import (
    created_document_read,
    present_document_call,
    voice_document_context,
)
from app.services.workspace_turn_state import collect_passage_marks
from app.services.document_navigation import exact_workspace_search
from app.services.workspace.service import add_source, create_workspace

AGREEMENT = "Uppsägningstiden är sex månader."


def test_a_document_body_is_not_copied_onto_the_user_turn():
    note = format_workspace_documents({
        "created_documents": [{
            "title": "Förhandlingspunkter",
            "artifact_id": "draft",
            "shown": True,
            "text": "Kontrollkoden är BRUN-LISTA-19.",
        }],
        "open_documents": [{
            "filename": "Avtal_22.pdf",
            "source_id": "src",
            "knowledge_status": "ready",
            "text": "Avtal 22 text",
        }],
    })
    assert attach_shown_reminder("Titta igen.", note) == "Titta igen."
    assert "BRUN-LISTA-19" not in note
    assert "Avtal 22 text" not in note
    assert "(artifact_id draft)" in note
    assert "(source_id src)" in note
    assert attach_shown_reminder("Titta igen.", "ingen vy") == "Titta igen."
    map_note = format_workspace_documents({
        "relation_maps": [{
            "title": "Relationskartan",
            "artifact_id": "map",
            "shown": True,
            "text": "Noder:\n- Hyresstart (händelse)",
        }],
    })
    reminded_map = attach_shown_reminder("Vad hänger ihop?", map_note)
    assert "Hyresstart" not in reminded_map
    assert "Relationskartan" in reminded_map
    assert reminded_map.endswith("Vad hänger ihop?")


def test_saved_marks_stay_out_of_the_turn_note():
    user = UserAccount(
        id="user-one", email="erik@example.test", first_name="Erik", last_name="Fremred", role="user",
    )
    state = WorkspaceState(selection={
        "source_id": "src",
        "anchor": {"exact_text": "Priset är 50", "locator": "document", "page_number": 2},
    })
    references = [type("Reference", (), {
        "id": "ref-karin",
        "source_id": "src",
        "snapshot": {"marked_by": {"kind": "expert", "id": "karin", "name": "Karin"}},
        "anchor": {"page_number": 1, "exact_text": AGREEMENT},
    })()]
    marks = collect_passage_marks(references, state, user)
    assert {mark["name"] for mark in marks} == {"Erik Fremred", "Karin"}
    note = format_workspace_documents({"passage_marks": marks})
    assert AGREEMENT not in note
    assert "Priset är 50" not in note
    assert "Markeringar i dokumenten" not in note


@pytest.mark.asyncio
async def test_marks_on_a_closed_document_stay_out_of_the_note(open_agreement):
    factory, ids = open_agreement
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, ids[1])
        state = WorkspaceState.model_validate(workspace.state)
        state.documents = []
        workspace.state = state.model_dump()
        session.add(WorkspaceReference(
            id="mark-one",
            workspace_id=ids[1],
            number=1,
            identity_key="mark-one",
            kind="underlag",
            source_id="source-one",
            source_version="abc",
            anchor={"page_number": 1, "exact_text": AGREEMENT, "locator": "document"},
            snapshot={"marked_by": {"kind": "expert", "id": "anton", "name": "Anton Hansson"}},
        ))
        await session.commit()
    opened = await load_open_workspace(
        factory, workspace_id=ids[1], user_id=ids[0], customer_id=1,
    )
    await another_client(factory)
    assert opened is not None
    _state, note = opened
    assert "Anton Hansson" not in note
    assert AGREEMENT not in note
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, ids[1])
        workspace.state = WorkspaceState(
            documents=[WorkspaceDocumentTab(source_id="source-one")],
        ).model_dump()
        await session.commit()
    opened = await load_open_workspace(
        factory, workspace_id=ids[1], user_id=ids[0], customer_id=1,
    )
    assert opened is not None
    _state, note = opened
    assert "Avtal.pdf (source_id source-one)" in note
    assert "Anton Hansson" not in note
    assert AGREEMENT not in note


def test_each_expert_passage_is_delivered_on_the_same_document():
    first = workspace_tool_delivery_key("focus_anchor", {"source_id": "avtal", "quote": "Priset är 50"}, "karin")
    second = workspace_tool_delivery_key("focus_anchor", {"source_id": "avtal", "quote": "Uppsägning sex månader"}, "karin")
    other = workspace_tool_delivery_key("focus_anchor", {"source_id": "avtal", "quote": "Priset är 50"}, "alfons")
    opened = workspace_tool_delivery_key("show_document", {"source_id": "avtal"}, "karin")
    opened_again = workspace_tool_delivery_key("show_document", {"source_id": "avtal"}, "alfons")
    noted = workspace_tool_delivery_key("focus_anchor", {"source_id": "avtal", "quote": "Priset är 50", "comment": "Otydligt"}, "karin")
    assert len({first, second, other, noted}) == 4
    assert opened == opened_again


def test_document_set_state_and_context_name_each_result():
    state = WorkspaceState(
        view="document_set",
        document_sets=[WorkspaceDocumentSet(
            id="leases",
            title="Hyresavtal under 2004",
            source_ids=["first", "second"],
        )],
        active_document_set_id="leases",
    )
    note = format_workspace_documents({
        "shown_document_set": {
            "title": state.document_sets[0].title,
            "documents": [
                {"source_id": "first", "filename": "Hyresavtal 2001.pdf"},
                {"source_id": "second", "filename": "Hyresavtal 2003.docx"},
            ],
        },
    })
    assert "Dokumentsamlingen som visas i vyn just nu är Hyresavtal under 2004" in note
    assert "Hyresavtal 2001.pdf (source_id first)" in note
    first = workspace_tool_delivery_key(
        "show_document_set",
        {"title": state.document_sets[0].title, "source_ids": state.document_sets[0].source_ids},
    )
    second = workspace_tool_delivery_key(
        "show_document_set",
        {"title": "Andra avtal", "source_ids": ["third"]},
    )
    assert first != second


@pytest.mark.asyncio
async def test_panel_sends_every_speakers_passages(monkeypatch):
    published = []

    async def publish(_customer_id, _panel_id, event):
        published.append(event)

    monkeypatch.setattr("app.services.sme_open_document.library_chat_broadcast.publish", publish)
    sent: set[tuple[str, ...]] = set()
    calls = [
        {"name": "show_document", "arguments": {"source_id": "avtal"}},
        {"name": "focus_anchor", "arguments": {"source_id": "avtal", "quote": "Priset är 50"}},
        {"name": "focus_anchor", "arguments": {"source_id": "avtal", "quote": "Uppsägning sex månader"}},
    ]
    await publish_speaker_tools(
        customer_id=1, user_id="user", panel_id=4, calls=calls, sent=sent, expert_id="karin",
    )
    await publish_speaker_tools(
        customer_id=1, user_id="user", panel_id=4,
        calls=[{"name": "focus_anchor", "arguments": {"source_id": "avtal", "quote": "Priset är 50"}},
               {"name": "show_document", "arguments": {"source_id": "avtal"}}],
        sent=sent, expert_id="alfons",
    )
    marks = [event for event in published if event["name"] == "focus_anchor"]
    assert [event["arguments"]["expert_id"] for event in marks] == ["karin", "karin", "alfons"]
    assert [event["arguments"]["quote"] for event in marks] == [
        "Priset är 50", "Uppsägning sex månader", "Priset är 50",
    ]
    assert [event["name"] for event in published].count("show_document") == 1


def test_open_tabs_are_named_by_id_without_document_text():
    note = format_open_documents([{
        "filename": "Avtal.pdf",
        "source_id": "src",
        "knowledge_status": "ready",
        "text": AGREEMENT,
    }])
    assert "Avtal.pdf (source_id src)" in note
    assert AGREEMENT not in note
    assert "Dokumenttexten ingår inte" in note
    assert with_open_document("Du sitter i panelen.", note).startswith("Du sitter i panelen.")
    assert with_open_document("Du sitter i panelen.", "") == "Du sitter i panelen."
    created = format_created_documents([{
        "title": "Förhandlingspunkter",
        "artifact_id": "draft",
        "shown": True,
        "text": "8 600 kr i månaden",
    }])
    assert "Förhandlingspunkter (artifact_id draft)" in created
    assert "8 600 kr i månaden" not in created
    assert "Dokumenttexten ingår inte" in created
    assert format_created_documents([]) == ""
    relations = format_relation_maps([{
        "title": "Relationskartan",
        "artifact_id": "map",
        "shown": True,
        "text": "Noder:\n- Hyresstart (händelse)\n\nKanter:\n- Hyresstart → Index: årlig höjning (källbelagd)",
    }])
    assert "vyn just nu är Relationskartan" in relations
    assert "artifact_id map" in relations
    assert "Hyresstart" not in relations
    assert "årlig höjning" not in relations
    assert "Kartans noder och kanter ingår inte" in relations
    assert format_relation_maps([]) == ""


@pytest.fixture
async def open_agreement(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/agreement.db",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.3,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=1, name="Customer", slug="agreement-test", available_modules=["dd"]))
        await session.flush()
        user = UserAccount(id="user-one", email="user@example.test", role="user", kund_id=1)
        session.add(user)
        await session.flush()
        workspace = await create_workspace(session, user, title="Avtal", module="dd")
        source = StoredObject(
            id="source-one",
            workspace_id=workspace.workspace_id,
            customer_id=1,
            owner_user_id=user.id,
            module="dd",
            kind="underlag",
            bucket="agreement-test",
            object_key="avtal.pdf",
            filename="Avtal.pdf",
            content_type="application/pdf",
            size_bytes=len(AGREEMENT),
            extraction_status="ok",
            extracted_text=AGREEMENT,
            knowledge_status="ready",
        )
        session.add(source)
        await session.flush()
        await add_source(session, workspace, source.id)
        workspace.state = WorkspaceState(
            documents=[WorkspaceDocumentTab(source_id=source.id)],
        ).model_dump()
        await session.commit()
        ids = user.id, workspace.id
    yield factory, ids
    await engine.dispose()


async def another_client(factory):
    async with factory() as other:
        assert await asyncio.wait_for(other.scalar(text("SELECT 1")), timeout=1) == 1


@pytest.mark.asyncio
async def test_the_open_agreement_is_read_without_holding_the_connection(open_agreement):
    factory, ids = open_agreement
    opened = await load_open_workspace(
        factory,
        workspace_id=ids[1],
        user_id=ids[0],
        customer_id=1,
        expert_id="expert-one",
    )
    await another_client(factory)
    assert opened is not None
    state, note = opened
    assert state.expert_id == "expert-one"
    assert state.documents[0].source_id == "source-one"
    assert "Avtal.pdf (source_id source-one)" in note
    assert AGREEMENT not in note


@pytest.mark.asyncio
async def test_the_created_document_on_screen_is_in_the_note(open_agreement):
    factory, ids = open_agreement
    async with factory() as session:
        session.add(WorkspaceArtifact(
            id="draft-points", workspace_id=ids[1], kind="document", title="Förhandlingspunkter",
            status="ready", revision=1, content={"blocks": [{"text": "8 600 kr i månaden"}]},
        ))
        workspace = await session.get(VoiceWorkspace, ids[1])
        state = WorkspaceState.model_validate(workspace.state)
        state.active_artifact_id = "draft-points"
        workspace.state = state.model_dump()
        await session.commit()
    opened = await load_open_workspace(
        factory, workspace_id=ids[1], user_id=ids[0], customer_id=1,
    )
    await another_client(factory)
    assert opened is not None
    _state, note = opened
    assert "Förhandlingspunkter (artifact_id draft-points)" in note
    assert "8 600 kr i månaden" not in note
    assert "Avtal.pdf (source_id source-one)" in note
    assert AGREEMENT not in note


@pytest.mark.asyncio
async def test_a_mentioned_created_document_is_in_the_same_note(open_agreement):
    factory, ids = open_agreement
    async with factory() as session:
        session.add(WorkspaceArtifact(
            id="draft-points", workspace_id=ids[1], kind="document", title="Förhandlingspunkter",
            status="ready", revision=1, content={"blocks": [{"text": "8 600 kr i månaden"}]},
        ))
        await session.commit()
    opened = await load_open_workspace(
        factory,
        workspace_id=ids[1],
        user_id=ids[0],
        customer_id=1,
        mentions=[DocumentMention(display_name="Förhandlingspunkter", source_object_id="draft-points")],
    )
    await another_client(factory)
    assert opened is not None
    state, note = opened
    assert state.document_mentions[0].source_object_id == "draft-points"
    assert "8 600 kr i månaden" not in note
    assert "draft-points" not in note
    assert "finns i arbetsytan" not in note


@pytest.mark.asyncio
async def test_a_single_expert_reads_the_created_document_on_screen(open_agreement):
    factory, ids = open_agreement
    async with factory() as session:
        session.add(WorkspaceArtifact(
            id="draft-points", workspace_id=ids[1], kind="document", title="Förhandlingspunkter",
            status="ready", revision=1, content={"blocks": [{"text": "8 600 kr i månaden"}]},
        ))
        await session.flush()
        state = WorkspaceState(
            documents=[WorkspaceDocumentTab(source_id="source-one")],
            active_artifact_id="draft-points",
        )
        turn, _tools, _stored = await prepare_workspace_chat(
            session,
            prompts={
                "workspace.chat.turn": "Läge:\n{workspace_json}",
                "workspace.voice.tool.start_research": "Starta research.",
            },
            workspace_id=ids[1],
            workspace_state=state,
            actor_user_id=ids[0],
            tool_names=[*SERVER_TOOLS, *CLIENT_TOOLS],
        )
        await session.rollback()
    await another_client(factory)
    assert "Förhandlingspunkter (artifact_id draft-points)" in turn
    assert "8 600 kr i månaden" not in turn
    assert "Avtal.pdf (source_id source-one)" in turn
    assert AGREEMENT not in turn


@pytest.mark.asyncio
async def test_asking_to_open_the_agreement_publishes_one_document(open_agreement, monkeypatch):
    factory, ids = open_agreement
    published: list[tuple] = []

    async def publish(customer_id, persona_id, event):
        published.append((customer_id, persona_id, event))
        await another_client(factory)

    monkeypatch.setattr(
        "app.services.sme_open_document.library_chat_broadcast.publish",
        publish,
    )
    source_id = await publish_document_open(
        factory,
        customer_id=1,
        user_id=ids[0],
        panel_id=3,
        workspace_id=ids[1],
        message="Öppna avtalet",
        history=[],
    )
    assert source_id == "source-one"
    assert published[0][2]["name"] == "show_document"
    assert published[0][2]["arguments"] == {"source_id": "source-one"}
    assert published[0][2]["thread_id"] == "3"
    missed = await publish_document_open(
        factory,
        customer_id=1,
        user_id=ids[0],
        panel_id=3,
        workspace_id=ids[1],
        message="Vad gäller uppsägningstiden?",
        history=[],
    )
    assert missed is None
    assert len(published) == 1


@pytest.mark.asyncio
async def test_a_foreign_workspace_is_refused_and_the_connection_is_released(open_agreement):
    factory, ids = open_agreement
    with pytest.raises(RuntimeError, match="voice_workspace_access_lost"):
        await load_open_workspace(
            factory,
            workspace_id=ids[1],
            user_id="someone-else",
            customer_id=1,
        )
    await another_client(factory)


@pytest.mark.asyncio
async def test_a_created_document_opens_once_and_the_read_releases_the_connection(open_agreement, monkeypatch):
    factory, ids = open_agreement
    async with factory() as session:
        session.add(WorkspaceArtifact(
            id="draft-points", workspace_id=ids[1], kind="document", title="Förhandlingspunkter",
            status="ready", revision=1, content={"blocks": []},
        ))
        await session.commit()
    published: list[dict] = []

    async def publish(_customer_id, _persona_id, event):
        published.append(event)
        await another_client(factory)

    monkeypatch.setattr("app.services.sme_open_document.library_chat_broadcast.publish", publish)
    opened = await publish_document_open(
        factory, customer_id=1, user_id=ids[0], panel_id=3, workspace_id=ids[1],
        message="Öppna förhandlingspunkter", history=[],
    )
    assert opened == "draft-points"
    assert published[0]["name"] == "show_artifact"
    assert published[0]["arguments"] == {"artifact_id": "draft-points"}


@pytest.mark.asyncio
async def test_the_workspace_hears_the_open_after_the_read_is_released(open_agreement):
    factory, ids = open_agreement
    scope = LibraryToolScope(
        enabled=True, persona_id="expert", mode="character", actor_user_id=ids[0],
        history=[], user_message="Öppna avtalet",
    )
    scope.client_calls.append(PlannedCall("draft", "show_artifact", {"artifact_id": "draft-points"}))
    emitted: list[list[dict]] = []

    async def emit(calls):
        await another_client(factory)
        emitted.append(calls)

    async with factory() as session:
        await finish_workspace_turn(
            session, scope, emit, workspace_id=ids[1], actor_user_id=ids[0],
            message="Öppna avtalet", history=[],
        )
    names = [call["name"] for call in emitted[0]]
    assert names == ["show_artifact", "show_document"]


def test_a_created_document_is_read_and_opened_like_any_document():
    artifact = WorkspaceArtifact(
        id="draft", workspace_id="workspace", kind="document", title="Förhandlingspunkter",
        status="ready", revision=1, content={"blocks": [{"text": "8 600 kr i månaden"}]},
    )
    read = created_document_read(artifact, None)
    assert read["source_id"] == "draft"
    assert read["text"] == "8 600 kr i månaden"
    assert read["ingest_status"] == "ready"
    opened = present_document_call("show_document", {"source_id": "draft"}, {"draft"})
    assert opened == ("show_artifact", {"artifact_id": "draft"})
    kept = present_document_call("show_document", {"source_id": "file"}, {"draft"})
    assert kept == ("show_document", {"source_id": "file"})


def test_document_set_tokens_resolve_filename_fragments():
    from app.services.workspace_document_context import (
        document_set_source_tokens,
        present_document_call,
        resolve_document_set_source_ids,
    )

    assert document_set_source_tokens({"source_ids": [17, 18, "19"]}) == ["17", "18", "19"]
    inventory = [
        {"source_object_id": "id-17", "filename": "Hyresavtal_17.pdf"},
        {"source_object_id": "id-18", "filename": "Hyresavtal_18.pdf"},
        {"source_object_id": "id-170", "filename": "Hyresavtal_170.pdf"},
    ]
    assert resolve_document_set_source_ids(["17", "18"], inventory) == ["id-17", "id-18"]
    name, arguments = present_document_call(
        "show_document_set",
        {"title": "Hyresavtal", "source_ids": [17, 18]},
        set(),
        inventory=inventory,
    )
    assert name == "show_document_set"
    assert arguments["source_ids"] == ["id-17", "id-18"]


@pytest.mark.asyncio
async def test_the_created_document_is_in_the_same_inventory(open_agreement):
    factory, ids = open_agreement
    async with factory() as session:
        session.add(WorkspaceArtifact(
            id="draft-points", workspace_id=ids[1], kind="document", title="Förhandlingspunkter",
            status="ready", revision=1, content={"blocks": [{"text": "8 600 kr i månaden"}]},
        ))
        await session.flush()
        workspace = await session.get(VoiceWorkspace, ids[1])
        user = await session.get(UserAccount, ids[0])
        documents = await voice_document_context(session, workspace, user)
        found = await exact_workspace_search(
            session, workspace, "8 600", limit=5, source_id="draft-points",
        )
        await session.rollback()
    await another_client(factory)
    row = next(item for item in documents["available_documents"] if item["filename"] == "Förhandlingspunkter")
    assert row["source_object_id"] == "draft-points"
    assert row["knowledge_status"] == "ready"
    assert any(item["filename"] == "Avtal.pdf" for item in documents["available_documents"])
    assert found["items"][0]["title"] == "Förhandlingspunkter"
    assert "8 600" in found["items"][0]["excerpt"]


@pytest.mark.asyncio
async def test_show_document_on_a_created_document_opens_the_draft(open_agreement):
    factory, ids = open_agreement
    async with factory() as session:
        session.add(WorkspaceArtifact(
            id="draft-points", workspace_id=ids[1], kind="document", title="Förhandlingspunkter",
            status="ready", revision=1, content={"blocks": [{"text": "8 600 kr i månaden"}]},
        ))
        await session.commit()
    scope = LibraryToolScope(
        enabled=True, persona_id="expert", mode="character", actor_user_id=ids[0],
        history=[], user_message="Läs förhandlingspunkterna",
    )
    scope.client_calls.append(PlannedCall("draft", "show_document", {"source_id": "draft-points"}))
    emitted: list[list[dict]] = []

    async def emit(calls):
        await another_client(factory)
        emitted.append(calls)

    async with factory() as session:
        await finish_workspace_turn(
            session, scope, emit, workspace_id=ids[1], actor_user_id=ids[0],
            message="Läs förhandlingspunkterna", history=[],
        )
    assert emitted[0] == [{"name": "show_artifact", "arguments": {"artifact_id": "draft-points"}}]


MAP = {
    "nodes": [
        {"id": "start", "label": "Hyresstart", "kind": "event", "source_refs": ["ref-1"]},
        {"id": "index", "label": "Index", "kind": "condition", "source_refs": ["ref-1"]},
    ],
    "edges": [{
        "id": "rise",
        "source": "start",
        "target": "index",
        "label": "årlig höjning",
        "interpretation": False,
        "source_refs": ["ref-1"],
    }],
}


@pytest.mark.asyncio
async def test_the_relation_map_on_screen_is_in_the_note(open_agreement):
    factory, ids = open_agreement
    async with factory() as session:
        session.add(WorkspaceArtifact(
            id="map-rent", workspace_id=ids[1], kind="relations", title="Relationskartan",
            status="ready", revision=1, content=MAP,
        ))
        workspace = await session.get(VoiceWorkspace, ids[1])
        state = WorkspaceState.model_validate(workspace.state)
        state.active_artifact_id = "map-rent"
        workspace.state = state.model_dump()
        await session.commit()
    opened = await load_open_workspace(
        factory, workspace_id=ids[1], user_id=ids[0], customer_id=1,
    )
    await another_client(factory)
    assert opened is not None
    _state, note = opened
    assert "vyn just nu är Relationskartan" in note
    assert "artifact_id map-rent" in note
    assert "Hyresstart" not in note
    assert "Avtal.pdf (source_id source-one)" in note
    assert AGREEMENT not in note


@pytest.mark.asyncio
async def test_a_single_expert_reads_the_relation_map_on_screen(open_agreement):
    factory, ids = open_agreement
    async with factory() as session:
        session.add(WorkspaceArtifact(
            id="map-rent", workspace_id=ids[1], kind="relations", title="Relationskartan",
            status="ready", revision=1, content=MAP,
        ))
        await session.flush()
        state = WorkspaceState(
            documents=[WorkspaceDocumentTab(source_id="source-one")],
            active_artifact_id="map-rent",
        )
        turn, _tools, _stored = await prepare_workspace_chat(
            session,
            prompts={
                "workspace.chat.turn": "Läge:\n{workspace_json}",
                "workspace.voice.tool.start_research": "Starta research.",
            },
            workspace_id=ids[1],
            workspace_state=state,
            actor_user_id=ids[0],
            tool_names=[*SERVER_TOOLS, *CLIENT_TOOLS],
        )
        await session.rollback()
    await another_client(factory)
    assert "Relationskartan" in turn
    assert "Hyresstart" not in turn
    assert "årlig höjning" not in turn
    assert "Avtal.pdf (source_id source-one)" in turn
    assert AGREEMENT not in turn


@pytest.mark.asyncio
async def test_asking_to_open_the_relation_map_publishes_it(open_agreement, monkeypatch):
    factory, ids = open_agreement
    async with factory() as session:
        session.add(WorkspaceArtifact(
            id="map-rent", workspace_id=ids[1], kind="relations", title="Relationskartan",
            status="ready", revision=1, content=MAP,
        ))
        await session.commit()
    published: list[dict] = []

    async def publish(_customer_id, _persona_id, event):
        published.append(event)
        await another_client(factory)

    monkeypatch.setattr("app.services.sme_open_document.library_chat_broadcast.publish", publish)
    opened = await publish_document_open(
        factory, customer_id=1, user_id=ids[0], panel_id=3, workspace_id=ids[1],
        message="Öppna relationskartan", history=[],
    )
    assert opened == "map-rent"
    assert published[0]["name"] == "show_artifact"
    assert published[0]["arguments"] == {"artifact_id": "map-rent"}
