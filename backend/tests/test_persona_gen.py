"""Tests for persona_gen slot vs description flows."""

import pytest

from app.llm import persona_gen as persona_gen_mod
from app.schemas.domain import EditablePersona
from app.services.prompt_catalog import default_prompts


@pytest.mark.asyncio
async def test_llm_personas_from_description_still_calls_llm(monkeypatch):
    calls = 0

    async def fake_generate(_messages):
        nonlocal calls
        calls += 1
        return EditablePersona(
            name=f"Person {calls}",
            initials="P1",
            age="35",
            kön="Kvinna",
            ort="Centrum",
            yrke="Lärare",
            lutning="Mitt",
            anekdot="—",
        )

    monkeypatch.setattr(persona_gen_mod, "generate_editable_persona", fake_generate)
    profiles = await persona_gen_mod.llm_personas_from_description(
        "En engagerad förälder",
        count=2,
        prompts=default_prompts("sv"),
    )
    assert calls == 2
    assert len(profiles) == 2
    assert profiles[0].name == "Person 1"
