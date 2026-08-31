"""API tests for post-hoc run-scoped persona interviews."""

from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.database.models import Persona, Population, PopulationMember, Run, UserAccount
from app.database.session import get_session
from app.llm import set_text_completer
from app.main import create_app
from app.serializers import utcnow
from app.services import jobs as jobs_service
from app.services.kund_store import ensure_default_kunder
from tests.conftest import ADMIN_USER_ID, TEST_JWT_SECRET, mint_access_token


def _variant_payload(persona_id: str) -> dict:
    return {
        "id": "main",
        "label": "Huvudtidslinje",
        "ticks_run": 2,
        "agents": [
            {
                "index": 0,
                "username": "anna",
                "member_name": "Anna",
                "persona_id": persona_id,
                "role": "population",
            }
        ],
        "tick_markers": [
            {
                "tick_index": 0,
                "day": 1,
                "silent": False,
                "key": "t1",
                "rounds": 1,
                "time_start": 0,
                "time_end": 10,
            },
            {
                "tick_index": 1,
                "day": 2,
                "silent": False,
                "key": "t2",
                "rounds": 1,
                "time_start": 11,
                "time_end": 20,
            },
        ],
        "posts": [
            {
                "post_id": 1,
                "user_id": 0,
                "content": "Nyhet dag 1",
                "created_at": 5,
            },
            {
                "post_id": 2,
                "user_id": 0,
                "content": "Nyhet dag 2 hemlig",
                "created_at": 15,
            },
        ],
        "comments": [],
        "trace": [],
    }


@pytest.fixture
async def interview_client():
    settings.persona_generator = "stub"
    settings.deepseek_api_key = "test-key-not-real"
    settings.supabase_jwt_secret = TEST_JWT_SECRET
    settings.simulation_engine = "none"

    async def _mock_text(messages: list[dict[str, str]]) -> str:
        system = messages[0]["content"] if messages else ""
        if "Nyhet dag 2 hemlig" in system:
            return "Jag såg dag-2-nyheten."
        if "Nyhet dag 1" in system:
            return "Jag såg bara dag 1."
        return "Mockad intervju."

    set_text_completer(_mock_text)

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.services.prompt_store import ensure_default_configurations

    async with session_factory() as seed_session:
        await ensure_default_kunder(seed_session)
        await ensure_default_configurations(seed_session)
        seed_session.add(
            UserAccount(
                id=ADMIN_USER_ID,
                email="admin@test.local",
                role="admin",
                kund_id=None,
            )
        )
        await seed_session.commit()

    async with session_factory() as session:
        persona = Persona(
            id="p-anna",
            customer_id=1,
            name="Anna",
            age=40,
            occ="Lärare",
            district="Centrum",
            quote="",
            origin="manuell",
            profile={"name": "Anna", "age": "40", "ort": "Centrum", "yrke": "Lärare"},
            updated_at=utcnow(),
        )
        pop = Population(
            name="InterviewPop",
            size=1,
            versions=1,
            fingerprint=[],
            recipe={},
            updated_at=utcnow(),
        )
        session.add(persona)
        session.add(pop)
        await session.flush()
        session.add(
            PopulationMember(
                population_id=pop.id,
                persona_id=persona.id,
                name="Anna",
                initials="A",
                age=40,
                occ="Lärare",
                district="Centrum",
                trait="",
            )
        )
        run = Run(
            name="InterviewRun",
            project_id=1,
            status="done",
            population_id=pop.id,
            seed="s",
            start_date=date(2026, 8, 1),
            main_ticks=[],
            branch=None,
            oasis_options={},
            results={
                "engine": "oasis",
                "attempts": [
                    {
                        "id": "att_test",
                        "finished_at": utcnow().isoformat(),
                        "engine": "oasis",
                        "variants": [_variant_payload(persona.id)],
                    }
                ],
            },
            updated_at=utcnow(),
        )
        session.add(run)
        await session.commit()
        run_id = run.id
        persona_id = persona.id

    jobs_service.set_job_session_factory(session_factory)
    app = create_app()

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    token = mint_access_token(sub=ADMIN_USER_ID, email="admin@test.local")
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        yield ac, run_id, persona_id

    jobs_service.set_job_session_factory(None)
    set_text_completer(None)
    await engine.dispose()


async def test_run_interview_happy_path(interview_client):
    client, run_id, persona_id = interview_client
    path = (
        f"/runs/{run_id}/attempts/att_test/variants/main"
        f"/personas/{persona_id}/interview"
    )
    listed = await client.get(path, params={"through_tick_index": 0})
    assert listed.status_code == 200
    assert listed.json() == []

    chat = await client.post(
        path,
        json={"through_tick_index": 0, "message": "Vad såg du?"},
    )
    assert chat.status_code == 200
    body = chat.json()
    assert "dag 1" in body["reply"].casefold() or "Mockad" in body["reply"]
    assert len(body["messages"]) == 2
    assert body["messages"][0]["run_id"] == run_id
    assert body["messages"][0]["through_tick_index"] == 0

    # Library chat must stay empty (run-scoped rows filtered out).
    lib = await client.get(
        f"/personas/{persona_id}/messages", params={"mode": "interview"}
    )
    assert lib.json() == []

    cleared = await client.delete(path, params={"through_tick_index": 0})
    assert cleared.status_code == 204
    after = await client.get(path, params={"through_tick_index": 0})
    assert after.json() == []


async def test_run_interview_rejects_bad_tick(interview_client):
    client, run_id, persona_id = interview_client
    path = (
        f"/runs/{run_id}/attempts/att_test/variants/main"
        f"/personas/{persona_id}/interview"
    )
    bad = await client.post(
        path,
        json={"through_tick_index": 9, "message": "Hej"},
    )
    assert bad.status_code == 400


async def test_run_interview_unknown_persona(interview_client):
    client, run_id, _persona_id = interview_client
    path = (
        f"/runs/{run_id}/attempts/att_test/variants/main"
        f"/personas/missing/interview"
    )
    # Persona row missing → 404 before variant check, or 404 from variant.
    resp = await client.post(
        path,
        json={"through_tick_index": 0, "message": "Hej"},
    )
    assert resp.status_code == 404
