"""simulate_run runs A/B variants concurrently."""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Persona, Population, PopulationMember, Run
from app.services.oasis_run import OasisUnavailable, simulate_run


def _tick(key: str, day: int, text: str) -> dict:
    return {
        "key": key,
        "day": day,
        "silent": False,
        "injections": [
            {
                "key": f"i-{key}",
                "type": "party_post",
                "sender": "@parti",
                "text": text,
                "mode": "text",
                "url": "",
                "fetching": False,
                "sourceDomain": "",
                "isVideo": False,
                "message_id": None,
            }
        ],
        "rounds": 1,
        "measurements": [],
        "interviews": [],
    }


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.services.prompt_store import ensure_default_configurations

    async with session_factory() as s:
        await ensure_default_configurations(s)
        yield s
    await engine.dispose()


async def _seed_ab_run(session: AsyncSession) -> Run:
    session.add(
        Persona(
            id="p1",
            name="Anna Test",
            age=40,
            occ="Lärare",
            district="Centrum",
            quote="Hej",
            origin="manuell",
            profile={"name": "Anna Test", "age": "40", "ort": "Centrum", "yrke": "Lärare"},
        )
    )
    pop = Population(
        name="Parallellpop",
        size=1,
        versions=1,
        fingerprint=[[100, 0, 0]],
        recipe={},
    )
    session.add(pop)
    await session.flush()
    session.add(
        PopulationMember(
            population_id=pop.id,
            persona_id="p1",
            name="Anna Test",
            initials="AT",
            age=40,
            occ="Lärare",
            district="Centrum",
            trait="Hej",
        )
    )
    run = Run(
        name="AB parallel",
        status="running",
        population_id=pop.id,
        seed="seed1",
        start_date=date(2026, 7, 1),
        main_ticks=[_tick("m1", 1, "gemensam")],
        branch={
            "afterIndex": 0,
            "mode": "ab",
            "a": [_tick("a2", 2, "version A")],
            "b": [_tick("b2", 2, "version B")],
        },
        oasis_options={"platform": "twitter", "allow_population_create_post": True},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def test_simulate_run_gathers_ab_variants_concurrently(session: AsyncSession):
    run = await _seed_ab_run(session)
    started = asyncio.Event()
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def fake_sim(**kwargs):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            if in_flight >= 2:
                started.set()
        await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.sleep(0.02)
        async with lock:
            in_flight -= 1
        vid = kwargs["variant_id"]
        return {
            "agents": [],
            "posts": [{"post_id": 1, "content": vid}],
            "comments": [],
            "follows": [],
            "mutes": [],
            "reports": [],
            "trace": [],
            "action_histogram": [],
            "tick_markers": [],
            "ticks_run": 2,
            "artifact_db": f"data/oasis/run_{kwargs['run_id']}/{vid}/simulation.db",
            "platform": "twitter",
            "agent_count": 1,
            "configured_ticks": 2,
            "oasis_options": {"platform": "twitter", "allow_population_create_post": True},
        }

    with patch(
        "app.services.oasis_run.run_oasis_simulation",
        new=AsyncMock(side_effect=fake_sim),
    ):
        results = await simulate_run(session, run)

    assert max_in_flight == 2
    attempt = results["attempts"][0]
    assert [v["id"] for v in attempt["variants"]] == ["a", "b"]
    assert attempt["variants"][0]["posts"][0]["content"] == "a"
    assert attempt["variants"][1]["posts"][0]["content"] == "b"
    assert attempt["error"] is None


async def test_simulate_run_records_variant_error_keeps_sibling(session: AsyncSession):
    run = await _seed_ab_run(session)

    async def fake_sim(**kwargs):
        if kwargs["variant_id"] == "a":
            raise RuntimeError("boom A")
        return {
            "agents": [],
            "posts": [],
            "comments": [],
            "follows": [],
            "mutes": [],
            "reports": [],
            "trace": [],
            "action_histogram": [],
            "tick_markers": [],
            "ticks_run": 1,
            "platform": "twitter",
            "agent_count": 1,
            "configured_ticks": 1,
            "oasis_options": {},
        }

    with patch(
        "app.services.oasis_run.run_oasis_simulation",
        new=AsyncMock(side_effect=fake_sim),
    ):
        results = await simulate_run(session, run)

    variants = results["attempts"][0]["variants"]
    by_id = {v["id"]: v for v in variants}
    assert by_id["a"]["error"] == "boom A"
    assert by_id["b"]["error"] is None
    assert results["attempts"][0]["error"] is None


async def test_simulate_run_propagates_oasis_unavailable(session: AsyncSession):
    run = await _seed_ab_run(session)

    async def fake_sim(**kwargs):
        raise OasisUnavailable("missing oasis")

    with patch(
        "app.services.oasis_run.run_oasis_simulation",
        new=AsyncMock(side_effect=fake_sim),
    ):
        with pytest.raises(OasisUnavailable, match="missing oasis"):
            await simulate_run(session, run)
