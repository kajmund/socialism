"""Saved marks stay out of the expert turn until a tool is asked for them."""

import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund, StoredObject, UserAccount
from app.database.workspace_models import (
    VoiceWorkspace,
    WorkspaceArtifact,
    WorkspacePassageComment,
    WorkspaceReference,
)
from app.llm.chat import _chat_messages, build_chat_system_prompt
from app.schemas.domain import EditablePersona
from app.schemas.workspace import WorkspaceDocumentTab, WorkspaceState
from app.services.document_tool_retrieval import state_filtered_specs
from app.services.library_workspace_turn import prepare_workspace_chat
from app.services.prompt_catalog import default_prompts
from app.services.workspace.service import add_source, create_workspace
from app.services.workspace_agent_deployment import CLIENT_TOOLS, SERVER_TOOLS
from app.services.workspace.tools import execute_workspace_tool
from app.services.workspace_turn_state import compact_selection, turn_payload

MARKS = 24
ANTON = "ANTON-MARKERING"
KARIN = "KARIN-MARKERING"
OLDER = "ALDRE-AVTAL-UPPSAGNING"
ANTON_NOTE = "ANTON-KOMMENTAR"
KARIN_NOTE = "KARIN-KOMMENTAR"
_PROMPTS = default_prompts("sv")


def _frida() -> EditablePersona:
    return EditablePersona(
        name="Frida Rosmarie",
        yrke="Python",
        beskrivning="Glad, social och humoristisk.",
    )


def _spec(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {}}}


def test_frida_keeps_her_identity_when_the_turn_has_no_documents():
    prompt = build_chat_system_prompt(
        _frida(), "character", prompts=_PROMPTS, profile_kind="expert",
    )
    assert "Frida Rosmarie" in prompt
    assert "Personlighet styr tonen, inte förmågan" in prompt
    assert "verktyg" in prompt


def test_a_follow_up_reuses_the_previous_answer():
    messages = _chat_messages(
        _frida(),
        "character",
        [
            ("user", "Vad innebär uppsägningstiden?"),
            ("assistant", "Avtalet har tre månaders uppsägningstid."),
        ],
        "Är det rimligt?",
        prompts=_PROMPTS,
        extra_system='{"documents":[{"id":"doc","title":"Hyresavtal.pdf"}]}',
        profile_kind="expert",
    )
    assert messages[0]["content"].startswith("[ROLL]\nLäge: IN-CHARACTER")
    assert "Hyresavtal.pdf" not in messages[0]["content"]
    assert messages[1]["role"] == "system"
    assert "Hyresavtal.pdf" in messages[1]["content"]
    assert any("tre månaders uppsägningstid" in message["content"] for message in messages)


def test_compact_state_tracks_the_open_document_and_drops_it_when_closed():
    open_state = WorkspaceState(
        view="documents",
        active_source_id="lease",
        documents=[WorkspaceDocumentTab(source_id="lease", page=2)],
    )
    closed = open_state.model_copy(update={"documents": [], "active_source_id": None})
    opened = turn_payload(open_state)
    assert opened["active_source_id"] == "lease"
    assert opened["documents"] == [{"id": "lease", "title": None, "page": 2}]
    assert opened["selection"] is None
    assert turn_payload(closed)["documents"] == []
    assert "exact_text" not in json.dumps(opened)


def test_a_short_selection_is_named_and_a_long_one_is_only_metadata():
    short = WorkspaceState(selection={
        "source_id": "lease",
        "reference_id": "selection-1",
        "anchor": {"exact_text": "Priset är 50", "page_number": 2},
    })
    payload = turn_payload(short)
    assert payload["selection"]["source_id"] == "lease"
    assert payload["selection"]["selection_id"] == "selection-1"
    assert payload["selection"]["page"] == 2
    assert payload["selection"]["text"] == "Priset är 50"
    long_text = "klausul " * 90
    selection = compact_selection(
        {"source_id": "lease", "anchor": {"exact_text": long_text, "page_number": 4}},
        text_mode="short",
    )
    assert selection is not None
    assert selection["has_text"] is True
    assert "text" not in selection
    fetched = compact_selection(
        {"source_id": "lease", "anchor": {"exact_text": long_text, "page_number": 4}},
        text_mode="full",
    )
    assert fetched is not None
    assert fetched["text"].startswith("klausul")


def test_no_open_document_still_leaves_search_available():
    specs = [_spec(name) for name in ("search_knowledge", "find_documents", "read_source")]
    names = [spec["function"]["name"] for spec in state_filtered_specs(specs, {"documents": []})]
    assert names == ["search_knowledge", "find_documents"]


