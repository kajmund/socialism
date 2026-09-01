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
        customer_id=1,
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


async def test_require_active_prompts_refreshes_stale_panel_dd_raise_hand(
    session: AsyncSession,
):
    result = await session.execute(
        select(Configuration).where(Configuration.is_active.is_(True))
    )
    row = result.scalar_one()
    stored = dict(row.prompts or {})
    stored["panel.dd.expert.raise_hand"] = (
        "Vanligtvis bedömd av: {typical_owner}. Räck upp handen om delfrågan är din."
    )
    stored["panel.dd.moderator.sub_question"] = (
        "Introducera delfrågan kort. Be inte alla om poäng — bara den som räcker upp handen."
    )
    stored["panel.dd.moderator.opening"] = (
        "Öppna panelen kort. Förklara att varje expert snart bedömer finansiell hälsa, "
        "legal risk, marknadsposition och integrationsrisk med poäng 1–10."
    )
    stored["panel.dd.moderator.system"] = (
        "Du är Spinndoktor och modererar en bolags-DD-panel.\n"
        "Skriv BARA din egen replik som moderator."
    )
    stored["panel.dd.expert.score"] = (
        "Slå upp bolaget med lookup_company om du behöver nyckeltal."
    )
    stored["panel.expert.tools"] = (
        "Du har search_companies — slå upp nyckeltal när grunddata saknar omsättning."
    )
    stored["chat.expert.search_tools"] = "search_duckduckgo (nyheter, lagar, siffror)"
    stored["chat.expert.company_tools"] = (
        "Använd dem när du behöver organisationsnummer, omsättning, resultat."
    )
    row.prompts = stored
    await session.commit()

    prompts = await require_active_prompts(session)
    assert "kärnkompetens" in prompts["panel.dd.expert.raise_hand"]
    assert "hela bedömningen" in prompts["panel.dd.expert.raise_hand"]
    assert "Första raden: JA eller NEJ" in prompts["panel.dd.expert.raise_hand"]
    assert "varför delfrågan är" in prompts["panel.dd.expert.raise_hand"]
    assert "{typical_owner}" not in prompts["panel.dd.expert.raise_hand"]
    assert "avgör själv" not in prompts["panel.dd.expert.raise_hand"]
    assert "Svara ENDAST JA eller NEJ" not in prompts["panel.dd.expert.raise_hand"]
    assert "Skriv inte **Namn:**-repliker" in prompts["panel.dd.moderator.sub_question"]
    assert "Be inte alla om poäng" not in prompts["panel.dd.moderator.sub_question"]
    assert "Tilldela inte första frågan" in prompts["panel.dd.moderator.opening"]
    assert "varje expert snart bedömer" not in prompts["panel.dd.moderator.opening"]
    assert "Du modererar panelen" in prompts["panel.dd.moderator.system"]
    assert "Du är Spinndoktor och modererar en bolags-DD-panel" not in prompts[
        "panel.dd.moderator.system"
    ]
    assert "Slå inte upp" in prompts["panel.dd.expert.score"]
    assert "hitta inte på en webbkälla" in prompts["panel.dd.expert.score"]
    assert "max 80" not in prompts["panel.dd.expert.score"]
    assert "Slå upp bolaget med lookup_company" not in prompts["panel.dd.expert.score"]
    assert "Sök inte efter samma siffror" in prompts["panel.expert.tools"]
    assert "Sök inte efter nyckeltal du redan har fått" in prompts[
        "chat.expert.search_tools"
    ]
    assert "Slå inte upp siffror du redan har fått" in prompts[
        "chat.expert.company_tools"
    ]


async def test_require_active_prompts_refreshes_stale_spindoctor_stock_text(
    session: AsyncSession,
):
    result = await session.execute(
        select(Configuration).where(Configuration.is_active.is_(True))
    )
    row = result.scalar_one()
    stored = dict(row.prompts or {})
    stored["spinndoctor.system"] = (
        "Gammal text. Svara kort om möjligt, utveckla när användaren ber om det."
    )
    stored["spinndoctor.system.tools"] = (
        "Egen verktygstext. Be inte om tillåtelse att använda ett verktyg."
    )
    row.prompts = stored
    await session.commit()

    prompts = await require_active_prompts(session)
    assert "Fråga inte användaren om något du kan slå upp" in prompts["spinndoctor.system"]
    assert "Svara kort om möjligt" not in prompts["spinndoctor.system"]
    assert prompts["spinndoctor.system.tools"].startswith("Egen verktygstext.")


async def test_require_active_prompts_refreshes_older_english_spindoctor_tools(
    session: AsyncSession,
):
    result = await session.execute(select(Configuration))
    rows = list(result.scalars().all())
    en_row = next(r for r in rows if r.language == "en")
    await set_active_configuration(session, en_row.id)
    stored = dict(en_row.prompts or {})
    stored["spinndoctor.system.tools"] = (
        "You have get_test_message. Call them when the question needs the "
        "message wording. Do not call tools if the context numbers are enough."
    )
    en_row.prompts = stored
    await session.commit()

    prompts = await require_active_prompts(session)
    assert "Do not ask permission to use a tool" in prompts["spinndoctor.system.tools"]
    assert "Do not call tools if" not in prompts["spinndoctor.system.tools"]
