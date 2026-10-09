"""Live check: an empty interview still gets a spoken opening greeting.

Opt-in. Default pytest skips it, including CI.

    RUN_LIVE_SPEECH_OPENING_INTEGRATION=1 uv run pytest \
      tests/integration/test_live_speech_opening_live.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database.models import Persona
from app.database_url import normalize_database_url
from app.llm import complete_structured, reset_client, set_structured_completer
from app.llm.runtime_override import set_runtime_selection_cache
from app.services.expert_reasoning import bound_expert_profile
from app.services.live_speech_admit import recent_interview_turns
from app.services.live_speech_phrases import OPENING_PROMPT_KEY, SpeechPhrase
from app.services.llm_runtime_settings import refresh_prompt_runtime_cache
from app.services.prompt_store import filled_prompts, module_for_persona_kind

pytestmark = pytest.mark.integration

_ENV_FLAG = "RUN_LIVE_SPEECH_OPENING_INTEGRATION"
_EXPERT_ID = "exp_1_integrationsriskbed_mare"
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


def _apply_cerebras_key(env_file: dict[str, str]) -> str:
    previous = settings.cerebras_api_key
    candidate = os.environ.get("CEREBRAS_API_KEY", "").strip()
    if _placeholder(candidate):
        candidate = env_file.get("CEREBRAS_API_KEY", "")
    if _placeholder(candidate):
        pytest.skip("CEREBRAS_API_KEY must be a real key in the environment or backend/.env")
    settings.cerebras_api_key = candidate
    reset_client()
    return previous


def _opening_user(turns: tuple[tuple[str, str], ...]) -> str:
    if not turns:
        return "No previous turns."
    lines = "\n".join(f"{role}: {content}" for role, content in turns)
    return f"Latest conversation:\n{lines}"


async def _empty_interview(
    database_url: str,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    engine = create_async_engine(normalize_database_url(database_url))
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            persona = await session.get(Persona, _EXPERT_ID)
            if persona is None:
                pytest.skip(f"live database has no expert {_EXPERT_ID}")
            await refresh_prompt_runtime_cache(session)
            prompts = await filled_prompts(
                session,
                customer_id=persona.customer_id,
                language="sv",
                module=module_for_persona_kind("expert"),
            )
            turns = await recent_interview_turns(session, persona.id)
            await session.rollback()
    finally:
        await engine.dispose()
    prompt = prompts.get(OPENING_PROMPT_KEY, "").strip()
    if not prompt:
        pytest.skip(f"live prompts have no {OPENING_PROMPT_KEY}")
    return prompt, turns


async def test_empty_interview_opening_is_a_greeting() -> None:
    if not _opted_in():
        pytest.skip(f"set {_ENV_FLAG}=1 to ask Snabb for an opening with no interview")
    env_file = _dotenv_values()
    database_url = env_file.get("DATABASE_URL", "").strip()
    if not database_url or database_url.startswith("sqlite"):
        pytest.skip("backend/.env DATABASE_URL must point at the live Postgres database")
    previous = _apply_cerebras_key(env_file)
    set_structured_completer(None)
    try:
        prompt, live_turns = await _empty_interview(database_url)
        # Text i intervjun ska inte styra det här fallet. Tom historik är
        # "No previous turns."; rader utan text är den sammanfattning som
        # öppningen faktiskt får.
        has_text = any(content.strip() for _, content in live_turns)
        turns = () if has_text else live_turns
        with bound_expert_profile("fast"):
            result = await complete_structured(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": _opening_user(turns)},
                ],
                SpeechPhrase,
                prompt_key=OPENING_PROMPT_KEY,
                max_tokens=120,
                timeout=settings.live_speech_phrase_timeout_seconds,
            )
    finally:
        settings.cerebras_api_key = previous
        reset_client()
        set_runtime_selection_cache(
            assignments={},
            configurations={},
            default_configuration_id=None,
        )
        set_structured_completer(None)
    assert result.silence is False, (
        "Snabb valde tystnad för tom intervju. "
        f"live_has_text={has_text} turns={turns!r} result={result!r}"
    )
    phrase = result.phrase.strip()
    assert phrase, (
        "Snabb gav ingen hälsningsfras. "
        f"live_has_text={has_text} turns={turns!r} result={result!r}"
    )
    assert len(phrase.split()) <= 32
