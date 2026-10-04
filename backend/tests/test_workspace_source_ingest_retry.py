"""Explicit ingest-source retries use the existing document and normal worker queue."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, Job, Kund, StoredObject, UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceOperation, WorkspaceSource
from app.database.workspaces import Workspace
from app.services import jobs
from app.services.workspace.source_ingest_retry import retry_failed_source
from app.services.workspace.tools import execute_workspace_tool
from tests.conftest import USER_USER_ID

SOURCE_ID = "retry-policy"
OLD_JOB = "retry-original-job"


@pytest.fixture
async def retry_document(client_db, user_token, monkeypatch):
    client, factory = client_db
    client.headers["Authorization"] = f"Bearer {user_token}"
    company = next(row["id"] for row in (await client.get("/workspaces")).json() if row["kind"] == "company")
    active = (await client.post("/workspaces", json={"name": "Retry client"})).json()["id"]
    sibling = (await client.post("/workspaces", json={"name": "Sibling"})).json()["id"]
    response = await client.post("/voice-workspaces", json={"workspace_id": active,
        "title": "Retry workspace", "idempotency_key": "retry-canvas"})
    assert response.status_code == 201, response.text
    canvas = response.json()["id"]
    async with factory.begin() as session:
        session.add(Job(id=OLD_JOB, customer_id=1, kind="document_ingest", status="failed",
            error="Avbrutet av serveromstart", request={"object_id": SOURCE_ID,
                "owner_user_id": USER_USER_ID, "workspace_id": company}))
        await session.flush()
        session.add(StoredObject(id=SOURCE_ID, workspace_id=company, customer_id=1,
            owner_user_id=USER_USER_ID, module="expertgranskning", kind="underlag",
            bucket="retry-test", object_key="original-policy.txt", filename="policy.txt", content_type="text/plain",
            size_bytes=16, extraction_status="ok", extracted_text="Synthetic policy", knowledge_status="failed",
            knowledge_error="Avbrutet av serveromstart", knowledge_job_id=OLD_JOB))
        await session.flush()
        scope = {"scope_type": "customer", "scope_key": "customer:1", "customer_id": 1}
        session.add(CanonicalDocumentRecord(id="retry-canonical-document", **scope,
            source_object_id=SOURCE_ID, source_type="uploaded_file", canonical_uri=f"stored-object:{SOURCE_ID}",
            title="policy.txt", extra={"workspace_id": company}))
        await session.flush()
        session.add(DocumentVersionRecord(id="retry-canonical-version", **scope,
            document_id="retry-canonical-document", mime_type="text/plain", content_hash="original-hash"))
    scheduled = []
    monkeypatch.setattr(jobs, "enqueue_job", scheduled.append)
    return client, factory, canvas, company, sibling, scheduled


async def _retry(document, *, key="retry-one", source_id=SOURCE_ID):
    client, _factory, canvas, _company, _sibling, _scheduled = document
    return await client.post(f"/voice-workspaces/{canvas}/tools/ingest_source",
        json={"idempotency_key": key, "arguments": {"source_id": source_id}})


async def _job_count(factory):
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(Job).where(Job.kind == "document_ingest"))


async def test_failed_source_retry_preserves_file_and_canonical_identity_and_schedules_worker(retry_document):
    client, factory, canvas, company, _sibling, scheduled = retry_document
    response = await _retry(retry_document)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "queued" and result["ingest_status"] == "pending"
    assert result["source_id"] == SOURCE_ID and result["job_id"] != OLD_JOB
    assert scheduled == [result["job_id"]]
    async with factory() as session:
        source = await session.get(StoredObject, SOURCE_ID)
        job = await session.get(Job, result["job_id"])
        assert source.knowledge_job_id == job.id and source.knowledge_error is None
        assert job.status == "pending" and job.kind == "document_ingest" and job.customer_id == 1
        assert job.request == {"object_id": SOURCE_ID, "owner_user_id": USER_USER_ID, "workspace_id": company}
        assert (source.bucket, source.object_key, source.filename, source.module) == (
            "retry-test", "original-policy.txt", "policy.txt", "expertgranskning")
        assert source.extracted_text == "Synthetic policy" and source.extraction_status == "ok"
        assert await session.get(WorkspaceSource, (canvas, SOURCE_ID)) is not None
        assert (await session.get(Job, OLD_JOB)).status == "failed"
        assert (await session.get(CanonicalDocumentRecord, "retry-canonical-document")).source_object_id == SOURCE_ID
        assert (await session.get(DocumentVersionRecord, "retry-canonical-version")).content_hash == "original-hash"
        for model in (StoredObject, CanonicalDocumentRecord, DocumentVersionRecord):
            assert await session.scalar(select(func.count()).select_from(model)) == 1
    status = await client.post(f"/voice-workspaces/{canvas}/tools/get_job_status",
        json={"idempotency_key": "retry-status", "arguments": {"job_id": result["job_id"]}})
    assert status.status_code == 200 and status.json()["job_status"] == "pending", status.text


async def test_retry_operation_replay_and_a_new_key_reuse_the_active_job(retry_document):
    first = await _retry(retry_document)
    assert first.status_code == 200, first.text
    replay = await _retry(retry_document)
    assert replay.status_code == 200 and replay.json() == first.json()
    active = await _retry(retry_document, key="another-key")
    assert active.status_code == 200 and active.json()["status"] == "completed"
    assert active.json()["job_id"] == first.json()["job_id"]
    assert await _job_count(retry_document[1]) == 2
    assert set(retry_document[5]) == {first.json()["job_id"]}


@pytest.mark.parametrize("source_status", ["ready", "partial", "pending", "running", "needs_ocr"])
async def test_attaching_non_failed_source_never_retries_automatically(retry_document, source_status):
    async with retry_document[1].begin() as session:
        source = await session.get(StoredObject, SOURCE_ID)
        source.knowledge_status = source_status
    response = await _retry(retry_document)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed" and response.json()["job_id"] == OLD_JOB
    assert response.json()["ingest_status"] == source_status
    assert await _job_count(retry_document[1]) == 1 and retry_document[5] == []


@pytest.mark.parametrize("job_status", ["pending", "running", "succeeded", "cancelled"])
async def test_failed_source_with_non_failed_current_job_is_not_requeued(retry_document, job_status):
    async with retry_document[1].begin() as session:
        (await session.get(Job, OLD_JOB)).status = job_status
    response = await _retry(retry_document)
    assert response.status_code == 200 and response.json()["status"] == "completed", response.text
    assert response.json()["job_id"] == OLD_JOB
    assert await _job_count(retry_document[1]) == 1 and retry_document[5] == []


@pytest.mark.parametrize("mismatch", ["customer", "object", "owner", "parent", "kind", "missing"])
async def test_retry_requires_the_current_failed_job_to_match_source_scope(retry_document, mismatch):
    async with retry_document[1].begin() as session:
        job = await session.get(Job, OLD_JOB)
        if mismatch == "customer":
            session.add(Kund(id=99, name="Unrelated", slug="retry-unrelated"))
            await session.flush()
            job.customer_id = 99
        elif mismatch in {"object", "owner", "parent"}:
            field = {"object": "object_id", "owner": "owner_user_id", "parent": "workspace_id"}[mismatch]
            job.request = {**job.request, field: "another-scope"}
        elif mismatch == "kind":
            job.kind = "report_generate"
        else:
            (await session.get(StoredObject, SOURCE_ID)).knowledge_job_id = None
    response = await _retry(retry_document)
    assert response.status_code == 404, response.text
    assert retry_document[5] == []
    async with retry_document[1]() as session:
        source = await session.get(StoredObject, SOURCE_ID)
        assert source.knowledge_status == "failed" and source.knowledge_error == "Avbrutet av serveromstart"
        assert await session.scalar(select(func.count()).select_from(Job)) == 1
        assert await session.scalar(select(func.count()).select_from(WorkspaceSource)) == 0


@pytest.mark.parametrize("scope", ["sibling", "foreign"])
async def test_retry_denies_sources_outside_the_readable_parent_workspaces(retry_document, scope):
    async with retry_document[1].begin() as session:
        source = await session.get(StoredObject, SOURCE_ID)
        if scope == "sibling":
            source.workspace_id = retry_document[4]
        else:
            session.add(Kund(id=99, name="Foreign", slug="retry-foreign"))
            await session.flush()
            session.add(Workspace(id="foreign-parent", customer_id=99, kind="company", name="Foreign"))
            await session.flush()
            source.customer_id, source.workspace_id = 99, "foreign-parent"
    response = await _retry(retry_document)
    assert response.status_code == 404, response.text
    assert retry_document[5] == [] and await _job_count(retry_document[1]) == 1


async def test_new_job_source_status_and_operation_roll_back_together(retry_document):
    _client, factory, canvas, _company, _sibling, _scheduled = retry_document
    async with factory() as session:
        user = await session.get(UserAccount, USER_USER_ID)
        result = await execute_workspace_tool(session, workspace_id=canvas, user=user,
            tool_name="ingest_source", arguments={"source_id": SOURCE_ID}, idempotency_key="rollback")
        assert result["status"] == "queued"
        await session.rollback()
    async with factory() as session:
        source = await session.get(StoredObject, SOURCE_ID)
        assert source.knowledge_status == "failed" and source.knowledge_job_id == OLD_JOB
        assert await session.scalar(select(func.count()).select_from(Job)) == 1
        assert await session.scalar(select(func.count()).select_from(WorkspaceOperation)) == 0
        assert await session.scalar(select(func.count()).select_from(WorkspaceSource)) == 0


@pytest.mark.parametrize("client", ["file_database"], indirect=True)
async def test_two_concurrent_explicit_retries_create_only_one_new_job(retry_document):
    first, second = await asyncio.gather(_retry(retry_document, key="concurrent-a"),
        _retry(retry_document, key="concurrent-b"))
    assert first.status_code == second.status_code == 200
    assert {first.json()["status"], second.json()["status"]} == {"queued", "completed"}
    assert first.json()["job_id"] == second.json()["job_id"]
    assert await _job_count(retry_document[1]) == 2 and len(retry_document[5]) == 1


@pytest.mark.parametrize("client", ["file_database"], indirect=True)
async def test_compare_and_swap_discards_a_losing_retry_job(retry_document):
    _client, factory, canvas_id, company, _sibling, _scheduled = retry_document
    async with factory() as stale:
        source = await stale.get(StoredObject, SOURCE_ID)
        canvas = await stale.get(VoiceWorkspace, canvas_id)
        async with factory.begin() as winner:
            winner.add(Job(id="winning-retry", customer_id=1, kind="document_ingest", status="pending",
                request={"object_id": SOURCE_ID, "owner_user_id": USER_USER_ID, "workspace_id": company}))
            await winner.flush()
            current = await winner.get(StoredObject, SOURCE_ID)
            current.knowledge_job_id, current.knowledge_status, current.knowledge_error = "winning-retry", "pending", None
        result = await retry_failed_source(stale, canvas, source)
        assert result["status"] == "completed" and result["job_id"] == "winning-retry"
        await stale.commit()
    assert await _job_count(factory) == 2
