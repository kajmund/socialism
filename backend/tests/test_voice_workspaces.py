from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select

from app.database.models import Job, Persona, StoredObject, UserAccount
from app.database.session import engine
from app.database.workspace_models import WorkspaceArtifact, WorkspaceOperation, WorkspaceReference
from app.services import jobs as jobs_service
from app.services.workspace.service import create_workspace, new_id, publish_artifact_revision
from app.services.workspace.tools import execute_workspace_tool
from tests.conftest import ADMIN_USER_ID


@pytest.fixture(autouse=True)
def hold_jobs(monkeypatch):
    monkeypatch.setattr(jobs_service, "enqueue_job", lambda _job_id: None)


async def workspace(client):
    response = await client.post("/voice-workspaces?customer_id=1", json={"title": "Avtal", "idempotency_key": new_id()})
    assert response.status_code == 201, response.text
    return response.json()


async def upload(client, wid, *, key="upload-one", text="Avtalets pris är 100 kronor."):
    response = await client.post(f"/voice-workspaces/{wid}/sources/upload", data={"idempotency_key": key},
        files={"file": ("avtal.txt", text.encode(), "text/plain")})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_workspace_owner_and_shared_source_membership_are_enforced(client_db, user_token):
    client, factory = client_db
    ws = await workspace(client)
    headers = {"Authorization": f"Bearer {user_token}"}
    assert (await client.get(f"/voice-workspaces/{ws['id']}", headers=headers)).status_code == 404
    other = await client.post("/underlag?module=dd", files={"file": ("privat.txt", b"Private", "text/plain")}, headers=headers)
    assert other.status_code == 201
    attach = await client.post(f"/voice-workspaces/{ws['id']}/sources", json={"source_id": other.json()["id"], "idempotency_key": "attach"})
    assert attach.status_code == 200
    async with factory() as session:
        assert (await session.execute(select(func.count()).select_from(WorkspaceOperation))).scalar_one() == 1


@pytest.mark.asyncio
async def test_state_cas_and_idempotent_replay_do_not_overwrite_newer_state(client):
    ws = await workspace(client)
    payload = {"expected_revision": 0, "title": "Första", "idempotency_key": "patch-first"}
    first = await client.patch(f"/voice-workspaces/{ws['id']}", json=payload)
    assert first.status_code == 200
    second = await client.patch(f"/voice-workspaces/{ws['id']}", json={"expected_revision": 1, "title": "Andra", "idempotency_key": "patch-second"})
    assert second.status_code == 200
    assert (await client.patch(f"/voice-workspaces/{ws['id']}", json=payload)).json() == first.json()
    stale = await client.patch(f"/voice-workspaces/{ws['id']}", json={**payload, "idempotency_key": "stale"})
    assert stale.status_code == 409
    changed_payload = await client.patch(f"/voice-workspaces/{ws['id']}", json={**payload, "title": "Manipulated"})
    assert changed_payload.status_code == 409
    assert (await client.get(f"/voice-workspaces/{ws['id']}")).json()["title"] == "Andra"


@pytest.mark.asyncio
async def test_ingest_replay_keeps_one_file_and_one_durable_job(client_db):
    client, factory = client_db
    ws = await workspace(client)
    first = await upload(client, ws["id"])
    assert await upload(client, ws["id"]) == first
    changed = await client.post(f"/voice-workspaces/{ws['id']}/sources/upload", data={"idempotency_key": "upload-one"},
        files={"file": ("avtal.txt", b"Different", "text/plain")})
    assert changed.status_code == 409
    async with factory() as session:
        assert (await session.execute(select(func.count()).select_from(Job).where(Job.kind == "document_ingest"))).scalar_one() == 1
        assert (await session.execute(select(func.count()).select_from(StoredObject))).scalar_one() == 1
    status = await client.post(f"/voice-workspaces/{ws['id']}/tools/get_job_status", json={"idempotency_key": "status", "arguments": {"job_id": first["job_id"]}})
    assert status.json()["job_status"] == "pending"


