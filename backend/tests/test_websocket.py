"""WebSocket coverage for jobs fan-out and streaming chat."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("CEREBRAS_API_KEY", "test-key-not-real")
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
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.database.base import Base
from app.database.models import Job, SmeExpertTurn, UserAccount, WordAction
from app.database.session import get_session
from app.llm import set_structured_completer, set_text_completer, set_text_streamer
from app.main import create_app
from app.realtime.expertgranskning_broadcast import expertgranskning_broadcast
from app.realtime.research_progress_broadcast import research_progress_broadcast
from app.schemas.domain import FollowUpQuestions
from app.serializers import utcnow
from app.services import jobs as jobs_service
from app.services.execution import create_attempt, create_run
from app.services.expertgranskning import WORD_JOB_KIND
from app.services.expertgranskning.watch import publish_action_created
from app.services.kund_store import (
    BOLAG_DEMO_KUND_SLUG,
    bolag_demo_customer_id,
    ensure_default_kunder,
)
from app.services.prompt_store import ensure_default_configurations
from app.services.research.progress import (
    append_research_progress_event,
    progress_event_to_dict,
)
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


def _research_hello(attempt_id: str, after_sequence: int = 0) -> dict:
    return {
        "type": "hello",
        "scope": "research_watch",
        "attempt_id": attempt_id,
        "after_sequence": after_sequence,
    }


async def _seed_research_attempt(session, *, customer_id: int = 1):
    run = await create_run(
        session,
        customer_id=customer_id,
        module="dd",
        title="Research WS",
        context={"case_id": "ws-research"},
    )
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={"model": "config-a"},
        input_snapshot={"question": "Vad gäller skattesatsen?"},
    )
    return attempt


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


def test_sme_websocket_routes_expert_output_by_thread(ws_client):
    client, _loop = ws_client
    bolag_id = _bolag_customer_id(client)
    enabled = client.patch(f"/kunder/{bolag_id}", json={"product": "sme"})
    assert enabled.status_code == 200
    created = client.post(
        "/personas",
        json={
            "kind": "expert",
            "customer_id": bolag_id,
            "name": "SME-expert",
            "occ": "Analytiker",
            "district": "—",
            "quote": "Testexpert",
            "tools": ["search_companies"],
        },
    )
    assert created.status_code == 201
    persona_id = created.json()["id"]
    os_id = next(
        row["id"]
        for row in client.get("/kunder").json()
        if row["slug"] != BOLAG_DEMO_KUND_SLUG
    )
    other_expert = client.post(
        "/personas",
        json={
            "kind": "expert",
            "customer_id": os_id,
            "name": "Annan kunds expert",
            "occ": "Jurist",
            "district": "—",
            "quote": "Ska inte nås",
        },
    )
    assert other_expert.status_code == 201

    with client.websocket_connect(
        f"/ws/sme?access_token={_bolag_token()}"
    ) as websocket:
        assert websocket.receive_json() == {"type": "ready", "scope": "sme"}
        websocket.send_json(
            {
                "type": "send",
                "request_id": "request-1",
                "thread_type": "expert",
                "thread_id": persona_id,
                "message": "Granska bolaget",
            }
        )
        typing = websocket.receive_json()
        assert typing["type"] == "typing"
        assert typing["thread_id"] == persona_id

        tokens: list[str] = []
        done = None
        for _ in range(10):
            event = websocket.receive_json()
            assert event["thread_id"] == persona_id
            assert event["request_id"] == "request-1"
            if event["type"] == "token":
                tokens.append(event["text"])
            elif event["type"] == "done":
                done = event
                break
        assert tokens == ["Mockad personasvar för tester."]
        assert done is not None
        assert done["reply"] == "Mockad personasvar för tester."

        suggestions = websocket.receive_json()
        assert suggestions["type"] == "suggestions"
        assert suggestions["thread_id"] == persona_id
        assert suggestions["questions"] == [
            "Vad händer sen?",
            "Kan du ge ett exempel?",
            "Hur känner du inför det?",
        ]
        assert websocket.receive_json()["type"] == "typing"

        websocket.send_json(
            {
                "type": "send",
                "request_id": "request-forbidden",
                "thread_type": "expert",
                "thread_id": other_expert.json()["id"],
                "message": "Otillåten fråga",
            }
        )
        assert websocket.receive_json()["type"] == "typing"
        denied = websocket.receive_json()
        assert denied["type"] == "error"
        assert denied["detail"] == "kund_access_denied"


def _enable_sme_expert(client, *, tools: list[str] | None = None) -> str:
    bolag_id = _bolag_customer_id(client)
    enabled = client.patch(f"/kunder/{bolag_id}", json={"product": "sme"})
    assert enabled.status_code == 200
    payload = {
        "kind": "expert",
        "customer_id": bolag_id,
        "name": "SME-reconnect",
        "occ": "Analytiker",
        "district": "—",
        "quote": "Testexpert",
    }
    if tools is not None:
        payload["tools"] = tools
    created = client.post("/personas", json=payload)
    assert created.status_code == 201
    return created.json()["id"]


async def _wait_persisted_expert_turn(
    request_id: str,
    *,
    statuses: set[str] | None = None,
) -> SmeExpertTurn:
    factory = jobs_service.job_session_factory()
    assert factory is not None
    for _ in range(80):
        async with factory() as session:
            turn = await session.get(SmeExpertTurn, request_id)
            if turn is not None and (
                statuses is None or turn.status in statuses
            ):
                return turn
        await asyncio.sleep(0.05)
    raise AssertionError(f"expert turn {request_id} was not persisted")


def _sme_turn_lookup(
    client,
    request_id: str,
    *,
    statuses: set[str] | None = None,
) -> dict:
    client.headers["Authorization"] = f"Bearer {_bolag_token()}"
    for _ in range(80):
        response = client.get(f"/sme/expert-turns/{request_id}")
        if response.status_code == 200:
            body = response.json()
            if statuses is None or body["status"] in statuses:
                return body
        time.sleep(0.05)
    raise AssertionError(f"expert turn {request_id} was not available")


def test_sme_websocket_recovers_turn_after_disconnect_before_token(ws_client):
    client, loop = ws_client
    persona_id = _enable_sme_expert(client, tools=[])
    released = threading.Event()

    async def delayed_stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        await asyncio.get_running_loop().run_in_executor(None, released.wait)
        yield "Svar efter avbrott"

    set_text_streamer(delayed_stream)
    request_id = "reconnect-before-token"
    with client.websocket_connect(f"/ws/sme?access_token={_bolag_token()}") as websocket:
        assert websocket.receive_json() == {"type": "ready", "scope": "sme"}
        websocket.send_json(
            {
                "type": "send",
                "request_id": request_id,
                "thread_type": "expert",
                "thread_id": persona_id,
                "message": "Fråga före token",
            }
        )
        assert websocket.receive_json()["type"] == "typing"
        turn = loop.run_until_complete(_wait_persisted_expert_turn(request_id))
        assert turn.status in {"accepted", "running"}
        assert turn.persona_id == persona_id
        released.set()
        loop.run_until_complete(
            _wait_persisted_expert_turn(request_id, statuses={"succeeded"})
        )

    other = _enable_sme_expert(client, tools=[])
    assert other != persona_id
    body = _sme_turn_lookup(client, request_id, statuses={"succeeded"})
    assert body["thread_id"] == persona_id
    assert body["messages"][-1]["content"] == "Svar efter avbrott"


def test_sme_websocket_recovers_turn_after_disconnect_during_tokens(ws_client):
    client, loop = ws_client
    persona_id = _enable_sme_expert(client, tools=[])
    released = threading.Event()

    async def paused_stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        yield "första"
        await asyncio.get_running_loop().run_in_executor(None, released.wait)
        yield " andra"

    set_text_streamer(paused_stream)
    request_id = "reconnect-during-tokens"
    with client.websocket_connect(f"/ws/sme?access_token={_bolag_token()}") as websocket:
        assert websocket.receive_json() == {"type": "ready", "scope": "sme"}
        websocket.send_json(
            {
                "type": "send",
                "request_id": request_id,
                "thread_type": "expert",
                "thread_id": persona_id,
                "message": "Fråga under svar",
            }
        )
        saw_token = False
        for _ in range(10):
            event = websocket.receive_json()
            if event["type"] == "token":
                saw_token = True
                break
        assert saw_token
        turn = loop.run_until_complete(_wait_persisted_expert_turn(request_id))
        assert turn.status == "running"
        assert turn.persona_id == persona_id
        released.set()
        loop.run_until_complete(
            _wait_persisted_expert_turn(request_id, statuses={"succeeded"})
        )

    body = _sme_turn_lookup(client, request_id, statuses={"succeeded"})
    assert "första" in body["messages"][-1]["content"]
    assert "andra" in body["messages"][-1]["content"]


def test_sme_websocket_rejects_request_id_payload_mismatch(ws_client):
    client, _loop = ws_client
    persona_id = _enable_sme_expert(client, tools=[])
    request_id = "request-payload-conflict"

    async def stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        yield "Första svaret"

    set_text_streamer(stream)
    with client.websocket_connect(f"/ws/sme?access_token={_bolag_token()}") as websocket:
        assert websocket.receive_json() == {"type": "ready", "scope": "sme"}
        websocket.send_json(
            {
                "type": "send",
                "request_id": request_id,
                "thread_type": "expert",
                "thread_id": persona_id,
                "message": "Första frågan",
            }
        )
        while True:
            event = websocket.receive_json()
            if event["type"] == "suggestions":
                break
        assert websocket.receive_json()["type"] == "typing"
        websocket.send_json(
            {
                "type": "send",
                "request_id": request_id,
                "thread_type": "expert",
                "thread_id": persona_id,
                "message": "Annan fråga",
            }
        )
        assert websocket.receive_json()["type"] == "typing"
        denied = websocket.receive_json()
        assert denied["type"] == "error"
        assert denied["detail"] == "request_id conflict"


def _expertgranskning_hello(job_id: str) -> dict:
    return {
        "type": "hello",
        "scope": "expertgranskning_watch",
        "job_id": job_id,
    }


def test_expertgranskning_websocket_replay_live_push_and_patch(ws_client):
    client, loop = ws_client

    async def _seed() -> tuple[str, str]:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            job = Job(
                id="job-ws-egr-replay",
                customer_id=1,
                kind=WORD_JOB_KIND,
                status="running",
                label="Word WS replay",
                request={"panel_id": 1},
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            row = WordAction(
                id="wa_ws_replay",
                job_id=job.id,
                customer_id=1,
                source_type="expert_review_result",
                source_id="egr_ws_replay",
                source_ordinal=0,
                action_type="comment",
                anchor={"paragraph_index": 1, "reviewed_text": "x", "text_hash": "h"},
                content="Första live-raden.",
                status="pending",
                created_at=utcnow(),
            )
            session.add_all([job, row])
            await session.commit()
            return job.id, row.id

    job_id, action_id = loop.run_until_complete(_seed())
    token = _admin_token()
    with client.websocket_connect(f"/ws/expertgranskning?access_token={token}") as ws:
        ws.send_json(_expertgranskning_hello(job_id))
        replay = ws.receive_json()
        assert replay["type"] == "expertgranskning.replay"
        assert replay["job_id"] == job_id
        assert replay["status"] == "running"
        assert len(replay["actions"]) == 1
        assert replay["actions"][0]["id"] == action_id
        assert replay["actions"][0]["content"] == "Första live-raden."

        async def _push_created() -> None:
            factory = jobs_service.job_session_factory()
            async with factory() as session:
                created = WordAction(
                    id="wa_ws_live",
                    job_id=job_id,
                    customer_id=1,
                    source_type="expert_review_result",
                    source_id="egr_ws_live",
                    source_ordinal=0,
                    action_type="comment",
                    anchor={"paragraph_index": 2, "reviewed_text": "y", "text_hash": "h2"},
                    content="Andra live-raden.",
                    status="pending",
                    created_at=utcnow(),
                )
                session.add(created)
                await session.commit()
                await session.refresh(created)
                await publish_action_created(created)

        loop.run_until_complete(_push_created())
        created_event = ws.receive_json()
        assert created_event["type"] == "expertgranskning.action.created"
        assert created_event["action"]["id"] == "wa_ws_live"
        assert created_event["action"]["action_type"] == "comment"

        claimed = client.post(
            f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/claim",
            json={"application_id": "app-ws-replay"},
        )
        assert claimed.status_code == 200, claimed.text
        claimed_event = ws.receive_json()
        assert claimed_event["type"] == "expertgranskning.action.updated"
        assert claimed_event["action"]["status"] == "applying"
        completed = client.post(
            f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/complete",
            json={"application_id": "app-ws-replay", "word_artifact_id": "word-cmt-1"},
        )
        assert completed.status_code == 200, completed.text
        updated_event = ws.receive_json()
        assert updated_event["type"] == "expertgranskning.action.updated"
        assert updated_event["action"]["id"] == action_id
        assert updated_event["action"]["word_artifact_id"] == "word-cmt-1"
        assert updated_event["action"]["status"] == "applied"


def test_expertgranskning_websocket_subscribe_before_snapshot_keeps_race_write(
    ws_client, monkeypatch
):
    """A write between subscribe and snapshot must land as created + replay."""
    client, loop = ws_client

    async def _seed() -> str:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            job = Job(
                id="job-ws-egr-race",
                customer_id=1,
                kind=WORD_JOB_KIND,
                status="running",
                label="Word WS race",
                request={"panel_id": 1},
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(job)
            await session.commit()
            return job.id

    job_id = loop.run_until_complete(_seed())
    real_subscribe = expertgranskning_broadcast.subscribe

    async def _subscribe_then_write(subscribed_job_id: str, websocket) -> None:
        await real_subscribe(subscribed_job_id, websocket)
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            created = WordAction(
                id="wa_ws_race",
                job_id=subscribed_job_id,
                customer_id=1,
                source_type="expert_review_result",
                source_id="egr_ws_race",
                source_ordinal=0,
                action_type="comment",
                anchor={"paragraph_index": 3, "reviewed_text": "z", "text_hash": "h3"},
                content="Skrivet mellan subscribe och snapshot.",
                status="pending",
                created_at=utcnow(),
            )
            session.add(created)
            await session.commit()
            await session.refresh(created)
            await publish_action_created(created)

    monkeypatch.setattr(expertgranskning_broadcast, "subscribe", _subscribe_then_write)

    token = _admin_token()
    with client.websocket_connect(f"/ws/expertgranskning?access_token={token}") as ws:
        ws.send_json(_expertgranskning_hello(job_id))
        first = ws.receive_json()
        second = ws.receive_json()

    by_type = {event["type"]: event for event in (first, second)}
    assert set(by_type) == {
        "expertgranskning.action.created",
        "expertgranskning.replay",
    }
    assert by_type["expertgranskning.action.created"]["action"]["id"] == "wa_ws_race"
    replay_ids = [row["id"] for row in by_type["expertgranskning.replay"]["actions"]]
    assert replay_ids == ["wa_ws_race"]


def test_expertgranskning_websocket_bolag_denied_foreign_job(ws_client):
    client, loop = ws_client

    async def _seed() -> str:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            job = Job(
                id="job-ws-egr-os",
                customer_id=1,
                kind=WORD_JOB_KIND,
                status="pending",
                label="OS word job",
                request={"panel_id": 1},
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(job)
            await session.commit()
            return job.id

    job_id = loop.run_until_complete(_seed())
    bolag_token = _bolag_token()
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            f"/ws/expertgranskning?access_token={bolag_token}"
        ) as ws:
            ws.send_json(_expertgranskning_hello(job_id))
            ws.receive_json()
    assert exc.value.code == 4403


def test_expertgranskning_websocket_bolag_can_watch_own_job(ws_client):
    client, loop = ws_client
    bolag_id = _bolag_customer_id(client)

    async def _seed() -> str:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            job = Job(
                id="job-ws-egr-bolag",
                customer_id=bolag_id,
                kind=WORD_JOB_KIND,
                status="pending",
                label="Bolag word job",
                request={"panel_id": 1},
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(job)
            await session.commit()
            return job.id

    job_id = loop.run_until_complete(_seed())
    bolag_token = _bolag_token()
    with client.websocket_connect(
        f"/ws/expertgranskning?access_token={bolag_token}"
    ) as ws:
        ws.send_json(_expertgranskning_hello(job_id))
        replay = ws.receive_json()
        assert replay["type"] == "expertgranskning.replay"
        assert replay["job_id"] == job_id
        assert replay["actions"] == []


def test_expertgranskning_websocket_unknown_or_wrong_kind_closes(ws_client):
    client, loop = ws_client

    async def _seed_other_kind() -> str:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            job = Job(
                id="job-ws-egr-wrong-kind",
                customer_id=1,
                kind="panel_session_run",
                status="pending",
                label="Not a word job",
                request={"session_id": "panel_x"},
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(job)
            await session.commit()
            return job.id

    other_id = loop.run_until_complete(_seed_other_kind())
    token = _admin_token()
    for job_id in ("job-does-not-exist", other_id):
        with client.websocket_connect(
            f"/ws/expertgranskning?access_token={token}"
        ) as ws:
            ws.send_json(_expertgranskning_hello(job_id))
            error = ws.receive_json()
            assert error["type"] == "error"
            assert error["detail"] == "Word review job not found"
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 1003


def test_research_websocket_replay_and_live_push(ws_client):
    client, loop = ws_client

    async def _seed() -> tuple[str, int]:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            attempt = await _seed_research_attempt(session)
            first = await append_research_progress_event(
                session,
                attempt_id=attempt.id,
                event_type="objective_accepted",
                idempotency_key="objective_accepted",
                payload={"objective_preview": "Kartlägg skattesatsen"},
            )
            await session.commit()
            return attempt.id, first.sequence

    attempt_id, first_sequence = loop.run_until_complete(_seed())
    token = _admin_token()
    with client.websocket_connect(f"/ws/research?access_token={token}") as ws:
        ws.send_json(_research_hello(attempt_id))
        replay = ws.receive_json()
        assert replay["type"] == "research.progress.replay"
        assert replay["attempt_id"] == attempt_id
        assert replay["after_sequence"] == 0
        assert [row["event_type"] for row in replay["events"]] == ["objective_accepted"]
        assert replay["events"][0]["sequence"] == first_sequence

        async def _push_live() -> None:
            factory = jobs_service.job_session_factory()
            async with factory() as session:
                row = await append_research_progress_event(
                    session,
                    attempt_id=attempt_id,
                    event_type="initial_plan_accepted",
                    idempotency_key="initial_plan_accepted",
                    payload={"need_count": 1, "need_ids": ["research_1"]},
                )
                await session.commit()
                await research_progress_broadcast.publish(
                    attempt_id, progress_event_to_dict(row)
                )

        loop.run_until_complete(_push_live())
        live = ws.receive_json()
        assert live["type"] == "research.progress"
        assert live["event_type"] == "initial_plan_accepted"
        assert live["attempt_id"] == attempt_id
        assert live["sequence"] == first_sequence + 1


def test_research_websocket_subscribe_before_snapshot_keeps_race_write(
    ws_client, monkeypatch
):
    """A persist+publish between subscribe and snapshot must not vanish."""
    client, loop = ws_client

    async def _seed() -> str:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            attempt = await _seed_research_attempt(session)
            await session.commit()
            return attempt.id

    attempt_id = loop.run_until_complete(_seed())
    real_subscribe = research_progress_broadcast.subscribe

    async def _subscribe_then_write(subscribed_attempt_id: str, websocket) -> None:
        await real_subscribe(subscribed_attempt_id, websocket)
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            row = await append_research_progress_event(
                session,
                attempt_id=subscribed_attempt_id,
                event_type="research_need_planned",
                idempotency_key="need_planned:research_1",
                payload={"research_need_id": "research_1", "origin": "initial"},
            )
            await session.commit()
            await research_progress_broadcast.publish(
                subscribed_attempt_id, progress_event_to_dict(row)
            )

    monkeypatch.setattr(research_progress_broadcast, "subscribe", _subscribe_then_write)

    token = _admin_token()
    with client.websocket_connect(f"/ws/research?access_token={token}") as ws:
        ws.send_json(_research_hello(attempt_id))
        first = ws.receive_json()
        second = ws.receive_json()

    by_type = {event["type"]: event for event in (first, second)}
    assert set(by_type) == {"research.progress", "research.progress.replay"}
    assert by_type["research.progress"]["event_type"] == "research_need_planned"
    replay_types = [row["event_type"] for row in by_type["research.progress.replay"]["events"]]
    assert replay_types == ["research_need_planned"]
    assert (
        by_type["research.progress"]["id"]
        == by_type["research.progress.replay"]["events"][0]["id"]
    )


def test_research_websocket_reconnect_after_sequence(ws_client):
    client, loop = ws_client

    async def _seed() -> tuple[str, int]:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            attempt = await _seed_research_attempt(session)
            await append_research_progress_event(
                session,
                attempt_id=attempt.id,
                event_type="objective_accepted",
                idempotency_key="objective_accepted",
                payload={"objective_preview": "Kartlägg skattesatsen"},
            )
            second = await append_research_progress_event(
                session,
                attempt_id=attempt.id,
                event_type="initial_plan_accepted",
                idempotency_key="initial_plan_accepted",
                payload={"need_count": 1},
            )
            await session.commit()
            return attempt.id, second.sequence - 1

    attempt_id, cursor = loop.run_until_complete(_seed())
    token = _admin_token()
    with client.websocket_connect(f"/ws/research?access_token={token}") as ws:
        ws.send_json(_research_hello(attempt_id, after_sequence=cursor))
        replay = ws.receive_json()
        assert replay["after_sequence"] == cursor
        assert [row["event_type"] for row in replay["events"]] == [
            "initial_plan_accepted"
        ]


def test_research_websocket_bolag_denied_foreign_attempt(ws_client):
    client, loop = ws_client

    async def _seed() -> str:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            attempt = await _seed_research_attempt(session, customer_id=1)
            await session.commit()
            return attempt.id

    attempt_id = loop.run_until_complete(_seed())
    bolag_token = _bolag_token()
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect(f"/ws/research?access_token={bolag_token}") as ws,
    ):
        ws.send_json(_research_hello(attempt_id))
        ws.receive_json()
    assert exc.value.code == 4403
