"""Scoped prompt loader: customer × module × language."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Configuration, Kund, PromptOverride
from app.services.kund_store import default_os_customer_id, ensure_default_kunder
from app.services.panel.module_defaults import ensure_module_panel_defaults
from app.services.prompt_catalog import default_prompts
from app.services.prompt_fields_store import (
    MissingPromptCatalogError,
    MissingPromptCustomerError,
    filled_prompts,
    get_prompt_field_by_key,
    replace_prompt_overrides,
)
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
        await ensure_module_panel_defaults(s)
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_two_customers_load_different_overrides(session: AsyncSession):
    os_id = await default_os_customer_id(session)
    other = Kund(name="Annan", slug="annan", available_modules=["politik"])
    session.add(other)
    await session.flush()
    await replace_prompt_overrides(
        session,
        customer_id=os_id,
        language="sv",
        prompts={"help.system": "OS-hjälp"},
    )
    await replace_prompt_overrides(
        session,
        customer_id=other.id,
        language="sv",
        prompts={"help.system": "Annan-hjälp"},
    )
    await session.commit()

    os_prompts = await require_active_prompts(
        session, customer_id=os_id, module="politik", language="sv"
    )
    other_prompts = await require_active_prompts(
        session, customer_id=other.id, module="politik", language="sv"
    )
    assert os_prompts["help.system"] == "OS-hjälp"
    assert other_prompts["help.system"] == "Annan-hjälp"
    assert os_prompts["persona.field_guide"] == default_prompts("sv")["persona.field_guide"]


@pytest.mark.asyncio
async def test_missing_customer_fails_loud(session: AsyncSession):
    with pytest.raises(MissingPromptCustomerError, match="99999"):
        await require_active_prompts(
            session, customer_id=99999, module="politik", language="sv"
        )


@pytest.mark.asyncio
async def test_module_filter_excludes_other_module_keys(session: AsyncSession):
    os_id = await default_os_customer_id(session)
    politik = await require_active_prompts(
        session, customer_id=os_id, module="politik", language="sv"
    )
    dd = await require_active_prompts(
        session, customer_id=os_id, module="dd", language="sv"
    )
    assert "persona.field_guide" in politik
    assert "persona.field_guide" not in dd
    assert "panel.dd.moderator.system" in dd
    assert "panel.dd.moderator.system" not in politik
    assert "help.system" in politik
    assert "help.system" in dd


@pytest.mark.asyncio
async def test_activate_does_not_change_loaded_prompt_text(session: AsyncSession):
    os_id = await default_os_customer_id(session)
    await replace_prompt_overrides(
        session,
        customer_id=os_id,
        language="sv",
        prompts={"help.system": "Kvar efter aktivering"},
    )
    await session.commit()
    result = await session.execute(select(Configuration))
    rows = list(result.scalars().all())
    en_row = next(r for r in rows if r.language == "en")
    await set_active_configuration(session, en_row.id)

    prompts = await require_active_prompts(
        session, customer_id=os_id, module="politik", language="sv"
    )
    assert prompts["help.system"] == "Kvar efter aktivering"


@pytest.mark.asyncio
async def test_empty_catalog_fails_loud(session: AsyncSession):
    os_id = await default_os_customer_id(session)
    with pytest.raises(MissingPromptCatalogError, match="okand"):
        await require_active_prompts(
            session, customer_id=os_id, module="okand", language="sv"
        )


@pytest.mark.asyncio
async def test_override_matching_default_is_not_stored(session: AsyncSession):
    os_id = await default_os_customer_id(session)
    default_help = default_prompts("sv")["help.system"]
    await replace_prompt_overrides(
        session,
        customer_id=os_id,
        language="sv",
        prompts={"help.system": default_help},
    )
    await session.commit()
    field = await get_prompt_field_by_key(session, "help.system")
    assert field is not None
    remaining = (
        await session.execute(
            select(PromptOverride).where(
                PromptOverride.customer_id == os_id,
                PromptOverride.prompt_field_id == field.id,
            )
        )
    ).scalars().all()
    assert remaining == []
    prompts = await filled_prompts(session, customer_id=os_id, language="sv", module="politik")
    assert prompts["help.system"] == default_help


@pytest.mark.asyncio
async def test_require_prompts_for_language_is_scoped(session: AsyncSession):
    await ensure_default_kunder(session)
    os_id = await default_os_customer_id(session)
    prompts = await require_prompts_for_language(
        session, "sv", customer_id=os_id, module="politik"
    )
    assert prompts["oasis.env.empty_posts"] == default_prompts("sv")["oasis.env.empty_posts"]
