"""WebSocket coverage for jobs fan-out and streaming chat."""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key-not-real")

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.config import settings
from app.database.base import Base
from app.database.session import get_session
from app.llm import set_text_completer, set_text_streamer
from app.main import create_app
from app.services import jobs as jobs_service
from app.services.population_generate import clear_generations
from app.services.prompt_store import ensure_default_configurations


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


@pytest.fixture
def ws_client():
    clear_generations()
    settings.persona_generator = "stub"
    settings.deepseek_api_key = "test-key-not-real"
    settings.simulation_engine = "none"

    async def _mock_text(_messages: list[dict[str, str]]) -> str:
        return "Mockad personasvar för tester."

    async def _mock_stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        for piece in ("Hej", " från", " stream"):
            yield piece

    set_text_completer(_mock_text)
    set_text_streamer(_mock_stream)

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    loop = asyncio.new_event_loop()

    async def _prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as seed_session:
            await ensure_default_configurations(seed_session)

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

    with TestClient(app) as client:
        yield client, loop

    jobs_service.set_job_session_factory(None)
    jobs_service.set_schedule_hook(None)
    set_text_completer(None)
    set_text_streamer(None)
    loop.run_until_complete(engine.dispose())
    loop.close()


def test_jobs_websocket_snapshot_and_update(ws_client):
    client, loop = ws_client
    with client.websocket_connect("/ws/jobs") as ws:
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

    with client.websocket_connect("/ws/chat") as ws:
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
