"""MAX_CONCURRENT_SIMULATION_JOBS caps overlapping run_simulate workers."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.database.models import Job, Population, Run
from app.services import jobs as jobs_service


@pytest.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    jobs_service.set_job_session_factory(factory)
    jobs_service.reset_simulation_job_semaphore()
    settings.max_concurrent_simulation_jobs = 1
    jobs_service.reset_simulation_job_semaphore()

    yield factory

    jobs_service.set_job_session_factory(None)
    jobs_service.reset_simulation_job_semaphore()
    settings.max_concurrent_simulation_jobs = 2
    await engine.dispose()


async def _seed_pending_sim_job(factory: async_sessionmaker[AsyncSession], name: str) -> str:
    async with factory() as session:
        pop = Population(name=name, size=0, versions=1, fingerprint=[], recipe={})
        session.add(pop)
        await session.flush()
        run = Run(
            name=name,
            project_id=1,
            status="running",
            population_id=pop.id,
            seed="s",
            start_date=date(2026, 7, 1),
            main_ticks=[],
            branch=None,
            oasis_options={},
        )
        session.add(run)
        await session.flush()
        job = Job(
            id=f"job_{name}",
            customer_id=1,
            kind="run_simulate",
            status="pending",
            label=name,
            request={"run_id": run.id},
        )
        session.add(job)
        await session.commit()
        return job.id


async def test_run_simulate_jobs_wait_for_semaphore_slot(session_factory, monkeypatch):
    release = asyncio.Event()
    entered: list[str] = []
    max_running = 0
    running_now = 0
    lock = asyncio.Lock()

    async def slow_simulate(_job_id: str) -> None:
        nonlocal running_now, max_running
        async with lock:
            running_now += 1
            max_running = max(max_running, running_now)
            entered.append(_job_id)
        await release.wait()
        async with lock:
            running_now -= 1

    monkeypatch.setattr(jobs_service, "_run_simulate", slow_simulate)

    j1 = await _seed_pending_sim_job(session_factory, "one")
    j2 = await _seed_pending_sim_job(session_factory, "two")

    t1 = asyncio.create_task(jobs_service._run_job(j1))
    t2 = asyncio.create_task(jobs_service._run_job(j2))

    await asyncio.sleep(0.05)
    assert len(entered) == 1
    assert max_running == 1

    async with session_factory() as session:
        statuses = {
            (await session.get(Job, j1)).status,
            (await session.get(Job, j2)).status,
        }
    assert statuses == {"running", "pending"}

    release.set()
    await asyncio.gather(t1, t2)
    assert max_running == 1
    assert set(entered) == {j1, j2}
