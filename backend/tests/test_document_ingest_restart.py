"""Restarted ingest jobs cannot leave their current source stuck in progress."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Job, Kund, StoredObject, UserAccount
from app.database.workspaces import Workspace
from app.services import jobs

OWNER_ID = "ingest-restart-owner"
RESTART_ERROR = "Avbrutet av serveromstart"


@pytest.fixture
async def restart_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'restart.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory.begin() as session:
        session.add_all([
            Kund(id=1, name="Testbyrån", slug="restart-one", available_modules=["dd"]),
            Kund(id=2, name="Annan byrå", slug="restart-two", available_modules=["dd"]),
        ])
        await session.flush()
        session.add(UserAccount(id=OWNER_ID, email="restart@test.invalid", role="user", kund_id=1))
        session.add_all([
            Workspace(id="client-a", customer_id=1, name="Klient A", kind="client"),
            Workspace(id="client-b", customer_id=1, name="Klient B", kind="client"),
            Workspace(id="foreign", customer_id=2, name="Annan byrå", kind="company"),
        ])
    yield factory
    await engine.dispose()


async def _add_source(session, identity, *, job_values=None, source_values=None):
    job_data = {
        "id": f"job-{identity}", "customer_id": 1, "kind": "document_ingest",
        "status": "failed", "error": "Bearbetningen avbröts",
        "request": {"object_id": identity, "owner_user_id": OWNER_ID},
    }
    job_data.update(job_values or {})
    session.add(Job(**job_data))
    await session.flush()
    source_data = {
        "id": identity, "customer_id": 1, "workspace_id": "client-a", "owner_user_id": OWNER_ID,
        "kind": "underlag", "module": "expertgranskning", "bucket": "test", "object_key": identity,
        "filename": f"{identity}.txt", "content_type": "text/plain", "size_bytes": 13,
        "knowledge_status": "running", "knowledge_error": None, "knowledge_job_id": job_data["id"],
        "extraction_status": "ok", "extracted_text": "Synthetic text.",
    }
    source_data.update(source_values or {})
    session.add(StoredObject(**source_data))


@pytest.mark.parametrize("job_status", ["pending", "running"])
@pytest.mark.parametrize("source_status", ["pending", "running"])
async def test_restart_fails_current_ingest_source_with_the_job(restart_factory, job_status, source_status):
    async with restart_factory.begin() as session:
        await _add_source(session, "interrupted", job_values={"status": job_status},
                          source_values={"knowledge_status": source_status})

    async with restart_factory() as session:
        assert await jobs.fail_interrupted_jobs(session) == 1

    async with restart_factory() as session:
        job = await session.get(Job, "job-interrupted")
        source = await session.get(StoredObject, "interrupted")
        assert job.status == source.knowledge_status == "failed"
        assert job.error == source.knowledge_error == RESTART_ERROR
        assert source.knowledge_job_id == job.id
        assert (source.extracted_text, source.extraction_status) == ("Synthetic text.", "ok")
        assert (source.bucket, source.object_key, source.filename) == ("test", "interrupted", "interrupted.txt")


@pytest.mark.parametrize("job_status", ["failed", "cancelled"])
@pytest.mark.parametrize("source_status", ["pending", "running"])
@pytest.mark.parametrize("error", [None, "Avbrutet under föregående omstart"])
async def test_startup_reconciles_previously_terminal_current_jobs(
    restart_factory, job_status, source_status, error,
):
    async with restart_factory.begin() as session:
        await _add_source(session, "stale", job_values={"status": job_status, "error": error},
                          source_values={"knowledge_status": source_status})

    async with restart_factory() as session:
        assert await jobs.fail_interrupted_jobs(session) == 0

    async with restart_factory() as session:
        source = await session.get(StoredObject, "stale")
        assert source.knowledge_status == "failed"
        assert source.knowledge_error == (error or RESTART_ERROR)
        assert (await session.get(Job, "job-stale")).status == job_status


async def test_reconciliation_fences_replaced_jobs_terminal_sources_and_unrelated_scopes(restart_factory):
    cases = [
        ("replacement", {"status": "succeeded"}, {}),
        ("ready", {}, {"knowledge_status": "ready"}),
        ("partial", {}, {"knowledge_status": "partial"}),
        ("already-failed", {}, {"knowledge_status": "failed", "knowledge_error": "Keep this error"}),
        ("foreign-job", {"customer_id": 2}, {}),
        ("foreign-source", {}, {"customer_id": 2, "workspace_id": "foreign"}),
        ("wrong-object", {"request": {"object_id": "another-source", "owner_user_id": OWNER_ID}}, {}),
        ("wrong-owner", {"request": {"object_id": "wrong-owner", "owner_user_id": "another-user"}}, {}),
        ("wrong-job-kind", {"kind": "report_generate"}, {}),
        ("wrong-source-kind", {}, {"kind": "report"}),
        ("missing-job", {}, {"knowledge_job_id": None}),
        ("sibling", {"request": {"object_id": "client-a-source", "owner_user_id": OWNER_ID}},
         {"workspace_id": "client-b"}),
    ]
    async with restart_factory.begin() as session:
        for identity, job_values, source_values in cases:
            await _add_source(session, identity, job_values=job_values, source_values=source_values)
        session.add(Job(
            id="old-replacement-job", customer_id=1, kind="document_ingest", status="failed",
            request={"object_id": "replacement", "owner_user_id": OWNER_ID}, error="Old job error",
        ))

    async with restart_factory() as session:
        assert await jobs.fail_interrupted_jobs(session) == 0

    async with restart_factory() as session:
        sources = {row.id: row for row in (await session.scalars(select(StoredObject))).all()}
        for identity, _job_values, source_values in cases:
            assert sources[identity].knowledge_status == source_values.get("knowledge_status", "running")
            assert sources[identity].knowledge_error == source_values.get("knowledge_error")
        assert sources["replacement"].knowledge_job_id == "job-replacement"


async def test_source_and_job_changes_rollback_together_if_startup_commit_fails(restart_factory, monkeypatch):
    async with restart_factory.begin() as session:
        await _add_source(session, "atomic", job_values={"status": "running"})

    async with restart_factory() as session:
        async def fail_commit():
            raise RuntimeError("Startup commit failed")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="Startup commit failed"):
            await jobs.fail_interrupted_jobs(session)
        await session.rollback()

    async with restart_factory() as session:
        assert (await session.get(Job, "job-atomic")).status == "running"
        source = await session.get(StoredObject, "atomic")
        assert source.knowledge_status == "running"
        assert source.knowledge_error is None
