"""Unit tests for interview system prompts."""

from app.llm.chat import build_chat_system_prompt, build_run_interview_prompt
from app.schemas.domain import EditablePersona
from app.services.prompt_catalog import default_prompts

_PROMPTS = default_prompts("sv")


def _profile(**overrides: str) -> EditablePersona:
    base = EditablePersona(
        name="Anna",
        age="40",
        kön="kvinna",
        ort="Centrum",
        yrke="Lärare",
        anekdot="Jag tar alltid en kaffe på pressbyrån.",
    )
    return base.model_copy(update=overrides)


def test_chat_prompt_includes_anekdot():
    prompt = build_chat_system_prompt(_profile(), "interview", prompts=_PROMPTS)
    assert "Vardagsdetalj" in prompt
    assert "kaffe på pressbyrån" in prompt


def test_run_interview_prompt_blocks_future_context():
    prompt = build_run_interview_prompt(
        _profile(),
        "=== Flöde ===\n- Nyhet dag 1",
        prompts=_PROMPTS,
        day=1,
        tick_index=0,
    )
    assert "efter dag 1" in prompt
    assert "tick 1" in prompt
    assert "Nyhet dag 1" in prompt
    assert "inte sett något" in prompt.casefold()
