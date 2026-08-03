from app.database.models import Persona, PopulationMember
from app.schemas.domain import Injection, Tick
from app.services.oasis_profiles import (
    build_run_profiles,
    build_user_char,
    injector_key,
    injectors_from_ticks,
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


def test_injectors_from_ticks_dedupes_by_type_and_sender():
    ticks = [
        Tick(
            key="t1",
            day=1,
            injections=[
                Injection(
                    key="i1",
                    type="party_post",
                    sender="@Socialdemokraterna",
                    text="Budskap A",
                ),
                Injection(
                    key="i2",
                    type="party_post",
                    sender="Socialdemokraterna",
                    text="Budskap B",
                ),
                Injection(
                    key="i3",
                    type="news_post",
                    sender="NT",
                    text="Nyhet",
                ),
            ],
        ),
        Tick(key="t2", day=2, injections=[]),
    ]
    injectors = injectors_from_ticks(ticks)
    assert len(injectors) == 2
    assert injectors[0].role == "injector"
    assert injectors[0].member_name == "Socialdemokraterna"
    assert "väljare" in injectors[0].user_char
    assert injectors[1].member_name == "NT"
    assert injector_key(ticks[0].injections[0]) == injector_key(ticks[0].injections[1])


def test_build_run_profiles_puts_injectors_before_population():
    members = [
        _member(name="Bo Lindgren", member_id=1),
        _member(name="Göran Svensson", member_id=2),
    ]
    ticks = [
        Tick(
            key="t1",
            day=1,
            injections=[
                Injection(
                    key="i1",
                    type="party_post",
                    sender="@Socialdemokraterna",
                    text="Hej",
                )
            ],
        )
    ]
    profiles, key_to_index = build_run_profiles(members, ticks, max_agents=5)
    assert profiles[0].role == "injector"
    assert profiles[0].member_name == "Socialdemokraterna"
    assert profiles[1].role == "population"
    assert profiles[1].member_name == "Bo Lindgren"
    assert key_to_index["party_post:socialdemokraterna"] == 0


def test_build_run_profiles_respects_combined_agent_cap():
    members = [
        _member(name="Bo Lindgren", member_id=1),
        _member(name="Göran Svensson", member_id=2),
        _member(name="Eva Nilsson", member_id=3),
    ]
    ticks = [
        Tick(
            key="t1",
            day=1,
            injections=[
                Injection(
                    key="i1",
                    type="party_post",
                    sender="@Socialdemokraterna",
                    text="Hej",
                ),
                Injection(
                    key="i2",
                    type="news_post",
                    sender="NT",
                    text="Nyhet",
                ),
            ],
        )
    ]
    profiles, key_to_index = build_run_profiles(members, ticks, max_agents=2)
    assert len(profiles) == 2
    assert all(p.role == "injector" for p in profiles)
    assert "party_post:socialdemokraterna" in key_to_index
    assert "news_post:nt" in key_to_index

    mixed, _ = build_run_profiles(members, ticks, max_agents=3)
    assert len(mixed) == 3
    assert mixed[0].role == "injector"
    assert mixed[1].role == "injector"
    assert mixed[2].role == "population"