@pytest.fixture
async def marked_workspace(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/marks.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=1, name="Customer", slug="marks", available_modules=["dd"]))
        await session.flush()
        user = UserAccount(
            id="user-one", email="user@example.test", role="user", kund_id=1,
            first_name="Erik", last_name="Fremred",
        )
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
            bucket="marks",
            object_key="avtal.pdf",
            filename="Avtal.pdf",
            content_type="application/pdf",
            size_bytes=12,
            extraction_status="ok",
            extracted_text="Avtalstext.",
            knowledge_status="ready",
        )
        session.add(source)
        await session.flush()
        await add_source(session, workspace, source.id)
        session.add(WorkspaceReference(
            id="mark-anton",
            workspace_id=workspace.id,
            number=1,
            identity_key="mark-anton",
            kind="underlag",
            source_id="source-one",
            source_version="a" * 64,
            anchor={"page_number": 1, "exact_text": ANTON, "locator": "document"},
            snapshot={"marked_by": {"kind": "expert", "id": "anton", "name": "Anton Hansson"}},
        ))
        for number in range(2, MARKS):
            session.add(WorkspaceReference(
                id=f"mark-{number}",
                workspace_id=workspace.id,
                number=number,
                identity_key=f"mark-{number}",
                kind="underlag",
                source_id="source-one",
                source_version="a" * 64,
                anchor={"page_number": 1, "exact_text": f"{KARIN}-{number}", "locator": "document"},
                snapshot={"marked_by": {"kind": "expert", "id": "karin", "name": "Karin Ek"}},
            ))
        session.add(WorkspaceReference(
            id="mark-older",
            workspace_id=workspace.id,
            number=MARKS,
            identity_key="mark-older",
            kind="underlag",
            source_id="older-lease",
            source_version="b" * 64,
            anchor={"page_number": 3, "exact_text": OLDER, "locator": "document"},
            snapshot={"marked_by": {"kind": "expert", "id": "beata", "name": "Beata Holm"}},
        ))
        session.add(WorkspacePassageComment(
            id="comment-anton",
            workspace_id=workspace.id,
            source_id="source-one",
            passage_key="anton",
            anchor={"page_number": 1},
            author_kind="expert",
            expert_id="anton",
            author_name="Anton Hansson",
            body=ANTON_NOTE,
        ))
        session.add(WorkspacePassageComment(
            id="comment-karin",
            workspace_id=workspace.id,
            source_id="source-one",
            passage_key="karin",
            anchor={"page_number": 1},
            author_kind="expert",
            expert_id="karin",
            author_name="Karin Ek",
            body=KARIN_NOTE,
        ))
        workspace.state = WorkspaceState(documents=[]).model_dump()
        await session.commit()
        ids = user.id, workspace.id
    yield factory, ids
    await engine.dispose()


async def _turn(factory, ids, state: WorkspaceState) -> str:
    async with factory() as session:
        context, _tools, _stored = await prepare_workspace_chat(
            session,
            prompts={
                "workspace.chat.turn": _PROMPTS["workspace.chat.turn"],
                "workspace.voice.tool.start_research": "Starta research.",
            },
            workspace_id=ids[1],
            workspace_state=state,
            actor_user_id=ids[0],
            tool_names=[*SERVER_TOOLS, *CLIENT_TOOLS],
        )
        await session.rollback()
    return context


async def _context(factory, ids, arguments: dict) -> dict:
    async with factory() as session:
        user = await session.get(UserAccount, ids[0])
        assert user is not None
        result = await execute_workspace_tool(
            session,
            workspace_id=ids[1],
            user=user,
            tool_name="get_workspace_context",
            arguments=arguments,
            idempotency_key=json.dumps(arguments, sort_keys=True),
        )
        await session.commit()
    return result


@pytest.mark.asyncio
async def test_goddag_leaves_saved_marks_out_of_the_prompt(marked_workspace):
    factory, ids = marked_workspace
    closed = await _turn(factory, ids, WorkspaceState(documents=[]))
    open_tabs = WorkspaceState(
        view="documents",
        active_source_id="source-one",
        documents=[WorkspaceDocumentTab(source_id=f"tab-{number}") for number in range(10)],
    )
    opened = await _turn(factory, ids, open_tabs)
    for context in (closed, opened):
        assert ANTON not in context
        assert KARIN not in context
        assert OLDER not in context
        assert ANTON_NOTE not in context
        assert "Frida" not in context
    assert "tab-9" in opened
    assert "Avtal.pdf" not in closed


@pytest.mark.asyncio
async def test_marks_are_fetched_only_for_the_asked_expert_or_source(marked_workspace):
    factory, ids = marked_workspace
    empty = await _context(factory, ids, {})
    dumped = json.dumps(empty, ensure_ascii=False)
    assert ANTON not in dumped
    assert KARIN not in dumped
    assert OLDER not in dumped
    assert "passage_marks" not in empty["workspace"]
    assert empty["workspace"]["state"]["knowledge_scope"] == "workspace"

    anton = await _context(factory, ids, {"expert_ids": ["Anton"], "limit": 50})
    marks = anton["workspace"]["passage_marks"]
    assert marks
    assert {mark["name"] for mark in marks} == {"Anton Hansson"}
    assert ANTON in json.dumps(marks)
    assert KARIN not in json.dumps(anton["workspace"]["passage_marks"])
    assert anton["workspace"]["passage_comments"][0]["body"] == ANTON_NOTE
    assert KARIN_NOTE not in json.dumps(anton["workspace"]["passage_comments"])

    everyone = await _context(factory, ids, {"source_ids": ["source-one"]})
    names = {mark["name"] for mark in everyone["workspace"]["passage_marks"]}
    assert names == {"Anton Hansson", "Karin Ek"}
    assert everyone["workspace"]["passage_marks_total"] >= 20

    older = await _context(factory, ids, {"source_ids": ["older-lease"]})
    assert [mark["exact_text"] for mark in older["workspace"]["passage_marks"]] == [OLDER]


@pytest.mark.asyncio
async def test_relation_text_is_fetched_only_when_asked(marked_workspace):
    factory, ids = marked_workspace
    async with factory() as session:
        session.add(WorkspaceArtifact(
            id="map-rent",
            workspace_id=ids[1],
            kind="relations",
            title="Relationskartan",
            status="ready",
            revision=1,
            content={"nodes": [{"id": "start", "label": "Hyresstart", "kind": "event"}], "edges": []},
        ))
        workspace = await session.get(VoiceWorkspace, ids[1])
        assert workspace is not None
        workspace.state = WorkspaceState(active_artifact_id="map-rent").model_dump()
        await session.commit()
    hidden = await _context(factory, ids, {})
    assert "Hyresstart" not in json.dumps(hidden)
    shown = await _context(factory, ids, {"include_relations": True})
    assert "Hyresstart" in json.dumps(shown["workspace"]["relations"])
