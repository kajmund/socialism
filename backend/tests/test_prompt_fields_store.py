"""Prompt catalog tables: seed, no-overwrite, sparse overrides."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Configuration, Kund, PromptField, PromptOverride
from app.serializers import utcnow
from app.services.prompt_catalog import PROMPT_FIELDS, default_prompts
from app.services.prompt_defaults import (
    dd_prompt_defaults,
    expertgranskning_prompt_defaults,
    modules_for_prompt_key,
    politik_prompt_defaults,
    rattsunderlag_prompt_defaults,
)
from app.services.prompt_fields_store import (
    ensure_prompt_field_defaults,
    ensure_prompt_overrides_from_configurations,
    get_prompt_field_by_key,
    get_prompt_fields,
    retire_unknown_prompt_fields,
)


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as db:
        yield db
    await engine.dispose()


def test_modules_for_prompt_key_follows_prefix_convention():
    assert modules_for_prompt_key("panel.dd.moderator.system") == ["dd"]
    assert modules_for_prompt_key("dd.sourcing.chat.system") == ["dd"]
    assert modules_for_prompt_key("persona.field_guide") == ["politik"]
    assert modules_for_prompt_key("messages.variant.system") == ["politik"]
    assert modules_for_prompt_key("oasis.env.main") == ["politik"]
    assert modules_for_prompt_key("help.system") == ["dd", "politik"]
    assert modules_for_prompt_key("spinndoctor.system") == [
        "dd",
        "politik",
        "expertgranskning",
        "rattsunderlag",
    ]
    assert modules_for_prompt_key("panel.expert.system") == [
        "dd",
        "politik",
        "expertgranskning",
        "rattsunderlag",
    ]
    assert modules_for_prompt_key("panel.generic.synthesis") == [
        "dd",
        "politik",
        "expertgranskning",
    ]
    assert modules_for_prompt_key("expert.from_underlag.system") == [
        "dd",
        "politik",
        "expertgranskning",
    ]
    assert modules_for_prompt_key("rattsunderlag.search_terms.system") == ["rattsunderlag"]
    assert modules_for_prompt_key("expertgranskning.word.paragraph") == ["expertgranskning"]
    assert modules_for_prompt_key("expertgranskning.word.heading") == ["expertgranskning"]
    assert modules_for_prompt_key("expertgranskning.word.expert.raise_hand") == [
        "expertgranskning"
    ]
    assert modules_for_prompt_key("expertgranskning.word.expert.comment") == [
        "expertgranskning"
    ]
    assert modules_for_prompt_key("expertgranskning.word.rewrite_convergence") == [
        "expertgranskning"
    ]
    assert modules_for_prompt_key("expertgranskning.word.moderator.batch") == [
        "expertgranskning"
    ]


def test_module_providers_cover_all_catalog_keys_without_overlap_gaps():
    dd_keys = {field["key"] for field in dd_prompt_defaults()}
    politik_keys = {field["key"] for field in politik_prompt_defaults()}
    ratts_keys = {field["key"] for field in rattsunderlag_prompt_defaults()}
    expert_keys = {field["key"] for field in expertgranskning_prompt_defaults()}
    all_keys = {field["key"] for field in PROMPT_FIELDS}
    assert dd_keys | politik_keys | ratts_keys | expert_keys == all_keys
    spinndoctor_keys = {key for key in all_keys if key.startswith("spinndoctor.")}
    shared_with_dd = spinndoctor_keys | {"panel.expert.system"}
    assert shared_with_dd <= ratts_keys
    assert ratts_keys.isdisjoint(dd_keys - shared_with_dd)
    assert {
        "expertgranskning.word.paragraph",
        "expertgranskning.word.heading",
        "expertgranskning.word.moderator.batch",
        "expertgranskning.word.expert.raise_hand",
        "expertgranskning.word.expert.comment",
        "expertgranskning.word.rewrite_convergence",
    }.isdisjoint(dd_keys | politik_keys | ratts_keys)
    assert "rattsunderlag.search_terms.system" in ratts_keys
    assert "panel.dd.moderator.system" in dd_keys
    assert "panel.dd.moderator.system" not in politik_keys
    assert "persona.field_guide" in politik_keys
    assert "persona.field_guide" not in dd_keys
    assert "help.system" in dd_keys & politik_keys
    assert expert_keys < all_keys
    assert "panel.expert.system" in expert_keys
    assert "panel.generic.synthesis" in expert_keys
    assert "panel.generic.synthesis" in dd_keys
    assert "panel.generic.synthesis" in politik_keys
    assert "panel.generic.synthesis" not in ratts_keys
    assert "spinndoctor.system" in expert_keys
    assert "spinndoctor.system" in ratts_keys
    assert "panel.expert.system" in ratts_keys
    assert "expertgranskning.word.paragraph" in expert_keys
    assert "expertgranskning.word.heading" in expert_keys
    assert "expertgranskning.word.moderator.batch" in expert_keys
    assert "expertgranskning.word.expert.raise_hand" in expert_keys
    assert "expertgranskning.word.expert.comment" in expert_keys
    assert "expertgranskning.word.rewrite_convergence" in expert_keys
    assert "help.system" not in expert_keys
    assert "panel.dd.moderator.system" not in expert_keys


@pytest.mark.asyncio
async def test_ensure_prompt_field_defaults_inserts_once(session: AsyncSession):
    specs = dd_prompt_defaults()
    added = await ensure_prompt_field_defaults(session, "dd", specs)
    assert added == len(specs)
    again = await ensure_prompt_field_defaults(session, "dd", specs)
    assert again == 0
    rows = await get_prompt_fields(session, "dd")
    assert {row.key for row in rows} == {field["key"] for field in specs}
    assert await get_prompt_fields(session, "politik") == []


@pytest.mark.asyncio
async def test_ensure_prompt_field_defaults_does_not_overwrite(session: AsyncSession):
    await ensure_prompt_field_defaults(session, "dd", dd_prompt_defaults())
    row = await get_prompt_field_by_key(session, "help.system")
    assert row is not None
    row.default_sv = "Edited default"
    await session.commit()

    await ensure_prompt_field_defaults(session, "dd", dd_prompt_defaults())
    await session.refresh(row)
    assert row.default_sv == "Edited default"


@pytest.mark.asyncio
async def test_ensure_prompt_field_defaults_attaches_module_without_duplicate(
    session: AsyncSession,
):
    await ensure_prompt_field_defaults(session, "dd", dd_prompt_defaults())
    row = await get_prompt_field_by_key(session, "help.system")
    assert row is not None
    row.default_sv = "Edited default"
    await session.commit()

    attached = await ensure_prompt_field_defaults(
        session, "politik", politik_prompt_defaults()
    )
    assert attached > 0
    again = await ensure_prompt_field_defaults(
        session, "politik", politik_prompt_defaults()
    )
    assert again == 0

    await session.refresh(row)
    assert row.default_sv == "Edited default"
    assert row.modules == ["dd", "politik"]

    await ensure_prompt_field_defaults(
        session, "rattsunderlag", rattsunderlag_prompt_defaults()
    )
    await ensure_prompt_field_defaults(
        session, "expertgranskning", expertgranskning_prompt_defaults()
    )
    all_rows = (await session.execute(select(PromptField))).scalars().all()
    assert len(all_rows) == len(PROMPT_FIELDS)
    dd_only = await get_prompt_field_by_key(session, "panel.dd.moderator.system")
    politik_only = await get_prompt_field_by_key(session, "persona.field_guide")
    assert dd_only is not None and dd_only.modules == ["dd"]
    assert politik_only is not None and politik_only.modules == ["politik"]


@pytest.mark.asyncio
async def test_sparse_overrides_skip_defaults_and_keep_existing(session: AsyncSession):
    await ensure_prompt_field_defaults(session, "dd", dd_prompt_defaults())
    customer = Kund(name="Acme", slug="acme", available_modules=["dd"])
    session.add(customer)
    await session.flush()
    now = utcnow()
    defaults = default_prompts("sv")
    stored = dict(defaults)
    stored["help.system"] = "Kundanpassad hjälpchatt."
    session.add(
        Configuration(
            customer_id=customer.id,
            name="Standard (svenska)",
            language="sv",
            prompts=stored,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()

    added = await ensure_prompt_overrides_from_configurations(session)
    assert added == 1
    again = await ensure_prompt_overrides_from_configurations(session)
    assert again == 0

    rows = (await session.execute(select(PromptOverride))).scalars().all()
    assert len(rows) == 1
    field = await get_prompt_field_by_key(session, "help.system")
    assert field is not None
    assert rows[0].prompt_field_id == field.id
    assert rows[0].text == "Kundanpassad hjälpchatt."

    rows[0].text = "Redigerad override"
    await session.commit()
    await ensure_prompt_overrides_from_configurations(session)
    await session.refresh(rows[0])
    assert rows[0].text == "Redigerad override"


@pytest.mark.asyncio
async def test_two_customers_can_store_different_overrides(session: AsyncSession):
    await ensure_prompt_field_defaults(session, "dd", dd_prompt_defaults())
    field = await get_prompt_field_by_key(session, "help.system")
    assert field is not None
    first = Kund(name="A", slug="a", available_modules=["dd"])
    second = Kund(name="B", slug="b", available_modules=["dd"])
    session.add_all([first, second])
    await session.flush()
    session.add_all(
        [
            PromptOverride(
                customer_id=first.id,
                prompt_field_id=field.id,
                language="sv",
                text="A-text",
                updated_at=utcnow(),
            ),
            PromptOverride(
                customer_id=second.id,
                prompt_field_id=field.id,
                language="sv",
                text="B-text",
                updated_at=utcnow(),
            ),
        ]
    )
    await session.commit()
    rows = (await session.execute(select(PromptOverride))).scalars().all()
    by_customer = {row.customer_id: row.text for row in rows}
    assert by_customer == {first.id: "A-text", second.id: "B-text"}


@pytest.mark.asyncio
async def test_retire_unknown_prompt_fields_deletes_rows_overrides_and_config_keys(
    session: AsyncSession,
):
    await ensure_prompt_field_defaults(session, "politik", politik_prompt_defaults())
    await ensure_prompt_field_defaults(session, "dd", dd_prompt_defaults())
    customer = Kund(name="Acme", slug="acme", available_modules=["politik"])
    session.add(customer)
    await session.flush()
    leftover = PromptField(
        key="persona.from_slot.system",
        modules=["politik"],
        section="persona",
        label_sv="Legacy",
        label_en="Legacy",
        default_sv="old",
        default_en="old",
        default_nb="old",
        active=True,
        updated_at=utcnow(),
    )
    session.add(leftover)
    await session.flush()
    session.add(
        PromptOverride(
            customer_id=customer.id,
            prompt_field_id=leftover.id,
            language="sv",
            text="kundtext",
            updated_at=utcnow(),
        )
    )
    now = utcnow()
    session.add(
        Configuration(
            customer_id=customer.id,
            name="Standard (svenska)",
            language="sv",
            prompts={
                "persona.from_slot.system": "kvar i blob",
                "help.system": "behålls",
            },
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()

    removed = await retire_unknown_prompt_fields(session)
    assert removed == 1
    assert await get_prompt_field_by_key(session, "persona.from_slot.system") is None
    assert (await session.execute(select(PromptOverride))).scalars().all() == []
    config = (await session.execute(select(Configuration))).scalar_one()
    assert config.prompts == {"help.system": "behålls"}
    assert await retire_unknown_prompt_fields(session) == 0


@pytest.mark.asyncio
async def test_startup_seed_fills_catalog_without_default_overrides(client_db):
    _client, factory = client_db
    async with factory() as db:
        rows = (await db.execute(select(PromptField))).scalars().all()
        assert {row.key for row in rows} == {field["key"] for field in PROMPT_FIELDS}
        help_row = await get_prompt_field_by_key(db, "help.system")
        assert help_row is not None
        assert set(help_row.modules) == {"dd", "politik"}
        shared = await get_prompt_field_by_key(db, "panel.expert.system")
        assert shared is not None
        assert set(shared.modules) == {"dd", "politik", "expertgranskning", "rattsunderlag"}
        overrides = (await db.execute(select(PromptOverride))).scalars().all()
        assert overrides == []
