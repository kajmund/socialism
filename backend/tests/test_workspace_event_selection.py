"""Question-time PDF proof is atomic, immutable and releases the DB pool."""

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass, replace
from hashlib import sha256
from threading import Event

import pytest
from sqlalchemy import delete, func, select, text

from app.database.models import PersonaMessage, StoredObject
from app.database.workspace_conversations import WorkspaceConversationEvent, WorkspaceConversationSession
from app.database.workspace_models import VoiceWorkspace, WorkspaceOperation, WorkspaceReference, WorkspaceSource
from app.services.workspace import selection_verification
from app.services.workspace.service import add_source
from app.services.workspace.sources import source_version
from tests.test_workspace_conversations import (
    bootstrap,
    provider as provider,
    single_connection_provider as single_connection_provider,
    tool_body,
    tool_url,
)
from tests.test_workspace_pdf_selection import QUOTE, _pdf_inputs, _synthetic_pdf

SOURCE = "synthetic-question-selection"


@dataclass(frozen=True)
class QuestionCase:
    provider: tuple
    engine: object
    connection: dict
    data: bytes
    body: dict
    stored_state: dict
    stored_revision: int
    original_source: dict

    @property
    def url(self):
        return f"/workspace-chat/{self.provider[2]}/sessions/{self.connection['session_id']}/events"


@pytest.fixture
async def question_case(single_connection_provider):
    bound_provider, engine = single_connection_provider
    _client, factory, workspace_id, _expert_id, _requests = bound_provider
    data = _synthetic_pdf()
    flat_text, anchor = _pdf_inputs(data)
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, workspace_id)
        source = StoredObject(id=SOURCE, customer_id=workspace.customer_id, workspace_id=workspace.workspace_id,
            owner_user_id=workspace.owner_user_id, module=workspace.module, kind="underlag",
            bucket="synthetic-question-selection", object_key="columns.pdf", filename="columns.pdf",
            content_type="application/pdf", size_bytes=len(data), extraction_status="ok",
            extracted_text=flat_text, knowledge_status="ready")
        session.add(source)
        await session.flush()
        await add_source(session, workspace, SOURCE)
        workspace.state = {**workspace.state, "view": "documents", "documents": [{"source_id": SOURCE}]}
        await session.commit()
    connection = await bootstrap(bound_provider, "text")
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, workspace_id)
        stored_state, stored_revision = deepcopy(workspace.state), workspace.revision
        version = source_version(await session.get(StoredObject, SOURCE))
        original_source = dict((await session.execute(select(StoredObject.__table__).where(StoredObject.id == SOURCE))).mappings().one())
    state = {**stored_state, "selection": {"source_id": SOURCE, "source_version": version,
        "source_file_sha256": sha256(data).hexdigest(), "anchor": anchor}}
    body = {"event_key": "question-one", "kind": "user", "text": "Explain the selected policy.",
        "context_snapshot": state, "workspace_revision": stored_revision}
    return QuestionCase(bound_provider, engine, connection, data, body, stored_state, stored_revision, original_source)


def storage_probe(case, monkeypatch, *, pending=None, check_pool=True):
    calls = []

    async def get_object(bucket, key):
        if check_pool:
            assert case.engine.pool.checkedout() == 0
        async with case.provider[1]() as reader:
            assert await asyncio.wait_for(reader.scalar(text("SELECT 1")), timeout=1) == 1
        calls.append((bucket, key))
        if pending is not None:
            await pending(len(calls))
        return case.data, "application/pdf"

    original = selection_verification.selected_pdf_quote

    def parse_pdf(data, anchor):
        if check_pool:
            assert case.engine.pool.checkedout() == 0
        return original(data, anchor)

    monkeypatch.setattr(selection_verification, "get_object", get_object)
    monkeypatch.setattr(selection_verification, "selected_pdf_quote", parse_pdf)
    return calls


async def assert_writes(case, *, count):
    async with case.provider[1]() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceReference)) == count
        assert await session.scalar(select(func.count()).select_from(PersonaMessage)) == count
        assert await session.scalar(select(func.count()).select_from(WorkspaceConversationEvent).where(
            WorkspaceConversationEvent.kind == "user")) == count
        assert await session.scalar(select(func.count()).select_from(WorkspaceOperation)) == 0
        workspace = await session.get(VoiceWorkspace, case.provider[2])
        assert workspace.state == case.stored_state
        assert workspace.revision == case.stored_revision