@pytest.mark.asyncio
async def test_stable_citations_track_changed_source_and_reject_other_workspace(client_db):
    client, factory = client_db
    ws = await workspace(client)
    source = await upload(client, ws["id"])
    async def read(key):
        return await client.post(f"/voice-workspaces/{ws['id']}/tools/read_source", json={"idempotency_key": key, "arguments": {"source_id": source["source_id"]}})
    async with factory() as session:
        row = await session.get(StoredObject, source["source_id"])
        row.extracted_text, row.extraction_status = "Avtalets pris är 100 kronor.", "ok"
        await session.commit()
    first, second = (await read("read-one")).json(), (await read("read-two")).json()
    assert first["reference_id"] == second["reference_id"]
    assert first["number"] == 1 and not first["stale"]
    other = await workspace(client)
    forbidden = await client.get(f"/voice-workspaces/{other['id']}/references/{first['reference_id']}")
    assert forbidden.status_code == 404
    async with factory() as session:
        row = await session.get(StoredObject, source["source_id"])
        row.extracted_text = "En ny version med andra villkor."
        await session.commit()
    old = await client.get(f"/voice-workspaces/{ws['id']}/references/{first['reference_id']}")
    assert old.json()["stale"] is True and old.json()["file_url"] is None
    assert old.json()["excerpt"] == first["excerpt"]


@pytest.mark.asyncio
async def test_search_only_uses_selected_scope_and_readable_members(client_db, monkeypatch):
    client, factory = client_db
    ws = await workspace(client)
    source = await upload(client, ws["id"])
    captured, indexed = [], {}
    from app.services.workspace import search
    async def external_search(sources, query):
        captured.append(SimpleNamespace(customer_id=query.scope.customer_id, case_id=sources[0].id))
        hit = SimpleNamespace(document_id="indexed-one", provider="supabase", score=0.9,
            excerpt="Avtalets pris är 100 kronor.", title="Pris", locator="line:1", metadata=indexed)
        return [(sources[0], hit, [])]
    monkeypatch.setattr(search, "_external_search", external_search)
    pending = await client.post(f"/voice-workspaces/{ws['id']}/tools/search_knowledge", json={"idempotency_key": "pending", "arguments": {"query": "pris"}})
    assert pending.json()["items"] == [] and pending.json()["gaps"][0]["status"] == "pending"
    async with factory() as session:
        row = await session.get(StoredObject, source["source_id"])
        row.knowledge_status, row.extraction_status = "partial", "ok"
        row.extracted_text = "Avtalets pris är 100 kronor."
        indexed.update(await _seed_canonical_source(session, row))
    result = await client.post(f"/voice-workspaces/{ws['id']}/tools/search_knowledge", json={"idempotency_key": "ready", "arguments": {"query": "pris"}})
    assert result.status_code == 200, result.text
    assert result.json()["items"][0]["number"] == 1
    assert captured[0].customer_id == 1 and captured[0].case_id == source["source_id"]
    conflict = await client.post(f"/voice-workspaces/{ws['id']}/tools/search_knowledge", json={"idempotency_key": "wrong-scope", "arguments": {"query": "pris", "scope": "general"}})
    assert conflict.status_code == 409


async def _seed_canonical_source(session, source):
    from app.services.knowledge.canonical_ingest import ingest_extracted_source
    from app.services.knowledge.extractors import ExtractedBlock, ExtractedDocument
    from app.services.knowledge.models import KnowledgeDocument, KnowledgeScope
    from app.services.knowledge.units import hash_text
    from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
    from tests.knowledge_fakes import FakeEmbeddingProvider
    result = await ingest_extracted_source(session,
        extracted=ExtractedDocument([ExtractedBlock(source.extracted_text, "line:1")]),
        document=KnowledgeDocument(document_id="indexed-one", provider="supabase", external_id=source.id,
            title=source.filename, mime_type=source.content_type,
            scope=KnowledgeScope(customer_id=source.customer_id, workspace_id=source.workspace_id, module=source.module),
            metadata={"source_object_id": source.id, "workspace_id": source.workspace_id}),
        source_type="uploaded_file", canonical_uri=f"stored-object:{source.id}",
        content_hash=hash_text(source.extracted_text), customer_id=source.customer_id, source_object_id=source.id,
        embeddings=FakeEmbeddingProvider(), vector_store=MemoryKnowledgeVectorStore())
    return {"text_unit_id": result.segmented.text_units[0].id,
            "document_version_id": result.document_version_id}


