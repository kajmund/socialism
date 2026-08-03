"""Recipe dist groups beyond age/district/occ/lean must shape generated profiles."""

from random import Random

from app.schemas.domain import DistGroup, DistRow, PopulationRecipe
from app.services.population_generate import sample_slot, stub_persona


def _recipe_with_extras() -> PopulationRecipe:
    return PopulationRecipe(
        size=4,
        entryMode="manual",
        freeText="",
        locale="norrkoping",
        seed=1,
        dist={
            "age": DistGroup(
                label="Ålder",
                rows=[DistRow(k="medel", l="Medel", v=100)],
            ),
            "district": DistGroup(
                label="Ort",
                rows=[DistRow(k="centrum", l="Centrum", v=100)],
            ),
            "occupation": DistGroup(
                label="Yrke",
                rows=[DistRow(k="vard", l="Undersköterska", v=100)],
            ),
            "leaning": DistGroup(
                label="Lutning",
                rows=[DistRow(k="vanster", l="Vänster", v=100)],
            ),
            "ton": DistGroup(
                label="Ton",
                rows=[DistRow(k="sark", l="Sarkastisk och otålig", v=100)],
            ),
            "parti": DistGroup(
                label="Parti",
                rows=[DistRow(k="v", l="Vänsterpartiet", v=100)],
            ),
            "education": DistGroup(
                label="Utbildning",
                rows=[DistRow(k="gym", l="Gymnasium", v=100)],
            ),
            "sprak": DistGroup(
                label="Språk",
                rows=[DistRow(k="kort", l="Kort och konkret", v=100)],
            ),
        },
    )


def test_sample_slot_includes_catalog_profile_fields():
    slot = sample_slot(_recipe_with_extras(), Random(0))
    assert slot.profile_fields["ton"] == "Sarkastisk och otålig"
    assert slot.profile_fields["parti"] == "Vänsterpartiet"
    assert slot.profile_fields["utbildning"] == "Gymnasium"
    assert slot.profile_fields["sprak"] == "Kort och konkret"


def test_stub_persona_applies_ton_and_parti():
    persona = stub_persona(_recipe_with_extras(), Random(0))
    assert persona.profile.ton == "Sarkastisk och otålig"
    assert persona.profile.parti == "Vänsterpartiet"
    assert persona.profile.utbildning == "Gymnasium"
    assert persona.profile.sprak == "Kort och konkret"
    assert persona.quote == "Sarkastisk och otålig"