async def test_question_proves_original_and_freezes_tool_context_without_canvas_update(question_case, monkeypatch):
    case = question_case
    calls = storage_probe(case, monkeypatch)
    response = await case.provider[0].post(case.url, json=case.body)
    assert response.status_code == 200, response.text
    state = json.loads(response.json()["context"])["state"]
    reference_id = state["selection"]["reference_id"]
    assert state["selection"]["anchor"]["exact_text"] == QUOTE
    async with case.provider[1]() as session:
        reference = await session.get(WorkspaceReference, reference_id)
        event = await session.scalar(select(WorkspaceConversationEvent).where(WorkspaceConversationEvent.kind == "user"))
        assert reference.snapshot["selection_verified"] is True
        assert reference.source_version == case.body["context_snapshot"]["selection"]["source_version"]
        assert event.payload["workspace_state"] == state
        original_source = dict((await session.execute(select(StoredObject.__table__).where(StoredObject.id == SOURCE))).mappings().one())
        assert original_source == case.original_source
    captured = []

    async def execute(_session, **kwargs):
        captured.append(kwargs["agent_session"].turn_state)
        return {"status": "completed"}

    from app.api import workspace_conversations as api
    monkeypatch.setattr(api, "execute_workspace_tool", execute)
    tool_request = {**tool_body(case.connection), "turn_event_key": case.body["event_key"]}
    result = await case.provider[0].post(tool_url(case.provider, case.connection), json=tool_request)
    assert result.status_code == 200, result.text
    assert captured == [state]
    assert len(calls) == 1
    await assert_writes(case, count=1)


@pytest.mark.parametrize("change", ["quote", "page", "region", "version", "missing_version", "missing_file_hash"])
async def test_invalid_selection_never_creates_question_or_reference(question_case, monkeypatch, change):
    case = question_case
    storage_probe(case, monkeypatch)
    body = deepcopy(case.body)
    selection = body["context_snapshot"]["selection"]
    if change == "quote":
        selection["anchor"]["exact_text"] = "Policy: Customer files stay public. Cite original evidence."
    elif change == "page":
        selection["anchor"].update(page_number=2, locator="page:2")
    elif change == "region":
        selection["anchor"]["rects"] = [{"x": .52, "y": .06, "width": .45, "height": .1}]
    elif change == "version":
        selection["source_version"] = "0" * 64
    elif change == "missing_version":
        selection.pop("source_version")
    else:
        selection.pop("source_file_sha256")
    response = await case.provider[0].post(case.url, json=body)
    assert response.status_code == 409, response.text
    await assert_writes(case, count=0)


@pytest.mark.parametrize("change", ["revocation", "source_text", "source_membership"])
async def test_rechecks_authorization_and_source_after_storage_wait(question_case, monkeypatch, change):
    case = question_case
    entered, released = asyncio.Event(), asyncio.Event()

    async def pending(_count):
        entered.set()
        await released.wait()

    storage_probe(case, monkeypatch, pending=pending)
    task = asyncio.create_task(case.provider[0].post(case.url, json=case.body))
    await asyncio.wait_for(entered.wait(), timeout=2)
    try:
        async with case.provider[1]() as session:
            if change == "revocation":
                (await session.get(WorkspaceConversationSession, case.connection["session_id"])).status = "revoked"
            elif change == "source_text":
                (await session.get(StoredObject, SOURCE)).extracted_text = "A newly ingested source version."
            else:
                await session.execute(delete(WorkspaceSource).where(WorkspaceSource.workspace_id == case.provider[2],
                    WorkspaceSource.source_id == SOURCE))
            await session.commit()
    finally:
        released.set()
    response = await asyncio.wait_for(task, timeout=3)
    assert response.status_code in {401, 404, 409}, response.text
    await assert_writes(case, count=0)


