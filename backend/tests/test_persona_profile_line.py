"""Tests for persona profile line used in interview attribution."""

from app.services.report.persona_bio import persona_profile_line


def test_persona_profile_line_excludes_segment_dimension():
    bio = {
        "yrke": "Elektriker",
        "age": "55",
        "kön": "Man",
        "livssituation": "Ensamhushåll",
        "ort": "Hageby",
        "lutning": "Center",
    }
    line = persona_profile_line(bio, locale="sv", exclude_dimension="livssituation")
    assert "Elektriker" in line
    assert "55 år" in line
    assert "Hageby" in line
    assert "Ensamhushåll" not in line
