"""Tests for read-only help context assembly."""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key-not-real")

from app.database.base import Base
from app.database.models import Job, Population, Run
from app.schemas.domain import HelpViewContext
from app.services.help_read_context import build_help_context
from app.services.prompt_store import ensure_default_configurations
from app.services.run_log import run_variant_log_path, write_run_log_note


@pytest.fixture
def help_session():
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

    yield session_factory, loop

    loop.run_until_complete(engine.dispose())
    loop.close()


def test_build_help_context_includes_view_and_snapshot(help_session):
    session_factory, loop = help_session
    view = HelpViewContext(
        path="/runs",
        view_key="runs.list",
        label="Körningar — lista",
        params={},
        search={},
    )

    async def _run() -> str:
        async with session_factory() as session:
            return await build_help_context(session, view=view, query="starta simulering")

    text = loop.run_until_complete(_run())
    assert "Current view" in text
    assert "runs.list" in text
    assert "Live data snapshot" in text
    assert "Manual (OKF)" in text
    assert "Personas:" in text
    assert "Catalog ton labels (persona voice):" in text
    assert "Direkt och kort i tonen" in text
    assert "SSR tone labels:" in text
    assert "SSR style labels:" in text


def test_build_help_context_includes_failed_job_error(help_session):
    session_factory, loop = help_session

    async def _seed_and_run() -> str:
        async with session_factory() as session:
            session.add(
                Job(
                    id="job_fail_demo",
                    kind="run_simulate",
                    status="failed",
                    label="Simulering misslyckades",
                    error="DeepSeek timeout after 120s",
                )
            )
            await session.commit()
            view = HelpViewContext(
                path="/jobs",
                view_key="jobs.list",
                label="Jobb",
                params={},
                search={},
            )
            return await build_help_context(session, view=view, query="varför misslyckades jobbet")

    text = loop.run_until_complete(_seed_and_run())
    assert "Open jobs view" in text
    assert "DeepSeek timeout after 120s" in text


def test_build_help_context_includes_run_troubleshooting(help_session, tmp_path, monkeypatch):
    session_factory, loop = help_session
    monkeypatch.chdir(tmp_path)

    attempt_id = "att_demo"
    log_path = run_variant_log_path(42, attempt_id, "main")
    write_run_log_note(log_path, "engine=none\nerror=preflight failed")

    async def _seed_and_run() -> str:
        async with session_factory() as session:
            pop = Population(name="Testpop", size=0, versions=1)
            session.add(pop)
            await session.flush()
            session.add(
                Run(
                    name="Demo run",
                    project_id=1,
                    status="failed",
                    population_id=pop.id,
                    seed="seed",
                    main_ticks=[],
                    oasis_options={
                        "enable_search_wiki": True,
                        "enable_search_duckduckgo": False,
                        "enable_sympy_tools": False,
                    },
                    results={
                        "engine": "none",
                        "attempts": [
                            {
                                "id": attempt_id,
                                "engine": "none",
                                "error": "Population empty",
                                "variants": [
                                    {
                                        "id": "main",
                                        "label": "Main",
                                        "error": "Population empty",
                                        "log_path": str(log_path),
                                        "agent_tools": [
                                            {
                                                "tick_index": 1,
                                                "tool_name": "search_wiki",
                                                "args": {"entity": "Test"},
                                                "result_preview": "Wikipedia-sökning misslyckades",
                                            }
                                        ],
                                        "quality_warnings": {
                                            "threshold": 0.4,
                                            "population_agents": 0,
                                            "warnings": [],
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                )
            )
            await session.flush()
            run_id = (await session.execute(select(Run.id).order_by(Run.id.desc()).limit(1))).scalar_one()
            await session.commit()
            view = HelpViewContext(
                path=f"/runs/{run_id}/edit",
                view_key="runs.edit",
                label="Körning — redigera",
                params={"id": str(run_id)},
                search={"tab": "resultat"},
            )
            return await build_help_context(session, view=view, query="varför failade körningen")

    text = loop.run_until_complete(_seed_and_run())
    assert "Attempt att_demo" in text
    assert "Population empty" in text
    assert "search_wiki" in text
    assert "preflight failed" in text
    assert "wiki=True" in text
