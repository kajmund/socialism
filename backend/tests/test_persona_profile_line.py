"""Tests for persona profile line used in interview attribution."""

from app.services.report.persona_bio import persona_profile_line


def test_persona_profile_line_format():
    bio = {
        "yrke": "Butiksbiträde",
        "age": "29",
        "kön": "Kvinna",
        "livssituation": "Sambo, barn",
        "ort": "Hageby",
        "lutning": "Höger",
    }
    assert persona_profile_line(bio, locale="sv") == (
        "Butiksbiträde · 29 år · Hageby · lutning höger"
    )


def test_persona_profile_line_excludes_segment_dimension():
    bio = {
        "yrke": "Elektriker",
        "age": "55",
        "kön": "Man",
        "livssituation": "Ensamhushåll",
        "ort": "Hageby",
        "lutning": "Center",
    }
    line = persona_profile_line(bio, locale="sv", exclude_dimension="ort")
    assert line == "Elektriker · 55 år · lutning center"
    assert "Hageby" not in line
    assert "Man" not in line
    assert "Ensamhushåll" not in line
