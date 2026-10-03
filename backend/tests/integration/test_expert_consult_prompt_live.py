"""Live check: the expert consult prompt makes the active model call ask_expert.

Opt-in. Default pytest skips it, including CI.

    RUN_EXPERT_TOOL_PROMPT_INTEGRATION=1 uv run pytest \
      tests/integration/test_expert_consult_prompt_live.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database.models import Persona, PersonaMessage
from app.database_url import normalize_database_url
from app.llm import complete_with_tools, set_tools_completer
from app.llm.chat import build_chat_system_prompt
from app.llm.runtime_override import default_configuration, set_runtime_selection_cache
from app.llm.selection import resolve_llm_runtime
from app.schemas.domain import EditablePersona
from app.serializers import profile_from_dict
from app.services.actor_profiles import actor_tool_specs
from app.services.dd.company_mcp import (
    _ALLABOLAG_SPECS,
    _CONSULT_TOOL_SPEC,
    _RESEARCH_TOOL_SPEC,
)
from app.services.expert_tools import default_expert_tools, expert_tool_prompt_extra
from app.services.llm_runtime_settings import refresh_prompt_runtime_cache
from app.services.oasis_agent_tools import search_tool_specs
from app.services.prompt_store import filled_prompts, module_for_persona_kind

pytestmark = pytest.mark.integration

_ENV_FLAG = "RUN_EXPERT_TOOL_PROMPT_INTEGRATION"
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_PLACEHOLDERS = frozenset({"", "test-key-not-real", "test-openai-key-not-real"})


def _opted_in() -> bool:
    return os.environ.get(_ENV_FLAG) == "1"


def _placeholder(value: str) -> bool:
    stripped = value.strip()
    return stripped in _PLACEHOLDERS or stripped.startswith("placeholder")


def _dotenv_values() -> dict[str, str]:
    path = _BACKEND_ROOT / ".env"
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        values[key.strip()] = raw.strip().strip('"').strip("'")
    return values


def _apply_live_secrets(env_file: dict[str, str]) -> dict[str, str]:
    """Return the previous settings values after copying real keys onto settings."""
    previous = {
        "deepseek_api_key": settings.deepseek_api_key,
        "cerebras_api_key": settings.cerebras_api_key,
    }
    for field, env_name in (
        ("deepseek_api_key", "DEEPSEEK_API_KEY"),
        ("cerebras_api_key", "CEREBRAS_API_KEY"),
    ):
        current = getattr(settings, field)
        if not _placeholder(current):
            continue
        # conftest sets a dummy key before Settings loads, so the process env
        # hides the real key in backend/.env.
        from_env = os.environ.get(env_name, "").strip()
        if _placeholder(from_env):
            from_env = ""
        candidate = from_env or env_file.get(env_name, "")
        if _placeholder(candidate):
            pytest.skip(f"{env_name} must be a real key in the environment or backend/.env")
        setattr(settings, field, candidate)
    return previous


def _restore_secrets(previous: dict[str, str]) -> None:
    settings.deepseek_api_key = previous["deepseek_api_key"]
    settings.cerebras_api_key = previous["cerebras_api_key"]


def _expert_tool_specs() -> list[dict]:
    return [
        *_ALLABOLAG_SPECS,
        *search_tool_specs(),
        _RESEARCH_TOOL_SPEC,
        _CONSULT_TOOL_SPEC,
        *actor_tool_specs(),
    ]


_RESEND_USER = "den skickades aldrig, skicka den igen"


def _messages_through_resend(
    prompts: dict[str, str],
    profile: EditablePersona,
    transcript: list[tuple[str, str]],
) -> list[dict]:
    extra = expert_tool_prompt_extra(prompts, default_expert_tools())
    system = build_chat_system_prompt(
        profile,
        "interview",
        prompts=prompts,
        extra_system=extra,
        profile_kind="expert",
    )
    matches = [
        index
        for index, (role, content) in enumerate(transcript)
        if role == "user" and content == _RESEND_USER
    ]
    if not matches:
        pytest.skip(f"live interview has no user turn {_RESEND_USER!r}")
    cutoff = matches[-1]
    history = transcript[: cutoff + 1]
    return [{"role": "system", "content": system}, *[{"role": role, "content": text} for role, text in history]]


async def _live_resend_messages() -> list[dict]:
    env_file = _dotenv_values()
    database_url = env_file.get("DATABASE_URL", "").strip()
    if not database_url or database_url.startswith("sqlite"):
        pytest.skip("backend/.env DATABASE_URL must point at the live Postgres database")
    engine = create_async_engine(normalize_database_url(database_url))
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            persona = await session.get(Persona, "exp_1_jurist")
            if persona is None:
                pytest.skip("live database has no expert exp_1_jurist")
            await refresh_prompt_runtime_cache(session)
            prompts = await filled_prompts(
                session,
                customer_id=persona.customer_id,
                language="sv",
                module=module_for_persona_kind("expert"),
            )
            rows = list(
                (
                    await session.execute(
                        select(PersonaMessage)
                        .where(
                            PersonaMessage.persona_id == persona.id,
                            PersonaMessage.mode == "interview",
                            PersonaMessage.run_id.is_(None),
                        )
                        .order_by(PersonaMessage.id.asc())
                    )
                ).scalars()
            )
            profile = profile_from_dict(persona.profile, persona.name)
            transcript = [(row.role, row.content) for row in rows]
            await session.rollback()
    finally:
        await engine.dispose()
    consult = prompts["chat.expert.consult_tool"]
    assert "Härma inte" in consult
    assert "visa aldrig verktygsanropet" not in consult.casefold()
    return _messages_through_resend(prompts, profile, transcript)


def _ask_expert_question(reply: object) -> str:
    calls = getattr(reply, "tool_calls", None) or []
    for call in calls:
        function = call.function
        if function.name != "ask_expert":
            continue
        arguments = json.loads(function.arguments or "{}")
        return str(arguments.get("question") or "").strip()
    names = [call.function.name for call in calls]
    content = getattr(reply, "content", None)
    raise AssertionError(
        "modellen anropade inte ask_expert. "
        f"verktyg={names or 'inga'} text={content!r}"
    )


async def test_resend_after_fake_sends_calls_ask_expert() -> None:
    if not _opted_in():
        pytest.skip(
            f"set {_ENV_FLAG}=1 to check the consult prompt against the active model"
        )
    previous = _apply_live_secrets(_dotenv_values())
    set_tools_completer(None)
    try:
        messages = await _live_resend_messages()
        resolution = await resolve_llm_runtime(
            prompt_key="chat.mode.interview",
            messages=messages,
            call_kind="tools",
        )
        active = default_configuration()
        assert active is not None
        assert resolution.selected_configuration_id == active.id
        reply = await complete_with_tools(
            messages,
            _expert_tool_specs(),
            prompt_key="chat.mode.interview",
        )
        question = _ask_expert_question(reply)
        assert question
        assert "integration" in question.casefold()
    finally:
        _restore_secrets(previous)
        set_runtime_selection_cache(
            assignments={},
            configurations={},
            default_configuration_id=None,
        )
        set_tools_completer(None)
