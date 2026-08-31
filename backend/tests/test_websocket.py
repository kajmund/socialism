"""WebSocket coverage for jobs fan-out and streaming chat."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key-not-real")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-supabase-jwt-secret-not-real")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-supabase-service-role-not-real")

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.config import settings
from app.database.base import Base
from app.database.models import UserAccount
from app.database.session import get_session
from app.llm import set_structured_completer, set_text_completer, set_text_streamer
from app.main import create_app
from app.schemas.domain import FollowUpQuestions
from app.services import jobs as jobs_service
from app.services.kund_store import (
    BOLAG_DEMO_KUND_SLUG,
    bolag_demo_customer_id,
    ensure_default_kunder,
)
from app.services.prompt_store import ensure_default_configurations
from tests.conftest import (
    ADMIN_USER_ID,
    BOLAG_USER_ID,
    TEST_JWT_SECRET,
    mint_access_token,
)


def _sample_recipe(*, size: int = 2, seed: int = 1) -> dict:
    return {
        "size": size,
        "locale": "local",
        "seed": seed,
        "dist": {
            "age": {
                "label": "Ålder",
                "rows": [
                    {"k": "ung", "l": "Ung", "v": 50},
                    {"k": "medel", "l": "Medel", "v": 50},
                ],
            },
            "district": {
                "label": "Ort",
                "rows": [
                    {"k": "centrum", "l": "Centrum", "v": 100},
                ],
            },
            "occupation": {
                "label": "Yrke",
                "rows": [
                    {"k": "vard", "l": "Vård", "v": 100},
                ],
            },
            "leaning": {
                "label": "Lutning",
                "rows": [
                    {"k": "mitt", "l": "Mitt", "v": 100},
                ],
            },
        },
    }


def _admin_token() -> str:
    return mint_access_token(sub=ADMIN_USER_ID, email="admin@test.local")


def _bolag_token() -> str:
    return mint_access_token(sub=BOLAG_USER_ID, email="bolag@test.local")


@pytest.fixture
def ws_client():
    settings.persona_generator = "stub"
    settings.deepseek_api_key = "test-key-not-real"
    settings.supabase_jwt_secret = TEST_JWT_SECRET
    settings.simulation_engine = "none"

    async def _mock_text(_messages: list[dict[str, str]]) -> str:
        return "Mockad personasvar för tester."

    async def _mock_stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        for piece in ("Hej", " från", " stream"):
            yield piece

    async def _mock_structured(_messages: list[dict[str, str]], response_model: type):
        if response_model is FollowUpQuestions:
            return FollowUpQuestions(
                questions=["Vad händer sen?", "Kan du ge ett exempel?", "Hur känner du inför det?"]
            )
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_text_completer(_mock_text)
    set_text_streamer(_mock_stream)
    set_structured_completer(_mock_structured)

    # File-backed SQLite so the fixture loop (seed/publish) and TestClient's
    # anyio loop (snapshot queries) share one durable DB. :memory: + StaticPool
    # can hide committed rows across those loops.
    tmpdir = tempfile.mkdtemp(prefix="ws-client-db-")
    db_path = Path(tmpdir) / "ws.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    loop = asyncio.new_event_loop()

    async def _prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as seed_session:
            await ensure_default_configurations(seed_session)
            await ensure_default_kunder(seed_session)
            bolag_id = await bolag_demo_customer_id(seed_session)
            seed_session.add(
                UserAccount(
                    id=ADMIN_USER_ID,
                    email="admin@test.local",
                    role="admin",
                    kund_id=None,
                )
            )
            seed_session.add(
                UserAccount(
                    id=BOLAG_USER_ID,
                    email="bolag@test.local",
                    role="bolag",
                    kund_id=bolag_id,
                )
            )
            await seed_session.commit()

    loop.run_until_complete(_prepare())

    jobs_service.set_job_session_factory(session_factory)
    jobs_service.set_schedule_hook(lambda _job_id: None)
    jobs_service.reset_simulation_job_semaphore()
    settings.max_concurrent_simulation_jobs = 2

    app = create_app()

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    admin_token = _admin_token()
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = f"Bearer {admin_token}"
            yield client, loop
    finally:
        jobs_service.set_job_session_factory(None)
        jobs_service.set_schedule_hook(None)
        set_text_completer(None)
        set_text_streamer(None)
        set_structured_completer(None)
        loop.run_until_complete(engine.dispose())
        loop.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


def _jobs_hello(*, customer_id: int | None = None) -> dict:
    hello: dict = {"type": "hello", "scope": "jobs_watch"}
    if customer_id is not None:
        hello["customer_id"] = customer_id
    return hello


def _reports_hello(*, customer_id: int | None = None) -> dict:
    hello: dict = {"type": "hello", "scope": "reports_watch"}
    if customer_id is not None:
        hello["customer_id"] = customer_id
    return hello


def _bolag_customer_id(client) -> int:
    listed = client.get("/kunder")
    assert listed.status_code == 200
    return next(row["id"] for row in listed.json() if row["slug"] == BOLAG_DEMO_KUND_SLUG)


def test_jobs_websocket_snapshot_and_update(ws_client):
    client, loop = ws_client
    token = _admin_token()
    with client.websocket_connect(f"/ws/jobs?access_token={token}") as ws:
        ws.send_json(_jobs_hello())
        snap = ws.receive_json()
        assert snap["type"] == "jobs.snapshot"
        assert snap["jobs"] == []

        created = client.post(
            "/jobs",
            json={
                "kind": "population_generate",
                "label": "WS-pop",
                "request": {
                    "name": "WS-pop",
                    "recipe": _sample_recipe(size=2, seed=1),
                },
            },
        )
        assert created.status_code == 202
        pending_event = ws.receive_json()
        assert pending_event["type"] == "job.updated"
        assert pending_event["job"]["status"] == "pending"
        job_id = pending_event["job"]["id"]

        loop.run_until_complete(jobs_service._run_job(job_id))

        statuses: list[str] = []
        while "succeeded" not in statuses and len(statuses) < 5:
            event = ws.receive_json()
            assert event["type"] == "job.updated"
            statuses.append(event["job"]["status"])
        assert "succeeded" in statuses


def test_reports_websocket_snapshot_update_and_delete(ws_client):
    from app.database.models import Report
    from app.serializers import utcnow
    from app.services.report_realtime import publish_report

    client, loop = ws_client

    async def _seed_report() -> str:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            report = Report(
                id="rpt_ws_test",
                customer_id=1,
                status="pending",
                title="WS report",
                locale="sv",
                mode="quick",
                sources=[],
                html_path=None,
                slots_path=None,
                job_id=None,
                error=None,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(report)
            await session.commit()
            await publish_report(report)
            return report.id

    token = _admin_token()
    with client.websocket_connect(f"/ws/reports?access_token={token}") as ws:
        ws.send_json(_reports_hello())
        snap = ws.receive_json()
        assert snap["type"] == "reports.snapshot"
        assert snap["reports"] == []

        report_id = loop.run_until_complete(_seed_report())
        created_event = ws.receive_json()
        assert created_event["type"] == "report.updated"
        assert created_event["report"]["id"] == report_id
        assert created_event["report"]["status"] == "pending"

        async def _mark_running() -> None:
            factory = jobs_service.job_session_factory()
            async with factory() as session:
                report = await session.get(Report, report_id)
                assert report is not None
                report.status = "running"
                report.updated_at = utcnow()
                await session.commit()
                await publish_report(report)

        loop.run_until_complete(_mark_running())
        running_event = ws.receive_json()
        assert running_event["type"] == "report.updated"
        assert running_event["report"]["status"] == "running"

        deleted = client.delete(f"/reports/{report_id}")
        assert deleted.status_code == 204
        deleted_event = ws.receive_json()
        assert deleted_event["type"] == "report.deleted"
        assert deleted_event["ids"] == [report_id]
        assert deleted_event["customer_id"] == 1


def test_jobs_websocket_customer_scope_filters_push(ws_client):
    from app.database.models import Job
    from app.serializers import utcnow
    from app.services.jobs import publish_job

    client, loop = ws_client
    bolag_id = _bolag_customer_id(client)
    os_id = 1

    async def _seed_jobs() -> None:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            os_job = Job(
                id="job-ws-os",
                customer_id=os_id,
                kind="panel_session_run",
                status="pending",
                label="OS job",
                request={"session_id": "panel_os"},
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            bolag_job = Job(
                id="job-ws-bolag",
                customer_id=bolag_id,
                kind="panel_session_run",
                status="pending",
                label="Bolag job",
                request={"session_id": "panel_bolag"},
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add_all([os_job, bolag_job])
            await session.commit()
            await publish_job(os_job)
            await publish_job(bolag_job)

    admin_token = _admin_token()
    with client.websocket_connect(f"/ws/jobs?access_token={admin_token}") as admin_ws:
        admin_ws.send_json(_jobs_hello())
        admin_snap = admin_ws.receive_json()
        assert admin_snap["type"] == "jobs.snapshot"

        loop.run_until_complete(_seed_jobs())

        admin_os = admin_ws.receive_json()
        assert admin_os["type"] == "job.updated"
        assert admin_os["job"]["id"] == "job-ws-os"

        admin_bolag = admin_ws.receive_json()
        assert admin_bolag["type"] == "job.updated"
        assert admin_bolag["job"]["id"] == "job-ws-bolag"

    bolag_token = _bolag_token()
    with client.websocket_connect(f"/ws/jobs?access_token={bolag_token}") as bolag_ws:
        bolag_ws.send_json(_jobs_hello(customer_id=bolag_id))
        bolag_snap = bolag_ws.receive_json()
        assert bolag_snap["type"] == "jobs.snapshot"
        snap_ids = {row["id"] for row in bolag_snap["jobs"]}
        assert "job-ws-bolag" in snap_ids
        assert "job-ws-os" not in snap_ids

        async def _publish_os_only() -> None:
            factory = jobs_service.job_session_factory()
            async with factory() as session:
                job = await session.get(Job, "job-ws-os")
                assert job is not None
                job.status = "running"
                job.updated_at = utcnow()
                await session.commit()
                await publish_job(job)

        loop.run_until_complete(_publish_os_only())

        with pytest.raises(Exception):
            bolag_ws.receive_json(timeout=0.2)


def test_reports_websocket_customer_scope_filters_push(ws_client):
    from app.database.models import Report
    from app.serializers import utcnow
    from app.services.report_realtime import publish_report

    client, loop = ws_client
    bolag_id = _bolag_customer_id(client)
    os_id = 1

    async def _seed_reports() -> None:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            os_report = Report(
                id="rpt-ws-os",
                customer_id=os_id,
                status="pending",
                title="OS report",
                locale="sv",
                mode="quick",
                sources=[],
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            bolag_report = Report(
                id="rpt-ws-bolag",
                customer_id=bolag_id,
                status="pending",
                title="Bolag report",
                locale="sv",
                mode="dd",
                sources=[],
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add_all([os_report, bolag_report])
            await session.commit()
            await publish_report(os_report)
            await publish_report(bolag_report)

    admin_token = _admin_token()
    with client.websocket_connect(f"/ws/reports?access_token={admin_token}") as admin_ws:
        admin_ws.send_json(_reports_hello())
        admin_snap = admin_ws.receive_json()
        assert admin_snap["type"] == "reports.snapshot"

        loop.run_until_complete(_seed_reports())

        admin_os = admin_ws.receive_json()
        assert admin_os["type"] == "report.updated"
        assert admin_os["report"]["id"] == "rpt-ws-os"

        admin_bolag = admin_ws.receive_json()
        assert admin_bolag["type"] == "report.updated"
        assert admin_bolag["report"]["id"] == "rpt-ws-bolag"

    bolag_token = _bolag_token()
    with client.websocket_connect(f"/ws/reports?access_token={bolag_token}") as bolag_ws:
        bolag_ws.send_json(_reports_hello(customer_id=bolag_id))
        bolag_snap = bolag_ws.receive_json()
        assert bolag_snap["type"] == "reports.snapshot"
        snap_ids = {row["id"] for row in bolag_snap["reports"]}
        assert "rpt-ws-bolag" in snap_ids
        assert "rpt-ws-os" not in snap_ids

        async def _publish_os_only() -> None:
            factory = jobs_service.job_session_factory()
            async with factory() as session:
                report = await session.get(Report, "rpt-ws-os")
                assert report is not None
                report.status = "running"
                report.updated_at = utcnow()
                await session.commit()
                await publish_report(report)

        loop.run_until_complete(_publish_os_only())

        with pytest.raises(Exception):
            bolag_ws.receive_json(timeout=0.2)


def test_chat_websocket_streams_tokens(ws_client):
    client, _loop = ws_client
    generated = client.post(
        "/personas/generate",
        json={"mode": "beskrivning", "freeText": "cynisk undersköterska", "count": 1},
    )
    assert generated.status_code == 200
    candidate = generated.json()["candidates"][0]
    created = client.post(
        "/personas",
        json={
            "name": candidate["name"],
            "age": int("".join(ch for ch in candidate["age"] if ch.isdigit()) or "40"),
            "occ": candidate["yrke"],
            "district": candidate["ort"],
            "quote": candidate.get("ton", ""),
            "origin": "beskrivning",
            "profile": candidate,
        },
    )
    assert created.status_code == 201
    persona_id = created.json()["id"]

    token = _admin_token()
    with client.websocket_connect(f"/ws/chat?access_token={token}") as ws:
        ws.send_json(
            {
                "type": "hello",
                "scope": "library",
                "persona_id": persona_id,
                "mode": "interview",
            }
        )
        ready = ws.receive_json()
        assert ready["type"] == "ready"

        ws.send_json({"type": "send", "message": "Hej, hur mår du?"})
        typing = ws.receive_json()
        assert typing == {"type": "typing", "on": True}

        tokens: list[str] = []
        done = None
        for _ in range(10):
            event = ws.receive_json()
            if event["type"] == "token":
                tokens.append(event["text"])
            elif event["type"] == "done":
                done = event
                break
            elif event["type"] == "error":
                pytest.fail(event["detail"])

        assert tokens == ["Hej", " från", " stream"]
        assert done is not None
        assert done["reply"] == "Hej från stream"
        assert len(done["messages"]) >= 2

        suggestions = ws.receive_json()
        assert suggestions["type"] == "suggestions"
        assert suggestions["questions"] == [
            "Vad händer sen?",
            "Kan du ge ett exempel?",
            "Hur känner du inför det?",
        ]
