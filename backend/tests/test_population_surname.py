"""Surname uniqueness during population generation."""

from random import Random

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base

from app.llm.persona_gen import SlotPlan
from app.schemas.domain import (
    DistGroup,
    DistRow,
    EditablePersona,
    GeneratedPersonaOut,
    PopulationGenerateRequest,
    PopulationRecipe,
)
from app.services import population_generate as gen
from app.services.persona_catalog import LASTN
from app.services.population_generate import (
    _assign_unique_names,
    sample_slot,
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


@pytest.fixture
async def gen_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


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
async def test_run_generate_at_max_size_has_no_surname_catalog_warnings(
    stub_generator, gen_session
):
    recipe = _minimal_recipe(40)
    body = PopulationGenerateRequest(recipe=recipe, mode="replace")
    response = await gen.run_generate(body, library_personas={}, session=gen_session)
    assert not any(
        "efternamn" in w.casefold() or "disambiguerades" in w.casefold()
        for w in response.warnings
    )


@pytest.mark.asyncio
async def test_run_generate_resolves_names_when_catalog_exhausted(
    stub_generator, gen_session, monkeypatch
):
    monkeypatch.setattr(gen, "LASTN", ["Al-Amin", "Berg", "Karlsson"])
    size = 13
    recipe = _minimal_recipe(size)
    body = PopulationGenerateRequest(recipe=recipe, mode="replace")
    response = await gen.run_generate(body, library_personas={}, session=gen_session)
    names = [c.persona.name for c in response.candidates]
    assert len(names) == len(set(n.casefold() for n in names))
    surnames = [surname_from_name(n) for n in names]
    assert len(set(surnames)) <= 3
    assert response.warnings
    assert any(
        "efternamn" in w.casefold() or "disambiguerades" in w.casefold()
        for w in response.warnings
    )


@pytest.mark.asyncio
async def test_run_generate_keeps_catalog_ton(stub_generator, gen_session):
    recipe = _minimal_recipe(4)
    recipe.dist["ton"] = DistGroup(
        label="Ton",
        rows=[DistRow(k="saklig", l="Saklig och nyanserad", v=100)],
    )
    body = PopulationGenerateRequest(recipe=recipe, mode="replace")
    response = await gen.run_generate(body, library_personas={}, session=gen_session)
    assert [c.persona.profile.ton for c in response.candidates] == [
        "Saklig och nyanserad"
    ] * 4
    assert [c.persona.quote for c in response.candidates] == ["Saklig och nyanserad"] * 4


@pytest.mark.asyncio
async def test_run_generate_size_5_has_no_surname_warnings(stub_generator, gen_session):
    recipe = _minimal_recipe(5)
    body = PopulationGenerateRequest(recipe=recipe, mode="replace")
    response = await gen.run_generate(body, library_personas={}, session=gen_session)
    assert len(response.candidates) == 5
    surnames = [surname_from_name(c.persona.name) for c in response.candidates]
    assert len(surnames) == len(set(surnames))
    assert response.warnings == []


def test_validate_surname_uniqueness_detects_duplicates():
    from app.schemas.domain import GenerationCandidate

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


def test_assign_unique_names_avoids_surname_collisions():
    recipe = _minimal_recipe(5)
    rng = Random(0)
    slots = [sample_slot(recipe, rng) for _ in range(5)]
    used: set[str] = set()
    names, warnings = _assign_unique_names(slots, rng, used)
    assert len(names) == 5
    assert warnings == []
    assert len({surname_from_name(n) for n in names}) == 5


@pytest.mark.asyncio
async def test_llm_batch_uses_preassigned_names_and_waves(monkeypatch, gen_session):
    monkeypatch.setattr(gen.settings, "persona_generator", "deepseek")
    monkeypatch.setattr(gen.settings, "persona_generate_concurrency", 2)

    async def fake_prompts(session, **_kwargs):
        return {}

    monkeypatch.setattr(gen, "require_active_prompts", fake_prompts)

    seen_fixed: list[str] = []
    anecdote_prevs: list[tuple[str, ...]] = []

    async def fake_from_slot(
        slot,
        free_text="",
        *,
        session=None,
        taken_surnames=None,
        fixed_name=None,
        previous_personas=(),
        previous_anecdotes=(),
        prompts=None,
        include_anecdote=True,
    ):
        assert fixed_name
        assert include_anecdote is False
        seen_fixed.append(fixed_name)
        ton = slot.profile_fields.get("ton", "")
        profile = EditablePersona(
            name="WRONG Namnsson",
            initials="WN",
            age=str(slot.age),
            kön=slot.profile_fields.get("kön", "Kvinna"),
            ort=slot.district,
            yrke=slot.occ,
            lutning=slot.lean_label,
            ton=ton,
            anekdot="—",
        )
        # Real path overwrites fixed_name; simulate that contract.
        profile.name = fixed_name
        profile.initials = "XX"
        return GeneratedPersonaOut(
            name=fixed_name,
            initials="XX",
            age=slot.age,
            occ=slot.occ,
            district=slot.district,
            occ_key=slot.occ_key,
            district_key=slot.district_key,
            lean=slot.lean,
            lean_label=slot.lean_label,
            trait=ton,
            quote=ton,
            profile=profile,
        )

    async def fake_anecdote(profile, *, session=None, previous_anecdotes=(), prompts=None):
        anecdote_prevs.append(previous_anecdotes)
        return f"Igår gick {profile.name.split()[0]} till affären i {profile.ort}."

    monkeypatch.setattr(gen, "llm_persona_from_slot", fake_from_slot)
    monkeypatch.setattr(gen, "llm_persona_anecdote", fake_anecdote)

    recipe = _minimal_recipe(4, seed=7)
    body = PopulationGenerateRequest(recipe=recipe, mode="replace")
    response = await gen.run_generate(body, library_personas={}, session=gen_session)
    assert len(response.candidates) == 4
    names = [c.persona.name for c in response.candidates]
    assert len(names) == len(set(names))
    assert set(seen_fixed) == set(names)
    assert all(c.persona.profile.anekdot != "—" for c in response.candidates)
    # Wave size 2: second wave sees anecdotes from the first.
    assert anecdote_prevs[0] == ()
    assert anecdote_prevs[1] == ()
    assert len(anecdote_prevs[2]) == 2
    assert len(anecdote_prevs[3]) == 2


@pytest.mark.asyncio
async def test_llm_persona_from_slot_builds_profile_from_slot(monkeypatch):
    from app.llm import persona_gen as persona_gen_mod
    from app.services.prompt_catalog import default_prompts

    async def fail_generate(*_args, **_kwargs):
        raise AssertionError("generate_editable_persona must not be called for slot profiles")

    monkeypatch.setattr(persona_gen_mod, "generate_editable_persona", fail_generate)
    slot = SlotPlan(
        age=40,
        age_bucket="medel",
        district_key="centrum",
        district="Centrum",
        occ_key="utbildning",
        occ="Lärare",
        lean="mitt",
        lean_label="Mitt",
        profile_fields={
            "kön": "Kvinna",
            "ton": "Saklig och nyanserad",
            "parti": "S",
        },
    )
    out = await persona_gen_mod.llm_persona_from_slot(
        slot,
        fixed_name="Anna Lindqvist",
        prompts=default_prompts("sv"),
        include_anecdote=False,
    )
    assert out.name == "Anna Lindqvist"
    assert out.profile.name == "Anna Lindqvist"
    assert out.profile.kön == "Kvinna"
    assert out.profile.yrke == "Lärare"
    assert out.profile.ort == "Centrum"
    assert out.profile.lutning == "Mitt"
    assert out.profile.ton == "Saklig och nyanserad"
    assert out.profile.parti == "S"
    assert out.profile.anekdot == "—"
