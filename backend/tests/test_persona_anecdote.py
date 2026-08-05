"""Persona anecdote generation."""

from random import Random

import pytest

from app.services.prompt_catalog import default_prompts
from app.llm.persona_anecdote import (
    anecdote_is_usable,
    llm_persona_anecdote,
    stub_persona_anecdote,
)
from app.schemas.domain import DistGroup, DistRow, EditablePersona, PopulationRecipe
from app.services.population_generate import sample_slot, stub_persona


def _profile(**kwargs: str) -> EditablePersona:
    base = EditablePersona(
        name="Anna Lindqvist",
        initials="AL",
        age="42",
        kön="Kvinna",
        ort="Centrum",
        yrke="Undersköterska",
        livssituation="Ensamstående med barn",
        lutning="Mitt",
        parti="—",
    )
    return base.model_copy(update=kwargs)


def test_stub_persona_anecdote_is_short_and_grounded():
    profile = _profile()
    text = stub_persona_anecdote(profile, Random(0))
    words = text.split()
    assert 4 <= len(words) <= 20
    assert "Centrum" in text or "Undersköterska" in text or "ensamstående" in text.casefold()


def test_stub_persona_includes_anekdot():
    recipe = PopulationRecipe(
        size=1,
        entryMode="manual",
        freeText="",
        locale="norrkoping",
        seed=1,
        dist={
            "age": DistGroup(label="Ålder", rows=[DistRow(k="medel", l="Medel", v=100)]),
            "district": DistGroup(label="Ort", rows=[DistRow(k="centrum", l="Centrum", v=100)]),
            "occupation": DistGroup(
                label="Yrke",
                rows=[DistRow(k="vard", l="Undersköterska", v=100)],
            ),
            "leaning": DistGroup(label="Lutning", rows=[DistRow(k="mitt", l="Mitt", v=100)]),
        },
    )
    persona = stub_persona(recipe, Random(3))
    assert persona.profile.anekdot not in ("", "—")
    assert len(persona.profile.anekdot.split()) <= 20


def test_anecdote_is_usable_rejects_political_wording():
    profile = _profile(parti="Moderaterna")
    assert anecdote_is_usable(
        "Jag sympatiserar med Moderaterna eftersom skatten är viktig.",
        profile,
    ) is False
    assert anecdote_is_usable(
        "Förra veckan stod jag i kö vid bussen i Centrum i regnet.",
        profile,
    ) is True


@pytest.mark.asyncio
async def test_llm_persona_anecdote_uses_structured_completer(monkeypatch):
    from app.llm import set_structured_completer
    from app.schemas.domain import PersonaAnecdoteOut

    calls: list[str] = []

    async def stub(messages, response_model):
        assert response_model is PersonaAnecdoteOut
        calls.append(messages[-1]["content"])
        return PersonaAnecdoteOut(
            anekdot="Min syster jobbar också som undersköterska i Centrum och skickade bilder igår."
        )

    set_structured_completer(stub)
    try:
        text = await llm_persona_anecdote(_profile(), prompts=default_prompts("sv"))
    finally:
        set_structured_completer(None)

    assert "Undersköterska" in calls[0]
    assert "politisk" in calls[0].casefold()
    assert "Centrum" in text


def test_sample_slot_does_not_assign_anekdot():
    recipe = PopulationRecipe(
        size=1,
        entryMode="manual",
        freeText="",
        locale="norrkoping",
        seed=1,
        dist={
            "age": DistGroup(label="Ålder", rows=[DistRow(k="medel", l="Medel", v=100)]),
            "district": DistGroup(label="Ort", rows=[DistRow(k="centrum", l="Centrum", v=100)]),
            "occupation": DistGroup(
                label="Yrke",
                rows=[DistRow(k="vard", l="Undersköterska", v=100)],
            ),
            "leaning": DistGroup(label="Lutning", rows=[DistRow(k="mitt", l="Mitt", v=100)]),
            "ton": DistGroup(label="Ton", rows=[DistRow(k="sak", l="Saklig", v=100)]),
        },
    )
    slot = sample_slot(recipe, Random(0))
    assert "anekdot" not in slot.profile_fields
