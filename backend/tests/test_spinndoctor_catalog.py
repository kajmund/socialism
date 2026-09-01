"""Fas 5: report-chat Spinndoktor is a catalog persona; context is a separate message."""

from __future__ import annotations

import pytest

from app.services.panel.spinndoctor_profile import (
    SPINNDOCTOR_KEY,
    require_spinndoctor_profile,
)
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


@pytest.mark.asyncio
async def test_spinndoctor_profile_seeded_for_dd_and_politik(client_db):
    _client, factory = client_db
    async with factory() as db:
        row = await require_spinndoctor_profile(db)
        assert row.key == SPINNDOCTOR_KEY
        assert set(row.modules) == {"dd", "politik"}
        assert row.name == "Spinndoktor"


@pytest.mark.asyncio
async def test_identity_prompt_uses_panel_expert_system(client_db):
    _client, factory = client_db
    async with factory() as db:
        identity = await _build_identity_prompt(db, locale="sv")
        assert "Du deltar som Spinndoktor" in identity
        assert "Politisk kommunikation" in identity
        assert "Du har dataverktyg" in identity
        assert "## Kandidat" not in identity
        assert "## Körning" not in identity
