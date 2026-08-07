"""Prompt configuration loading."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Configuration
from app.services.prompt_catalog import default_prompts
from app.services.prompt_store import (
    ensure_default_configurations,
    require_active_prompts,
    require_prompts_for_language,
    set_active_configuration,
)


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        await ensure_default_configurations(s)
        yield s
    await engine.dispose()


async def test_require_prompts_for_language_ignores_global_active(session: AsyncSession):
    result = await session.execute(select(Configuration))
    rows = list(result.scalars().all())
    en_row = next(r for r in rows if r.language == "en")
    await set_active_configuration(session, en_row.id)

    active = await require_active_prompts(session)
    sv = await require_prompts_for_language(session, "sv")

    assert active["oasis.env.empty_posts"] == default_prompts("en")["oasis.env.empty_posts"]
    assert sv["oasis.env.empty_posts"] == default_prompts("sv")["oasis.env.empty_posts"]
