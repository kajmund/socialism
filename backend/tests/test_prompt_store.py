"""Prompt configuration loading."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Configuration
from app.serializers import utcnow
from app.services.prompt_catalog import default_prompts
from app.services.prompt_store import (
    MissingActiveConfigurationError,
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


async def test_require_prompts_for_language_uses_active_matching_language(
    session: AsyncSession,
):
    result = await session.execute(select(Configuration))
    rows = list(result.scalars().all())
    sv_row = next(r for r in rows if r.language == "sv")
    await set_active_configuration(session, sv_row.id)

    prompts = await require_prompts_for_language(session, "sv")
    active = await require_active_prompts(session)

    assert prompts["oasis.env.empty_posts"] == active["oasis.env.empty_posts"]
    assert prompts["oasis.env.empty_posts"] == default_prompts("sv")["oasis.env.empty_posts"]


async def test_require_prompts_for_language_rejects_active_other_language(
    session: AsyncSession,
):
    result = await session.execute(select(Configuration))
    rows = list(result.scalars().all())
    en_row = next(r for r in rows if r.language == "en")
    await set_active_configuration(session, en_row.id)

    with pytest.raises(MissingActiveConfigurationError, match="language 'en'"):
        await require_prompts_for_language(session, "sv")


async def test_require_prompts_for_language_prefers_active_not_oldest(
    session: AsyncSession,
):
    """Multiple sv configs: always the active one, never the oldest inactive."""
    now = utcnow()
    custom_prompts = dict(default_prompts("sv"))
    custom_prompts["oasis.env.empty_posts"] = "CUSTOM_ACTIVE_SV_MARKER"
    custom = Configuration(
        name="Custom active sv",
        language="sv",
        prompts=custom_prompts,
        ssr_temperature=0.1,
        anchor_sets={},
        is_active=False,
        created_at=now,
        updated_at=now,
    )
    session.add(custom)
    await session.commit()
    await session.refresh(custom)

    await set_active_configuration(session, custom.id)
    prompts = await require_prompts_for_language(session, "sv")
    assert prompts["oasis.env.empty_posts"] == "CUSTOM_ACTIVE_SV_MARKER"


async def test_require_active_prompts_backfills_missing_help_keys(
    session: AsyncSession,
):
    """Configs created before help.* keys existed should get catalog defaults."""
    result = await session.execute(
        select(Configuration).where(Configuration.is_active.is_(True))
    )
    row = result.scalar_one()
    stored = dict(row.prompts or {})
    for key in (
        "help.system",
        "help.system.scb",
        "help.system.scb_population",
        "help.system.feedback",
    ):
        stored.pop(key, None)
    row.prompts = stored
    await session.commit()

    prompts = await require_active_prompts(session)
    assert prompts["help.system"].strip()
    assert prompts["help.system.feedback"].strip()

    await session.refresh(row)
    assert "help.system" in (row.prompts or {})
    assert "help.system.feedback" in (row.prompts or {})
