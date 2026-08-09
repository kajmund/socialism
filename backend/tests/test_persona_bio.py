"""Tests for persona bio join used in report segmentation."""

from app.services.report.bundles import RunBundle
from app.services.report.persona_bio import (
    bio_fields_from_profile,
    build_agent_bio_by_index,
    persona_record_from_member,
    segment_value,
)
from app.schemas.domain import EditablePersona


def test_bio_fields_from_profile_uses_district_fallback():
    profile = EditablePersona(
        name="Anna",
        ort="—",
        livssituation="Sambo, barn",
        lutning="Center",
    )
    bio = bio_fields_from_profile(profile, district="Hageby", age=34)
    assert bio["ort"] == "Hageby"
    assert bio["livssituation"] == "Sambo, barn"
    assert bio["lutning"] == "Center"
    assert bio["age"] == "34"


def test_persona_record_includes_bio_and_persona_id():
    row = persona_record_from_member(
        persona_id="p-1",
        name="Bo Nilsson",
        age=52,
        occ="Lärare",
        district="Lindö",
        trait="",
        profile_data={
            "livssituation": "Ensamhushåll",
            "lutning": "Höger",
            "ort": "Lindö",
        },
    )
    assert row["persona_id"] == "p-1"
    assert row["bio"]["livssituation"] == "Ensamhushåll"
    assert row["bio"]["yrke"] == "Lärare"


def test_build_agent_bio_by_index_joins_persona_id():
    bundle = RunBundle(
        label="Test",
        run_id=1,
        run_name="Test",
        attempt_id="att_1",
        seed=None,
        engine="oasis",
        agents=[
            {"index": 0, "persona_id": "p-1", "member_name": "Anna", "role": "population"},
            {"index": 1, "persona_id": "p-2", "member_name": "Bo", "role": "population"},
            {"index": 99, "persona_id": None, "member_name": "Inject", "role": "injector"},
        ],
        personas=[
            {
                "persona_id": "p-1",
                "name": "Anna",
                "bio": {"livssituation": "Sambo, barn", "ort": "Centrum", "lutning": "Vänster"},
            },
            {
                "persona_id": "p-2",
                "name": "Bo",
                "bio": {"livssituation": "Ensamhushåll", "ort": "Hageby", "lutning": "Höger"},
            },
        ],
    )
    by_index = build_agent_bio_by_index(bundle)
    assert 99 not in by_index
    assert by_index[0]["livssituation"] == "Sambo, barn"
    assert by_index[1]["ort"] == "Hageby"


def test_build_agent_bio_falls_back_to_member_name():
    bundle = RunBundle(
        label="Test",
        run_id=1,
        run_name="Test",
        attempt_id="att_1",
        seed=None,
        engine=None,
        agents=[{"index": 3, "member_name": "Carl", "role": "population"}],
        personas=[
            {
                "persona_id": None,
                "name": "Carl",
                "bio": {"livssituation": "Gift, vuxna barn"},
            },
        ],
    )
    assert build_agent_bio_by_index(bundle)[3]["livssituation"] == "Gift, vuxna barn"


def test_segment_value_normalizes_empty():
    assert segment_value({"livssituation": "—"}, "livssituation") == ""
    assert segment_value({"livssituation": "Ensamhushåll"}, "livssituation") == "Ensamhushåll"