@pytest.mark.asyncio
async def test_artifact_edits_are_revision_bound_and_old_revision_is_immutable(client_db):
    client, factory = client_db
    ws = await workspace(client)
    async with factory() as session:
        artifact = WorkspaceArtifact(id=new_id(), workspace_id=ws["id"], kind="document", title="Brev", status="queued", revision=0, content={})
        session.add(artifact)
        await session.flush()
        await publish_artifact_revision(session, artifact, expected_revision=0,
            content={"blocks": [{"id": "p1", "type": "paragraph", "text": "Ursprunglig text", "source_refs": []}]})
        await session.commit()
        aid = artifact.id
    payload = {"expected_revision": 1, "idempotency_key": "edit", "content": {"blocks": [{"id": "p1", "type": "paragraph", "text": "Ändrad text", "source_refs": []}]}}
    edited = await client.patch(f"/voice-workspaces/{ws['id']}/artifacts/{aid}", json=payload)
    assert edited.status_code == 200 and edited.json()["artifact"]["revision"] == 2
    assert (await client.patch(f"/voice-workspaces/{ws['id']}/artifacts/{aid}", json=payload)).json() == edited.json()
    stale = await client.patch(f"/voice-workspaces/{ws['id']}/artifacts/{aid}", json={**payload, "idempotency_key": "stale-edit"})
    assert stale.status_code == 409
    original = await client.get(f"/voice-workspaces/{ws['id']}/artifacts/{aid}/revisions/1")
    assert original.json()["content"]["blocks"][0]["text"] == "Ursprunglig text"
    bad_refs = await client.patch(f"/voice-workspaces/{ws['id']}/artifacts/{aid}", json={"expected_revision": 2, "idempotency_key": "bad-refs",
        "content": {"blocks": [{"id": "p1", "type": "paragraph", "text": "Claim", "source_refs": ["other-workspace-ref"]}]}})
    assert bad_refs.status_code == 404


