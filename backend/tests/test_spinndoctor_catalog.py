"""Fas 5: Spinndoktor is a catalog persona; report context and panel brief stay separate."""

from __future__ import annotations

import pytest

from app.services.panel.spinndoctor_profile import (
    SPINNDOCTOR_KEY,
    require_spinndoctor_profile,
)
from app.services.panel.structured_scoring import (
    assemble_dd_moderator_messages,
    build_dd_moderator_identity,
)
from app.services.kund_store import default_os_customer_id
from app.services.prompt_store import require_active_prompts
from app.services.spindoctor_chat import (
    _build_identity_prompt,
    assemble_spindoctor_messages,
)


def test_assemble_spindoctor_messages_keeps_context_separate():
    messages = assemble_spindoctor_messages(
        identity="Du deltar som Spinndoktor",
        context="DD-rapport: Test",
        history=[{"role": "user", "content": "tidigare"}],
        user_message="Hur ser poängen ut?",
    )
    assert messages[0] == {"role": "system", "content": "Du deltar som Spinndoktor"}
    assert messages[1] == {"role": "system", "content": "DD-rapport: Test"}
    assert messages[0]["content"] != messages[1]["content"]
    assert "DD-rapport" not in str(messages[0]["content"])
    assert messages[-1] == {"role": "user", "content": "Hur ser poängen ut?"}


def test_assemble_dd_moderator_messages_keeps_brief_separate():
    messages = assemble_dd_moderator_messages(
        identity="Du deltar som Spinndoktor",
        brief="Test AB i Stockholm",
        user_content="Öppna panelen kort.",
    )
    assert messages[0] == {"role": "system", "content": "Du deltar som Spinndoktor"}
    assert messages[1] == {"role": "system", "content": "Test AB i Stockholm"}
    assert "Test AB" not in messages[0]["content"]
    assert messages[2] == {"role": "user", "content": "Öppna panelen kort."}


@pytest.mark.asyncio
async def test_spinndoctor_profile_seeded_for_dd_and_politik(client_db):
    _client, factory = client_db
    async with factory() as db:
        row = await require_spinndoctor_profile(db)
        assert row.key == SPINNDOCTOR_KEY
        assert set(row.modules) == {"dd", "politik", "expertgranskning"}
        assert row.name == "Spinndoktor"


@pytest.mark.asyncio
async def test_spinndoctor_is_not_a_default_dd_scoring_slot(client_db):
    from app.services.dd.expert_roles import load_expert_slots
    from app.services.kund_store import bolag_demo_customer_id

    _client, factory = client_db
    async with factory() as db:
        customer_id = await bolag_demo_customer_id(db)
        slots = await load_expert_slots(db, customer_id=customer_id)
        assert len(slots) == 4
        assert "spinndoctor" not in {slot.slot_id for slot in slots}


@pytest.mark.asyncio
async def test_identity_prompt_uses_panel_expert_system(client_db):
    _client, factory = client_db
    async with factory() as db:
        customer_id = await default_os_customer_id(db)
        identity = await _build_identity_prompt(
            db, locale="sv", customer_id=customer_id, module="politik"
        )
        assert "Du deltar som Spinndoktor" in identity
        assert "Politisk kommunikation" in identity
        assert "Du är Spinndoktorn" in identity
        assert "Förbjudna ord" in identity
        assert "Du har dataverktyg" in identity
        assert "## Kandidat" not in identity
        assert "## Körning" not in identity


@pytest.mark.asyncio
async def test_dd_moderator_identity_uses_catalog_and_policy(client_db):
    _client, factory = client_db
    async with factory() as db:
        customer_id = await default_os_customer_id(db)
        prompts = await require_active_prompts(
            db, customer_id=customer_id, module="dd", language="sv"
        )
        identity = await build_dd_moderator_identity(db, prompts)
        assert "Du deltar som Spinndoktor" in identity
        assert "Politisk kommunikation" in identity
        assert "Hitta inte på namn" in identity
        assert "Du är Spinndoktor och modererar en bolags-DD-panel" not in identity
        assert "Test AB" not in identity
