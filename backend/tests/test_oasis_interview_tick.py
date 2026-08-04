"""Unit tests for planned OASIS INTERVIEW resolution (no camel-oasis)."""

from dataclasses import dataclass

from app.schemas.domain import TickInterview
from app.services.oasis_run import population_action_names, resolve_tick_interviews


@dataclass
class _Profile:
    persona_id: str | None
    role: str = "population"


def test_population_actions_never_include_interview():
    for platform in ("twitter", "reddit"):
        names = population_action_names(platform=platform)  # type: ignore[arg-type]
        assert "INTERVIEW" not in names
        names_create = population_action_names(
            allow_population_create_post=True,
            platform=platform,  # type: ignore[arg-type]
        )
        assert "INTERVIEW" not in names_create


def test_resolve_tick_interviews_maps_persona_to_agent_index():
    profiles = [
        _Profile(persona_id=None, role="injector"),
        _Profile(persona_id="p-anna"),
        _Profile(persona_id="p-bo"),
    ]
    interviews = [
        TickInterview(key="i1", persona_id="p-bo", prompt="Vad tyckte du?"),
        TickInterview(key="i2", persona_id="p-anna", prompt="  Hur mår du?  "),
    ]
    assert resolve_tick_interviews(interviews, profiles) == [
        (2, "Vad tyckte du?"),
        (1, "Hur mår du?"),
    ]


def test_resolve_tick_interviews_skips_unknown_and_empty():
    profiles = [_Profile(persona_id="p-anna")]
    interviews = [
        TickInterview(key="i1", persona_id="missing", prompt="Hej"),
        TickInterview(key="i2", persona_id="p-anna", prompt="   "),
        {"persona_id": "p-anna", "prompt": "Ok?"},
    ]
    assert resolve_tick_interviews(interviews, profiles) == [(0, "Ok?")]
