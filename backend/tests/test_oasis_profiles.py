import json

from app.database.models import Persona, PopulationMember
from app.schemas.domain import Injection, Tick
from app.services.oasis_profiles import (
    build_run_profiles,
    build_user_char,
    injector_key,
    injectors_from_ticks,
    members_to_profiles,
    oasis_gender_from_kon,
    write_reddit_profile_json,
    write_twitter_profile_csv,
)
from app.services.prompt_catalog import default_prompts

_PROMPTS = default_prompts("sv")


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
            "kön": "Kvinna",
            "ort": "Centrum",
            "yrke": "Lärare",
            "lutning": "center",
            "parti": "C",
            "sakfragor": "skola",
            "ton": "saklig",
            "sprak": "rikssvenska",
        },
    )
    text = build_user_char(_member(persona=persona), prompts=_PROMPTS)
    assert "Anna Andersson" in text
    assert "kvinna" in text
    assert "center" in text
    assert "Skolan först" in text
    assert "svensk" in text.lower()
    assert "like_post" in text
    assert "dislike_post" in text
    assert "gilla INTE" in text
    assert "Temperament" in text
    assert "invändning" in text
    assert "nämna andra personer" in text
    assert "author_first_name" in text
    assert "Som Erik säger" not in text
    assert "Kommentar 3" in text  # still banned as numbered ref
    assert "Undvik att upprepa politikerns" in text


def test_build_user_char_includes_anekdot_when_present():
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
            "kön": "Kvinna",
            "ort": "Centrum",
            "yrke": "Lärare",
            "lutning": "center",
            "parti": "C",
            "anekdot": "Förra veckan såg jag elever vänta i regnet vid skolans cykelställ.",
        },
    )
    text = build_user_char(_member(persona=persona), prompts=_PROMPTS)
    assert "Förra veckan såg jag elever vänta i regnet vid skolans cykelställ." in text
    assert "Personlig vardagsdetalj" in text


def test_build_user_char_places_voice_before_occupation():
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
            "kön": "Kvinna",
            "ort": "Centrum",
            "yrke": "Lärare",
            "lutning": "center",
            "parti": "C",
            "sakfragor": "skola",
            "ton": "saklig",
            "sprak": "rikssvenska",
        },
    )
    text = build_user_char(_member(persona=persona, trait="Ironisk och snabb"), prompts=_PROMPTS)
    trait_idx = text.index("Temperament")
    occ_idx = text.index("Yrke:")
    politics_idx = text.index("Politisk lutning")
    assert trait_idx < occ_idx < politics_idx
    assert "Din röst och temperament" in text
    assert "Ton:" not in text


def test_write_reddit_profile_json_includes_gender_and_persona(tmp_path):
    persona = Persona(
        id="aa01",
        name="Anna Andersson",
        age=42,
        occ="Lärare",
        district="Centrum",
        quote="",
        origin="manuell",
        profile={
            "name": "Anna Andersson",
            "age": "42",
            "kön": "Kvinna",
            "ort": "Centrum",
            "yrke": "Lärare",
            "lutning": "Mitt",
        },
    )
    profiles = members_to_profiles(
        [_member(persona=persona)], prompts=_PROMPTS, platform="reddit"
    )
    assert "kvinna" in profiles[0].description
    path = write_reddit_profile_json(profiles, tmp_path / "profiles.json")
    rows = json.loads(path.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["gender"] == "female"
    assert rows[0]["realname"] == "Anna Andersson"
    assert rows[0]["bio"]
    assert "like_post" in rows[0]["persona"]
    assert oasis_gender_from_kon("Man") == "male"
    assert oasis_gender_from_kon("Icke-binär") == "nonbinary"


def test_injector_user_char_forbids_likes_and_dislikes():
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
            ],
        ),
    ]
    injectors = injectors_from_ticks(ticks, prompts=_PROMPTS)
    assert "ogillar inte" in injectors[0].user_char


def test_members_to_profiles_all_and_csv(tmp_path):
    members = [
        _member(name="Anna Andersson", member_id=1),
        _member(name="Bertil Berg", member_id=2),
        _member(name="Cecilia Carlsson", member_id=3),
    ]
    profiles = members_to_profiles(members, prompts=_PROMPTS)
    assert len(profiles) == 3
    assert profiles[0].username.startswith("Anna_Andersson")
    path = write_twitter_profile_csv(profiles, tmp_path / "profiles.csv")
    content = path.read_text(encoding="utf-8")
    assert "username,description,user_char" in content
    assert "Anna_Andersson_0" in content
    assert "Bertil_Berg_1" in content
    assert "Cecilia_Carlsson_2" in content


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
    injectors = injectors_from_ticks(ticks, prompts=_PROMPTS)
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
    profiles, key_to_index = build_run_profiles(members, ticks, prompts=_PROMPTS)
    assert profiles[0].role == "injector"
    assert profiles[0].member_name == "Socialdemokraterna"
    assert profiles[1].role == "population"
    assert profiles[1].member_name == "Bo Lindgren"
    assert profiles[2].member_name == "Göran Svensson"
    assert key_to_index["party_post:socialdemokraterna"] == 0


def test_build_run_profiles_includes_full_population_plus_injectors():
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
    profiles, key_to_index = build_run_profiles(members, ticks, prompts=_PROMPTS)
    assert len(profiles) == 5
    assert profiles[0].role == "injector"
    assert profiles[1].role == "injector"
    assert [p.member_name for p in profiles if p.role == "population"] == [
        "Bo Lindgren",
        "Göran Svensson",
        "Eva Nilsson",
    ]
    assert "party_post:socialdemokraterna" in key_to_index
    assert "news_post:nt" in key_to_index