async def test_redelivery_uses_winning_frozen_context_without_reading_changed_source(question_case, monkeypatch):
    case = question_case
    calls = storage_probe(case, monkeypatch)
    first = await case.provider[0].post(case.url, json=case.body)
    assert first.status_code == 200, first.text
    async with case.provider[1]() as session:
        (await session.get(StoredObject, SOURCE)).extracted_text = "Changed after the question was saved."
        await session.commit()
    later = deepcopy(case.body)
    later["context_snapshot"]["selection"]["anchor"]["exact_text"] = "Later unrelated selection."
    replay = await case.provider[0].post(case.url, json=later)
    assert replay.status_code == 200, replay.text
    assert replay.json()["duplicate"] is True
    assert replay.json()["context"] == first.json()["context"]
    assert len(calls) == 1
    await assert_writes(case, count=1)


async def test_duplicate_arriving_during_proof_does_not_save_a_losing_reference(question_case, monkeypatch):
    case = question_case
    entered, released = asyncio.Event(), asyncio.Event()

    async def pending(count):
        if count == 1:
            entered.set()
            await released.wait()

    calls = storage_probe(case, monkeypatch, pending=pending, check_pool=False)
    delayed_body = deepcopy(case.body)
    anchor = delayed_body["context_snapshot"]["selection"]["anchor"]
    anchor.update(exact_text="Policy:", rects=[anchor["rects"][0]])
    delayed = asyncio.create_task(case.provider[0].post(case.url, json=delayed_body))
    await asyncio.wait_for(entered.wait(), timeout=2)
    try:
        winner = await case.provider[0].post(case.url, json=case.body)
        assert winner.status_code == 200, winner.text
    finally:
        released.set()
    replay = await asyncio.wait_for(delayed, timeout=3)
    assert replay.status_code == 200, replay.text
    assert replay.json()["duplicate"] is True
    assert replay.json()["context"] == winner.json()["context"]
    assert len(calls) == 2
    await assert_writes(case, count=1)


