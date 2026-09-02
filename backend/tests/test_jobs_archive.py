"""Archive finished background jobs (hide from the default list)."""

from __future__ import annotations

import pytest

from app.database.models import Job
from app.serializers import utcnow
from tests.conftest import TEST_CUSTOMER_ID


def _job(**overrides: object) -> Job:
    now = utcnow()
    values: dict[str, object] = {
        "id": "job-archive-1",
        "customer_id": TEST_CUSTOMER_ID,
        "kind": "report_generate",
        "status": "succeeded",
        "label": "Klar rapport",
        "request": {},
        "result": {"report_id": "rpt-1"},
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return Job(**values)


@pytest.mark.asyncio
async def test_archive_hides_job_from_default_list(client_db) -> None:
    client, factory = client_db
    async with factory() as session:
        session.add(_job())
        await session.commit()

    listed = await client.get("/jobs")
    assert listed.status_code == 200
    assert any(row["id"] == "job-archive-1" for row in listed.json())

    archived = await client.patch("/jobs/job-archive-1", json={"archived": True})
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None

    hidden = await client.get("/jobs")
    assert hidden.status_code == 200
    assert all(row["id"] != "job-archive-1" for row in hidden.json())

    still_there = await client.get("/jobs/job-archive-1")
    assert still_there.status_code == 200
    assert still_there.json()["archived_at"] is not None

    only_archived = await client.get("/jobs", params={"archived_only": True})
    assert only_archived.status_code == 200
    assert any(row["id"] == "job-archive-1" for row in only_archived.json())

    with_archived = await client.get("/jobs", params={"include_archived": True})
    assert with_archived.status_code == 200
    assert any(row["id"] == "job-archive-1" for row in with_archived.json())


@pytest.mark.asyncio
async def test_unarchive_returns_job_to_list(client_db) -> None:
    client, factory = client_db
    async with factory() as session:
        session.add(_job(id="job-unarchive", archived_at=utcnow()))
        await session.commit()

    listed = await client.get("/jobs")
    assert all(row["id"] != "job-unarchive" for row in listed.json())

    restored = await client.patch("/jobs/job-unarchive", json={"archived": False})
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None

    visible = await client.get("/jobs")
    assert any(row["id"] == "job-unarchive" for row in visible.json())


@pytest.mark.asyncio
async def test_cannot_archive_running_job(client_db) -> None:
    client, factory = client_db
    async with factory() as session:
        session.add(_job(id="job-running", status="running", result=None))
        await session.commit()

    response = await client.patch("/jobs/job-running", json={"archived": True})
    assert response.status_code == 409

    listed = await client.get("/jobs")
    assert any(row["id"] == "job-running" for row in listed.json())


@pytest.mark.asyncio
async def test_archive_finished_archives_succeeded_and_failed(client_db) -> None:
    client, factory = client_db
    now = utcnow()
    async with factory() as session:
        session.add(_job(id="job-ok", status="succeeded"))
        session.add(
            _job(
                id="job-fail",
                status="failed",
                error="boom",
                result=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(_job(id="job-pending", status="pending", result=None))
        await session.commit()

    response = await client.post("/jobs/archive-finished")
    assert response.status_code == 200
    archived_ids = {row["id"] for row in response.json()}
    assert archived_ids == {"job-ok", "job-fail"}

    listed = await client.get("/jobs")
    ids = {row["id"] for row in listed.json()}
    assert "job-pending" in ids
    assert "job-ok" not in ids
    assert "job-fail" not in ids


@pytest.mark.asyncio
async def test_user_cannot_archive_other_kund_job(client_db, user_client) -> None:
    _client, factory = client_db
    async with factory() as session:
        session.add(_job(id="job-other", customer_id=2))
        await session.commit()

    response = await user_client.patch("/jobs/job-other", json={"archived": True})
    assert response.status_code == 403
