"""Fixtures for manual OASIS smoke tests (opt-in via ``pytest -m smoke``)."""

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.services import jobs as jobs_service
from app.services.oasis_run import oasis_installed


def _placeholder_deepseek_key(key: str) -> bool:
    stripped = key.strip()
    return (
        not stripped
        or stripped == "test-key-not-real"
        or stripped.startswith("placeholder")
    )


@pytest.fixture
def smoke_deepseek_key() -> str:
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    key = env_key or settings.deepseek_api_key
    if _placeholder_deepseek_key(key):
        pytest.skip(
            "DEEPSEEK_API_KEY must be set to a real key in the environment "
            "(placeholder/test keys are rejected for smoke tests)"
        )
    return key


@pytest.fixture
def smoke_oasis_extra() -> None:
    if not oasis_installed():
        pytest.skip("camel-oasis is not installed — run: uv sync --extra oasis")


@pytest.fixture
async def smoke_session(monkeypatch: pytest.MonkeyPatch, tmp_path):
    from app.services.anchor_store import ensure_default_anchor_sets
    from app.services.prompt_store import ensure_default_configurations

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as seed_session:
        await ensure_default_anchor_sets(seed_session)
        await ensure_default_configurations(seed_session)

    jobs_service.set_job_session_factory(session_factory)
    jobs_service.reset_simulation_job_semaphore()

    artifact_root = tmp_path / "oasis"
    artifact_root.mkdir()
    monkeypatch.setattr("app.services.oasis_run.ARTIFACT_ROOT", artifact_root)

    yield session_factory

    jobs_service.set_job_session_factory(None)
    await engine.dispose()
