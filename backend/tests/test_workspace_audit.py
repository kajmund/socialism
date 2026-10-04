"""Regression coverage for workspace generation boundaries and private job events."""

from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from starlette.websockets import WebSocketState

from app.auth.scope import job_visible_to_user
from app.database.models import Job, Kund, StoredObject, UserAccount
from app.database.workspace_models import WorkspaceArtifactRevision, WorkspaceReference, WorkspaceSource
from app.llm import set_structured_completer
from app.realtime.hub import EventHub
from app.services import jobs
from app.services.workspace_export import export_revision_docx
from tests.conftest import ADMIN_USER_ID, USER_USER_ID
from tests.test_workspace_generation import document


@pytest.fixture(autouse=True)
def hold_jobs(monkeypatch):
    monkeypatch.setattr(jobs, "enqueue_job", lambda _job_id: None)


async def create_workspace(client, headers=None):
    response = await client.post("/voice-workspaces?customer_id=1", headers=headers, json={"title": "Audit", "idempotency_key": str(uuid4())})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["version", "remove", "tamper"])
async def test_generation_revalidates_every_input_before_llm(client_db, change):
    client, factory = client_db
    workspace = await create_workspace(client)
    async with factory() as session:
        session.add(StoredObject(id="source-audit", workspace_id=workspace["workspace_id"], customer_id=1, owner_user_id=ADMIN_USER_ID, module="dd", kind="underlag",
            bucket="audit", object_key="source.txt", filename="source.txt", content_type="text/plain", size_bytes=6,
            extraction_status="ok", extracted_text="Source", knowledge_status="ready"))
        session.add(WorkspaceSource(workspace_id=workspace["id"], source_id="source-audit"))
        await session.commit()
    read = await client.post(f"/voice-workspaces/{workspace['id']}/tools/read_source", json={"idempotency_key": "read", "arguments": {"source_id": "source-audit"}})
    queued = await client.post(f"/voice-workspaces/{workspace['id']}/tools/create_document", json={"idempotency_key": "generate",
        "arguments": {"source_refs": [read.json()["reference_id"]], "instructions": "Use the source"}})
    assert queued.status_code == 200, queued.text
    job_id = queued.json()["job_id"]
    async with factory() as session:
        if change == "version":
            (await session.get(StoredObject, "source-audit")).extracted_text = "Changed source"
        elif change == "remove":
            await session.delete(await session.get(WorkspaceSource, (workspace["id"], "source-audit")))
        else:
            job = await session.get(Job, job_id)
            request = {**job.request, "arguments": {**job.request["arguments"]}}
            context = request["arguments"]["source_context"]
            request["arguments"]["source_context"] = [{**context[0], "snapshot": {**context[0]["snapshot"], "excerpt": "Forged context"}}]
            job.request = request
        await session.commit()
    calls = []
    async def complete(_messages, model):
        calls.append("LLM")
        return model.model_validate(document())
    set_structured_completer(complete)
    await jobs._run_job(job_id)
    assert calls == []
    async with factory() as session:
        assert (await session.get(Job, job_id)).status == "failed"


@pytest.mark.asyncio
async def test_generation_checks_current_customer_binding_before_llm(client_db, user_token):
    client, factory = client_db
    headers = {"Authorization": f"Bearer {user_token}"}
    workspace = await create_workspace(client, headers)
    queued = await client.post(f"/voice-workspaces/{workspace['id']}/tools/create_document", headers=headers,
        json={"idempotency_key": "generate", "arguments": {"instructions": "Draft"}})
    assert queued.status_code == 200, queued.text
    async with factory() as session:
        user = await session.get(UserAccount, USER_USER_ID)
        user.kund_id = 2
        await session.commit()
    calls = []
    async def complete(_messages, model):
        calls.append("LLM")
        return model.model_validate(document())
    set_structured_completer(complete)
    await jobs._run_job(queued.json()["job_id"])
    assert calls == []
    async with factory() as session:
        assert (await session.get(Job, queued.json()["job_id"])).status == "failed"


def test_docx_uses_actual_page_number_and_source_url_contract():
    reference = WorkspaceReference(id="ref", workspace_id="ws", number=3, kind="graph", source_id="source", source_version="hash",
        anchor={"page_number": 7, "locator": "section:4"}, snapshot={"title": "Evidence", "source_url": "https://example.test/evidence"})
    revision = WorkspaceArtifactRevision(artifact_id="artifact", revision=1, title="Document", content=document(refs=[reference.id]))
    with ZipFile(BytesIO(export_revision_docx(revision, [reference]))) as package:
        content = " ".join(ET.fromstring(package.read("word/document.xml")).itertext())
    assert "[3]" in content and "s. 7" in content and "https://example.test/evidence" in content


