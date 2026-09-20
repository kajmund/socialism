"""Resume failed expert research jobs from the jobs API."""

from __future__ import annotations

import asyncio

import pytest

from app.database.models import Job, Persona
from app.serializers import utcnow
from app.services import jobs as jobs_service
from tests.conftest import TEST_CUSTOMER_ID


def _job(**overrides: object) -> Job:
    now = utcnow()
    values: dict[str, object] = {
        "id": "job-resume-1",
        "customer_id": TEST_CUSTOMER_ID,
        "kind": "expert_chat_research",
        "status": "failed",
        "label": "Expertresearch: Klausul 2",
        "request": {
            "persona_id": "expert-resume-1",
            "specific_question": "Vad innebär klausul 2?",
            "question": "Vilka rekvisit gäller?",
        },
        "result": {"attempt_id": "attempt-resume-1"},
        "error": "Avbrutet av serveromstart",
        "created_at": now,
        "started_at": now,
        "finished_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return Job(**values)


async def _expert(session) -> Persona:
    expert = Persona(
        id="expert-resume-1",
        customer_id=TEST_CUSTOMER_ID,
        kind="expert",
        name="Avtalsjuristen",
        age=None,
        occ="Jurist",
        district="—",
        quote="",
        origin="test",
        profile={},
        tools=None,
    )
    session.add(expert)
    return expert


@pytest.mark.asyncio
async def test_concurrent_resume_only_requeues_once(client_db, monkeypatch) -> None:
    client, factory = client_db
    scheduled: list[str] = []
    monkeypatch.setattr(jobs_service, "enqueue_job", scheduled.append)
    async with factory() as session:
        await _expert(session)
        session.add(_job())
        await session.commit()

    async def resume_once() -> int:
        response = await client.post("/jobs/job-resume-1/resume")
        return response.status_code

    first, second = await asyncio.gather(resume_once(), resume_once())
    assert sorted([first, second]) == [200, 409]
    assert scheduled == ["job-resume-1"]


@pytest.mark.asyncio
async def test_mark_job_running_is_single_claim(client_db) -> None:
    _, factory = client_db
    async with factory() as session:
        await _expert(session)
        session.add(_job(status="pending", error=None, finished_at=None))
        await session.commit()

    first = await jobs_service._mark_job_running("job-resume-1")
    second = await jobs_service._mark_job_running("job-resume-1")
    assert first == "expert_chat_research"
    assert second is None


@pytest.mark.asyncio
async def test_resume_failed_expert_research_job(client_db, monkeypatch) -> None:
    client, factory = client_db
    scheduled: list[str] = []
    monkeypatch.setattr(jobs_service, "enqueue_job", scheduled.append)
    async with factory() as session:
        await _expert(session)
        session.add(_job())
        await session.commit()

    resumed = await client.post("/jobs/job-resume-1/resume")
    assert resumed.status_code == 200
    body = resumed.json()
    assert body["status"] == "pending"
    assert body["error"] is None
    assert body["started_at"] is None
    assert body["finished_at"] is None
    assert body["result"]["attempt_id"] == "attempt-resume-1"
    assert scheduled == ["job-resume-1"]


@pytest.mark.asyncio
async def test_resume_rejects_running_and_other_kinds(client_db) -> None:
    client, factory = client_db
    async with factory() as session:
        await _expert(session)
        session.add(_job(id="job-running", status="running", error=None, finished_at=None))
        session.add(
            _job(
                id="job-report",
                kind="report_generate",
                request={"report_id": "rpt-1"},
                result={"report_id": "rpt-1"},
            )
        )
        await session.commit()

    running = await client.post("/jobs/job-running/resume")
    assert running.status_code == 409
    other = await client.post("/jobs/job-report/resume")
    assert other.status_code == 409
    missing = await client.post("/jobs/job-missing/resume")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_rerun_succeeded_expert_research_job(client_db, monkeypatch) -> None:
    client, factory = client_db
    scheduled: list[str] = []
    monkeypatch.setattr(jobs_service, "enqueue_job", scheduled.append)
    async with factory() as session:
        await _expert(session)
        session.add(
            _job(
                id="job-rerun-1",
                status="succeeded",
                error=None,
                result={"attempt_id": "attempt-old-1"},
            )
        )
        await session.commit()

    created = await client.post("/jobs/job-rerun-1/rerun")
    assert created.status_code == 202
    body = created.json()
    assert body["id"] != "job-rerun-1"
    assert body["status"] == "pending"
    assert body["kind"] == "expert_chat_research"
    assert body["label"] == "Expertresearch: Klausul 2"
    assert body["request"] == {
        "persona_id": "expert-resume-1",
        "specific_question": "Vad innebär klausul 2?",
        "question": "Vilka rekvisit gäller?",
    }
    assert body["result"] is None
    assert scheduled == [body["id"]]

    original = await client.get("/jobs/job-rerun-1")
    assert original.status_code == 200
    assert original.json()["status"] == "succeeded"
    assert original.json()["result"]["attempt_id"] == "attempt-old-1"


@pytest.mark.asyncio
async def test_rerun_rejects_running_and_other_kinds(client_db) -> None:
    client, factory = client_db
    async with factory() as session:
        await _expert(session)
        session.add(_job(id="job-running", status="running", error=None, finished_at=None))
        session.add(
            _job(
                id="job-report",
                kind="report_generate",
                request={"report_id": "rpt-1"},
                result={"report_id": "rpt-1"},
            )
        )
        await session.commit()

    running = await client.post("/jobs/job-running/rerun")
    assert running.status_code == 409
    other = await client.post("/jobs/job-report/rerun")
    assert other.status_code == 409
    missing = await client.post("/jobs/job-missing/rerun")
    assert missing.status_code == 404