async def test_simultaneous_proofs_save_exactly_one_question_and_reference(question_case, monkeypatch):
    case = question_case
    both_entered = asyncio.Event()

    async def pending(count):
        if count == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=2)

    calls = storage_probe(case, monkeypatch, pending=pending, check_pool=False)
    responses = await asyncio.gather(*(case.provider[0].post(case.url, json=case.body) for _ in range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["duplicate"] for response in responses) == [False, True]
    assert responses[0].json()["context"] == responses[1].json()["context"]
    assert len(calls) == 2
    await assert_writes(case, count=1)


async def test_memory_failure_retains_atomic_question_and_replay_skips_pdf_proof(question_case, monkeypatch):
    from app.services import workspace_conversation_events as events
    case = question_case
    calls = storage_probe(case, monkeypatch)
    original = events.workspace_memory_context

    async def failed_memory(*_args, **_kwargs):
        assert case.engine.pool.checkedout() == 0
        raise RuntimeError("Synthetic memory boundary failure")

    monkeypatch.setattr(events, "workspace_memory_context", failed_memory)
    with pytest.raises(RuntimeError, match="Synthetic memory boundary failure"):
        await case.provider[0].post(case.url, json=case.body)
    await assert_writes(case, count=1)
    monkeypatch.setattr(events, "workspace_memory_context", original)
    response = await case.provider[0].post(case.url, json=case.body)
    assert response.status_code == 200, response.text
    assert response.json()["duplicate"] is True
    assert json.loads(response.json()["context"])["state"]["selection"]["reference_id"]
    assert len(calls) == 1
    await assert_writes(case, count=1)


async def test_served_file_and_text_detail_expose_exact_source_version(question_case, monkeypatch):
    case = question_case
    from app.services import object_storage

    async def get_object(_bucket, _key):
        assert case.engine.pool.checkedout() == 0
        return case.data, "application/pdf"

    monkeypatch.setattr(object_storage, "get_object", get_object)
    endpoint = f"/voice-workspaces/{case.provider[2]}/sources/{SOURCE}"
    detail = await case.provider[0].get(endpoint)
    assert detail.status_code == 200, detail.text
    version = case.body["context_snapshot"]["selection"]["source_version"]
    assert detail.json()["source_version"] == version
    file = await case.provider[0].get(endpoint + "/file", headers={"Origin": "http://localhost:5173"})
    assert file.status_code == 200, file.text
    assert file.content == case.data
    assert file.headers["X-Workspace-Source-Version"] == version
    assert file.headers["X-Workspace-File-Sha256"] == sha256(case.data).hexdigest()
    assert "x-workspace-source-version" in file.headers["access-control-expose-headers"].lower()
    await assert_writes(case, count=0)


async def test_changed_original_bytes_rejected_even_when_metadata_and_pdf_text_match(question_case, monkeypatch):
    case = question_case
    changed_data = case.data.replace(b"%PDF-1.1", b"%PDF-1.2", 1)
    assert len(changed_data) == len(case.data) and changed_data != case.data
    storage_probe(replace(case, data=changed_data), monkeypatch)
    response = await case.provider[0].post(case.url, json=case.body)
    assert response.status_code == 409, response.text
    await assert_writes(case, count=0)


async def test_cancelled_storage_wait_leaves_no_question_and_releases_pool(question_case, monkeypatch):
    case = question_case
    entered, released = asyncio.Event(), asyncio.Event()

    async def pending(_count):
        entered.set()
        await released.wait()

    storage_probe(case, monkeypatch, pending=pending)
    task = asyncio.create_task(case.provider[0].post(case.url, json=case.body))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await assert_writes(case, count=0)
    assert case.engine.pool.checkedout() == 0


async def test_pdf_analysis_wait_releases_pool_and_cancellation_saves_nothing(question_case, monkeypatch):
    case = question_case
    storage_probe(case, monkeypatch)
    entered, released = asyncio.Event(), Event()
    loop = asyncio.get_running_loop()
    original = selection_verification.selected_pdf_quote

    def pending_parse(data, anchor):
        loop.call_soon_threadsafe(entered.set)
        assert released.wait(timeout=3)
        return original(data, anchor)

    monkeypatch.setattr(selection_verification, "selected_pdf_quote", pending_parse)
    task = asyncio.create_task(case.provider[0].post(case.url, json=case.body))
    await asyncio.wait_for(entered.wait(), timeout=2)
    try:
        async with case.provider[1]() as reader:
            assert await asyncio.wait_for(reader.scalar(text("SELECT 1")), timeout=1) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await assert_writes(case, count=0)
    finally:
        released.set()


async def test_text_question_creates_reference_without_pdf_download_or_canvas_update(question_case, monkeypatch):
    case = question_case
    async with case.provider[1]() as session:
        source = await session.get(StoredObject, SOURCE)
        source.content_type, source.filename, source.extracted_text = "text/plain", "policy.txt", QUOTE
        version = source_version(source)
        await session.commit()
    body = deepcopy(case.body)
    body["context_snapshot"]["selection"] = {"source_id": SOURCE, "source_version": version,
        "anchor": {"anchor_type": "text", "locator": "document", "exact_text": "Customer files stay private."}}
    calls = storage_probe(case, monkeypatch)
    response = await case.provider[0].post(case.url, json=body)
    assert response.status_code == 200, response.text
    state = json.loads(response.json()["context"])["state"]
    async with case.provider[1]() as session:
        reference = await session.get(WorkspaceReference, state["selection"]["reference_id"])
        assert reference.anchor["exact_text"] == "Customer files stay private."
        assert reference.source_version == version
    assert calls == []
    await assert_writes(case, count=1)


async def test_memory_wait_rechecks_revoked_provider_and_retains_saved_question(question_case, monkeypatch):
    from app.services import workspace_conversation_events as events
    case = question_case
    storage_probe(case, monkeypatch)
    entered, released = asyncio.Event(), asyncio.Event()

    async def pending_memory(*_args, **_kwargs):
        assert case.engine.pool.checkedout() == 0
        entered.set()
        await released.wait()
        return []

    monkeypatch.setattr(events, "workspace_memory_context", pending_memory)
    task = asyncio.create_task(case.provider[0].post(case.url, json=case.body))
    await asyncio.wait_for(entered.wait(), timeout=2)
    try:
        async with case.provider[1]() as session:
            (await session.get(WorkspaceConversationSession, case.connection["session_id"])).status = "revoked"
            await session.commit()
    finally:
        released.set()
    response = await asyncio.wait_for(task, timeout=3)
    assert response.status_code == 401, response.text
    await assert_writes(case, count=1)
    async with case.provider[1]() as session:
        event = await session.scalar(select(WorkspaceConversationEvent).where(WorkspaceConversationEvent.kind == "user"))
        assert event.payload.get("context") is None