class Socket:
    client_state = WebSocketState.CONNECTED
    def __init__(self):
        self.events = []
    async def send_json(self, event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_live_workspace_jobs_enforce_same_owner_rule_even_for_admins():
    owner = UserAccount(id="owner", email="owner@example.test", role="user", kund_id=1)
    admin = UserAccount(id="admin", email="admin@example.test", role="admin")
    event = {"type": "job.updated", "job": {"kind": "workspace_generation", "customer_id": 1,
        "request": {"workspace_id": "ws", "owner_user_id": owner.id, "source_context": "private"}}}
    job = SimpleNamespace(kind="workspace_generation", customer_id=1, request=event["job"]["request"])
    assert job_visible_to_user(owner, job) and not job_visible_to_user(admin, job)
    moved_owner = UserAccount(id=owner.id, email="owner@example.test", role="admin", kund_id=2)
    assert not job_visible_to_user(moved_owner, job)
    hub = EventHub(name="test")
    owner_socket, admin_socket, anonymous_socket = Socket(), Socket(), Socket()
    await hub.subscribe(owner_socket, customer_id=1, user=owner)
    await hub.subscribe(admin_socket, user=admin)
    await hub.subscribe(anonymous_socket)
    await hub.publish(event)
    assert owner_socket.events == [event] and admin_socket.events == anonymous_socket.events == []
    public = {"type": "job.updated", "job": {"kind": "report_generate", "customer_id": 1, "request": {}}}
    await hub.publish(public)
    assert admin_socket.events == anonymous_socket.events == [public]


@pytest.mark.asyncio
async def test_job_list_and_detail_hide_another_users_workspace_from_admin(client_db, user_token):
    client, _factory = client_db
    headers = {"Authorization": f"Bearer {user_token}"}
    workspace = await create_workspace(client, headers)
    queued = await client.post(f"/voice-workspaces/{workspace['id']}/tools/create_document", headers=headers,
        json={"idempotency_key": "generate", "arguments": {"instructions": "Private"}})
    job_id = queued.json()["job_id"]
    assert (await client.get(f"/jobs/{job_id}")).status_code == 403
    assert (await client.get(f"/jobs/{job_id}", headers=headers)).status_code == 200
    assert all(job["id"] != job_id for job in (await client.get("/jobs")).json())
    assert any(job["id"] == job_id for job in (await client.get("/jobs", headers=headers)).json())


@pytest.mark.asyncio
async def test_url_origin_is_persisted_and_inherited_by_new_citations(client_db, monkeypatch):
    client, factory = client_db
    workspace = await create_workspace(client)
    from app.services.workspace import ingest
    async def fetch(_url):
        return b"Remote source", "text/plain", "source.txt", "https://example.test/final-source"
    monkeypatch.setattr(ingest, "fetch_source_url", fetch)
    imported = await client.post(f"/voice-workspaces/{workspace['id']}/tools/ingest_source", json={"idempotency_key": "url",
        "arguments": {"url": "https://example.test/source"}})
    assert imported.status_code == 200, imported.text
    source_id = imported.json()["source_id"]
    async with factory() as session:
        membership = await session.get(WorkspaceSource, (workspace["id"], source_id))
        assert membership.source_url == "https://example.test/final-source"
        source = await session.get(StoredObject, source_id)
        source.extracted_text, source.extraction_status = "Remote source", "ok"
        await session.commit()
    read = await client.post(f"/voice-workspaces/{workspace['id']}/tools/read_source", json={"idempotency_key": "new-citation", "arguments": {"source_id": source_id}})
    assert read.status_code == 200, read.text
    assert read.json()["snapshot"]["source_url"] == "https://example.test/final-source"


@pytest.mark.asyncio
async def test_job_state_events_release_single_connection_before_broadcast(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.database.base import Base
    from app.serializers import utcnow
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/events.db", pool_size=1, max_overflow=0, pool_timeout=0.3)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Job(id="job-event", customer_id=1, kind="workspace_generation", status="pending", label="Draft",
            request={"voice_workspace_id": "ws", "workspace_id": "parent", "chat_id": "chat", "artifact_id": "a", "operation_id": "op", "owner_user_id": "owner",
                     "expected_revision": 0, "arguments": {}}, created_at=utcnow(), updated_at=utcnow()))
        await session.commit()
    states = []
    async def broadcast(job):
        states.append(job.status)
        async with factory() as reader:
            assert await reader.get(Job, job.id) is not None
    monkeypatch.setattr(jobs, "job_session_factory", lambda: factory)
    monkeypatch.setattr(jobs, "publish_job", broadcast)
    try:
        assert await jobs._mark_job_running("job-event") == "workspace_generation"
        async with factory() as session:
            await jobs._fail(session, "job-event", "Test failure")
        async with factory() as session:
            await jobs._succeed(session, "job-event", {"result": "Ready"})
        async with factory() as session:
            await jobs.set_job_archived(session, await session.get(Job, "job-event"), True)
        async with factory() as session:
            await jobs.set_job_archived(session, await session.get(Job, "job-event"), False)
        async with factory() as session:
            await jobs.archive_finished_jobs(session)

    finally:
        await engine.dispose()
    assert states == ["running", "failed", "succeeded", "succeeded", "succeeded", "succeeded"]


@pytest.mark.asyncio
async def test_job_snapshot_filters_owners_and_releases_pool_before_socket(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.database.base import Base
    from app.serializers import utcnow
    from app.services.job_watch import send_jobs_snapshot
    from app.database.workspaces import Workspace as CoreWorkspace
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/snapshot.db", pool_size=1, max_overflow=0, pool_timeout=0.3)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=1, name="Customer", slug="customer", available_modules=[]))
        session.add(UserAccount(id="admin", email="admin@example.test", role="admin"))
        session.add(CoreWorkspace(id="parent", customer_id=1, name="Company", kind="company"))
        for owner in ("admin", "other"):
            session.add(Job(id=f"job-{owner}", customer_id=1, kind="workspace_generation", status="pending", label="Draft",
                request={"workspace_id": "parent", "owner_user_id": owner, "source_context": "private"}, created_at=utcnow(), updated_at=utcnow()))
        await session.commit()
    events = []
    class CheckedSocket:
        async def send_json(self, event):
            async with factory() as reader:
                assert await reader.get(Job, "job-admin") is not None
            events.append(event)
    monkeypatch.setattr(jobs, "job_session_factory", lambda: factory)
    try:
        await send_jobs_snapshot(CheckedSocket(), UserAccount(id="admin", email="admin@example.test", role="admin"), customer_id=None)
    finally:
        await engine.dispose()
    assert [job["id"] for job in events[0]["jobs"]] == ["job-admin"]
