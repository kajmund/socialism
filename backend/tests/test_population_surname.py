"""Surname uniqueness during population generation."""

from random import Random

import pytest

from app.schemas.domain import DistGroup, DistRow, PopulationGenerateRequest, PopulationRecipe
from app.services import population_generate as gen
from app.services.persona_catalog import LASTN
from app.services.population_generate import (
    surname_from_name,
    stub_persona,
    validate_surname_uniqueness,
)


def _minimal_recipe(size: int, *, seed: int = 42) -> PopulationRecipe:
    return PopulationRecipe(
        size=size,
        locale="local",
        seed=seed,
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


@pytest.fixture
def stub_generator(monkeypatch):
    monkeypatch.setattr(gen.settings, "persona_generator", "stub")


def test_surname_from_name_uses_last_token():
    assert surname_from_name("Anna Lindqvist") == "lindqvist"
    assert surname_from_name("Erik") == "erik"


def test_stub_persona_avoids_surname_reuse_within_batch():
    used: set[str] = set()
    recipe = _minimal_recipe(5)
    rng = Random(0)
    names: list[str] = []
    for _ in range(5):
        persona = stub_persona(recipe, rng, used_surnames=used)
        names.append(persona.name)
    surnames = [surname_from_name(n) for n in names]
    assert len(surnames) == len(set(surnames))


@pytest.mark.asyncio
async def test_run_generate_size_13_warns_when_stub_catalog_exhausted(stub_generator):
    recipe = _minimal_recipe(13)
    body = PopulationGenerateRequest(recipe=recipe, mode="replace")
    response = await gen.run_generate(body, library_personas={})
    surnames = [surname_from_name(c.persona.name) for c in response.candidates]
    assert len(set(surnames)) <= len(LASTN)
    assert response.warnings
    assert any("efternamn" in w.casefold() for w in response.warnings)


@pytest.mark.asyncio
async def test_run_generate_size_5_has_no_surname_warnings(stub_generator):
    recipe = _minimal_recipe(5)
    body = PopulationGenerateRequest(recipe=recipe, mode="replace")
    response = await gen.run_generate(body, library_personas={})
    assert len(response.candidates) == 5
    surnames = [surname_from_name(c.persona.name) for c in response.candidates]
    assert len(surnames) == len(set(surnames))
    assert response.warnings == []


def test_stub_batch_same_occ_key_gets_distinct_writing_traits():
    from app.llm.persona_gen import SlotPlan
    from app.services.population_generate import _writing_traits_for_slots

    slots = [
        SlotPlan(
            age=40,
            age_bucket="medel",
            district_key="centrum",
            district="Centrum",
            occ_key="utbildning",
            occ="Lärare",
            lean="mitt",
            lean_label="Mitt",
        ),
        SlotPlan(
            age=41,
            age_bucket="medel",
            district_key="centrum",
            district="Centrum",
            occ_key="utbildning",
            occ="Lärare",
            lean="mitt",
            lean_label="Mitt",
        ),
    ]
    traits = _writing_traits_for_slots(slots, Random(1))
    assert traits[0] != traits[1]


def test_validate_surname_uniqueness_detects_duplicates():
    from app.schemas.domain import EditablePersona, GeneratedPersonaOut, GenerationCandidate

    def cand(name: str) -> GenerationCandidate:
        profile = EditablePersona(name=name, initials="AA", age="40", ort="X", yrke="Y")
        persona = GeneratedPersonaOut(
            name=name,
            initials="AA",
            age=40,
            occ="Y",
            district="X",
            occ_key="",
            district_key="",
            lean="mitt",
            lean_label="Mitt",
            trait="",
            quote="",
            profile=profile,
        )
        return GenerationCandidate(key="k1", source="generated", persona=persona)

    warnings = validate_surname_uniqueness(
        [cand("Anna Lindqvist"), cand("Bo Lindqvist")]
    )
    assert len(warnings) == 1
    assert "Lindqvist" in warnings[0]
