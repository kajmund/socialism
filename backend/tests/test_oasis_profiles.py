from app.database.models import Persona, PopulationMember
from app.services.oasis_profiles import (
    build_user_char,
    members_to_profiles,
    write_twitter_profile_csv,
)


def _member(
    *,
    name: str = "Anna Andersson",
    persona: Persona | None = None,
    trait: str = "pragmatisk",
    member_id: int = 1,
) -> PopulationMember:
    return PopulationMember(
        id=member_id,
        population_id=1,
        persona_id=persona.id if persona else None,
        name=name,
        initials="AA",
        age=42,
        occ="Lärare",
        district="Centrum",
        trait=trait,
        persona=persona,
    )


def test_build_user_char_includes_profile_and_swedish_instruction():
    persona = Persona(
        id="aa01",
        name="Anna Andersson",
        age=42,
        occ="Lärare",
        district="Centrum",
        quote="Skolan först",
        origin="manuell",
        profile={
            "name": "Anna Andersson",
            "age": "42",
            "ort": "Norrköping",
            "yrke": "Lärare",
            "lutning": "center",
            "parti": "C",
            "sakfragor": "skola",
            "ton": "saklig",
            "sprak": "rikssvenska",
        },
    )
    text = build_user_char(_member(persona=persona))
    assert "Anna Andersson" in text
    assert "center" in text
    assert "Skolan först" in text
    assert "svenska" in text.lower()


def test_members_to_profiles_caps_and_csv(tmp_path):
    members = [
        _member(name="Anna Andersson", member_id=1),
        _member(name="Bertil Berg", member_id=2),
        _member(name="Cecilia Carlsson", member_id=3),
    ]
    profiles = members_to_profiles(members, max_agents=2)
    assert len(profiles) == 2
    assert profiles[0].username.startswith("Anna_Andersson")
    path = write_twitter_profile_csv(profiles, tmp_path / "profiles.csv")
    content = path.read_text(encoding="utf-8")
    assert "username,description,user_char" in content
    assert "Anna_Andersson_0" in content
    assert "Bertil_Berg_1" in content
    assert "Cecilia" not in content