@pytest.mark.asyncio
async def test_create_document_replay_preserves_job_and_artifact(client_db):
    client, factory = client_db
    ws = await workspace(client)
    payload = {"idempotency_key": "create-draft", "arguments": {"title": "Brev", "instructions": "Ett kort brev"}}
    first = await client.post(f"/voice-workspaces/{ws['id']}/tools/create_document", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "queued"
    assert (await client.post(f"/voice-workspaces/{ws['id']}/tools/create_document", json=payload)).json() == first.json()
    async with factory() as session:
        assert (await session.execute(select(func.count()).select_from(WorkspaceArtifact))).scalar_one() == 1
        assert (await session.execute(select(func.count()).select_from(Job).where(Job.kind == "workspace_generation"))).scalar_one() == 1


@pytest.mark.asyncio
async def test_frozen_turn_context_survives_later_selection_but_revoked_session_is_denied(client_db):
    _client, factory = client_db
    async with factory() as session:
        user = await session.get(UserAccount, ADMIN_USER_ID)
        expert = (await session.execute(select(Persona).where(Persona.customer_id == 1, Persona.kind == "expert").limit(1))).scalar_one()
        from app.services.workspace.containers import WorkspaceContainer
        ws = await create_workspace(session, user, title="Test", module="dd", container=WorkspaceContainer(customer_id=1))
        old_state = {**ws.state, "expert_id": expert.id, "knowledge_scope": "general"}
        ws.state = {**old_state, "knowledge_scope": "workspace"}
        ws.revision = 4
        agent = SimpleNamespace(workspace_id=ws.id, user_id=user.id, customer_id=1, expert_id=expert.id,
            status="active", expires_at=datetime.now(UTC) + timedelta(minutes=5), turn_state=old_state, turn_revision=2)
        await session.commit()
        result = await execute_workspace_tool(session, workspace_id=ws.id, user=user, tool_name="get_workspace_context",
            arguments={}, idempotency_key="turn", agent_session=agent)
        assert result["turn_context"]["revision"] == 2
        assert result["turn_context"]["state"]["knowledge_scope"] == "general"
        assert result["workspace"]["state"]["knowledge_scope"] == "workspace"
        await session.commit()
        agent.status = "revoked"
        with pytest.raises(HTTPException) as error:
            await execute_workspace_tool(session, workspace_id=ws.id, user=user, tool_name="get_workspace_context",
                arguments={}, idempotency_key="turn", agent_session=agent)
        assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_workspace_create_is_idempotent_and_rejects_key_reuse(client):
    payload = {"title": "Avtal", "idempotency_key": "same-create"}
    first = await client.post("/voice-workspaces?customer_id=1", json=payload)
    second = await client.post("/voice-workspaces?customer_id=1", json=payload)
    assert first.status_code == 201 and second.json()["id"] == first.json()["id"]
    conflict = await client.post("/voice-workspaces?customer_id=1", json={**payload, "title": "Other"})
    assert conflict.status_code == 409
    assert len((await client.get("/voice-workspaces")).json()) == 1


@pytest.mark.asyncio
async def test_generation_language_is_frozen_from_explicit_workspace_locale(client_db):
    client, factory = client_db
    created = await client.post("/voice-workspaces?customer_id=1", json={"title": "Letter", "language": "en", "idempotency_key": "english"})
    ws = created.json()
    assert ws["state"]["language"] == "en"
    request = {"idempotency_key": "draft-en", "arguments": {"instructions": "Write a letter", "language": "sv"}}
    generated = await client.post(f"/voice-workspaces/{ws['id']}/tools/create_document", json=request)
    assert generated.status_code == 200, generated.text
    job_id = generated.json()["job_id"]
    async with factory() as session:
        job = await session.get(Job, job_id)
        assert job.request["language"] == "en" and job.request["arguments"]["language"] == "en"
        operation = await session.get(WorkspaceOperation, generated.json()["operation_id"])
        assert operation.context_snapshot["state"]["language"] == "en"
    changed = await client.patch(f"/voice-workspaces/{ws['id']}", json={"expected_revision": 0, "idempotency_key": "locale-sv",
        "state": {**ws["state"], "language": "sv"}})
    assert changed.status_code == 200
    assert (await client.post(f"/voice-workspaces/{ws['id']}/tools/create_document", json=request)).json() == generated.json()
    invalid = await client.patch(f"/voice-workspaces/{ws['id']}", json={"expected_revision": 1, "idempotency_key": "locale-bad",
        "state": {**ws["state"], "language": "xx"}})
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_subselection_is_quote_bound_and_document_tabs_bind_their_source(client_db):
    client, factory = client_db
    ws = await workspace(client)
    source = await upload(client, ws["id"])
    async with factory() as session:
        row = await session.get(StoredObject, source["source_id"])
        row.extracted_text, row.extraction_status = "Avtalets pris är 100 kronor.", "ok"
        await session.commit()
    read = await client.post(f"/voice-workspaces/{ws['id']}/tools/read_source", json={"idempotency_key": "full", "arguments": {"source_id": source["source_id"]}})
    ref = read.json()
    anchor = {**ref["anchor"], "exact_text": "100 kronor."}
    state = {**ws["state"], "documents": [{"source_id": source["source_id"], "reference_id": ref["reference_id"]}],
        "selection": {"reference_id": ref["reference_id"], "anchor": anchor}}
    selected = await client.patch(f"/voice-workspaces/{ws['id']}", json={"expected_revision": 0, "idempotency_key": "select-quote", "state": state})
    assert selected.status_code == 200, selected.text
    new_reference = selected.json()["state"]["selection"]["reference_id"]
    assert new_reference != ref["reference_id"]
    assert (await client.get(f"/voice-workspaces/{ws['id']}/references/{new_reference}")).json()["excerpt"] == "100 kronor."
    fake_anchor = {**state, "selection": {"reference_id": ref["reference_id"], "anchor": {**anchor, "exact_text": "Fake number 200"}}}
    bad = await client.patch(f"/voice-workspaces/{ws['id']}", json={"expected_revision": 1, "idempotency_key": "fake-anchor", "state": fake_anchor})
    assert bad.status_code == 409
    second = await upload(client, ws["id"], key="second-file")
    wrong_tab = {**selected.json()["state"], "documents": [{"source_id": second["source_id"], "reference_id": ref["reference_id"]}]}
    bad_tab = await client.patch(f"/voice-workspaces/{ws['id']}", json={"expected_revision": 1, "idempotency_key": "wrong-tab", "state": wrong_tab})
    assert bad_tab.status_code == 409


@pytest.mark.asyncio
async def test_selected_block_revision_prevents_editing_another_block(client_db):
    client, factory = client_db
    ws = await workspace(client)
    blocks = [{"id": "p1", "type": "paragraph", "text": "First", "source_refs": []},
              {"id": "p2", "type": "paragraph", "text": "Second", "source_refs": []}]
    async with factory() as session:
        artifact = WorkspaceArtifact(id=new_id(), workspace_id=ws["id"], kind="document", title="Letter", status="queued", revision=0, content={})
        session.add(artifact)
        await session.flush()
        await publish_artifact_revision(session, artifact, expected_revision=0, content={"blocks": blocks})
        artifact_id = artifact.id
        await session.commit()
    select = await client.patch(f"/voice-workspaces/{ws['id']}", json={"expected_revision": 0, "idempotency_key": "select-block",
        "state": {**ws["state"], "selection": {"artifact_id": artifact_id, "artifact_revision": 1, "block_id": "p1"}}})
    assert select.status_code == 200
    base = {"artifact_id": artifact_id, "expected_revision": 1}
    changed_second = {"blocks": [blocks[0], {**blocks[1], "text": "Unexpected change"}]}
    wrong = await client.post(f"/voice-workspaces/{ws['id']}/tools/revise_document", json={"idempotency_key": "wrong-block",
        "arguments": {**base, "block_id": "p2", "content": changed_second}})
    assert wrong.status_code == 409
    rewritten = await client.post(f"/voice-workspaces/{ws['id']}/tools/revise_document", json={"idempotency_key": "unselected-change",
        "arguments": {**base, "content": changed_second}})
    assert rewritten.status_code == 422
    valid = await client.post(f"/voice-workspaces/{ws['id']}/tools/revise_document", json={"idempotency_key": "selected-change",
        "arguments": {**base, "content": {"blocks": [{**blocks[0], "text": "Short"}, blocks[1]]}}})
    assert valid.status_code == 200 and valid.json()["artifact"]["revision"] == 2


@pytest.mark.asyncio
async def test_workspace_read_authorizes_sources_once_for_many_references(client_db):
    client, factory = client_db
    ws = await workspace(client)
    uploaded = await upload(client, ws["id"])
    async with factory() as session:
        for number in range(30):
            session.add(WorkspaceReference(id=new_id(), workspace_id=ws["id"], number=number + 1, identity_key=new_id(),
                kind="underlag", source_id=uploaded["source_id"], source_version="missing",
                anchor={"anchor_type": "text", "exact_text": str(number), "rects": []}, snapshot={"title": "Avtal", "excerpt": str(number)}))
        await session.commit()
    statements: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        response = await client.get(f"/voice-workspaces/{ws['id']}")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert response.status_code == 200
    assert len(response.json()["references"]) == 30
    assert len(response.json()["sources"]) == 1
    assert len(statements) < 80, len(statements)
