"""Tests for read-only help context assembly."""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key-not-real")

from app.database.base import Base
from app.schemas.domain import HelpViewContext
from app.services.help_read_context import build_help_context
from app.services.prompt_store import ensure_default_configurations


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
