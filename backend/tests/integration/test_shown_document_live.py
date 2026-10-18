"""Live check: an expert reads the document on screen after being told it was missing.

Opt-in. Default pytest skips it, including CI.

    RUN_SHOWN_DOCUMENT_INTEGRATION=1 uv run pytest \
      tests/integration/test_shown_document_live.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database.models import Persona
from app.database_url import normalize_database_url
from app.llm import complete_with_tools, reset_client
from app.llm.chat import _chat_messages
from app.schemas.workspace import WorkspaceDocumentTab, WorkspaceState
from app.serializers import profile_from_dict
from app.services.document_tool_retrieval import expose_workspace_tools
from app.services.prompt_store import require_prompts_for_persona
from app.services.sme_open_document import format_workspace_documents
from app.services.workspace_chat_tools import workspace_openai_tools, workspace_turn_text

pytestmark = pytest.mark.integration

_ENV_FLAG = "RUN_SHOWN_DOCUMENT_INTEGRATION"
_EXPERT_ID = "exp_1_finansiell_analytiker"
_MARKER = "BRUN-LISTA-19"
_USER = "Då testar vi att titta på det igen. Läs upp kontrollkoden i dokumentet som visas."
_THANKS = "Tack, det där har jag redan fått höra."
_REVIEW = f"Kontrollkoden i förhandlingspunkterna är {_MARKER}. Den är komplett."
_DENIAL = (
    "Nej, jag ser den fortfarande inte. Det som ligger i vyn är Avtal 22 — "
    "förhandlingspunktsdokumentet finns inte bland filerna hos mig."
)
_PLACEHOLDERS = frozenset({"", "test-key-not-real", "test-openai-key-not-real"})
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


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


def _live_database_url(env_file: dict[str, str]) -> str:
    raw = env_file.get("DATABASE_URL", "")
    if not raw or raw.startswith("sqlite"):
        pytest.skip("backend/.env DATABASE_URL must point at the running Postgres")
    return normalize_database_url(raw)


_LIVE_SETTINGS = (
    ("CEREBRAS_API_KEY", "cerebras_api_key"),
    ("CEREBRAS_BASE_URL", "cerebras_base_url"),
    ("LLM_PROVIDER", "llm_provider"),
    ("LLM_REASONING_EFFORT", "llm_reasoning_effort"),
    ("LLM_MAX_TOKENS", "llm_max_tokens"),
    ("LLM_TIMEOUT_SECONDS", "llm_timeout_seconds"),
    ("TYPESAFE_API_KEY", "typesafe_api_key"),
    ("TYPESAFE_BASE_URL", "typesafe_base_url"),
    ("JEV_MODEL", "jev_model"),
    ("JEV_TIMEOUT_SECONDS", "jev_timeout_seconds"),
    ("JEV_CONFIDENCE_THRESHOLD", "jev_confidence_threshold"),
)


def _apply_live_settings(env_file: dict[str, str]) -> None:
    for env_name, field in _LIVE_SETTINGS:
        raw = env_file.get(env_name, "").strip()
        if not raw or _placeholder(raw):
            continue
        current = getattr(settings, field)
        value: object = raw
        if isinstance(current, int) and not isinstance(current, bool):
            value = int(raw)
        elif isinstance(current, float):
            value = float(raw)
        setattr(settings, field, value)
    if _placeholder(settings.cerebras_api_key):
        pytest.skip("CEREBRAS_API_KEY must be a real key in backend/.env")
    if not settings.typesafe_api_key.strip():
        pytest.skip("TYPESAFE_API_KEY must be set in backend/.env")
    reset_client()


def _plain(value: str) -> str:
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014"):
        value = value.replace(dash, "-")
    return value.casefold()


def _documents() -> dict:
    return {
        "created_documents": [{
            "title": "Förhandlingspunkter",
            "artifact_id": "draft-live",
            "shown": True,
            "text": f"Kontrollkoden i förhandlingspunkterna är {_MARKER}.",
        }],
        "open_documents": [{
            "filename": "Avtal_22_Kontorshotell.pdf",
            "source_id": "src-22",
            "knowledge_status": "ready",
            "text": "Detta är Avtal 22. Månadsavgiften är 8 600 kr.",
        }],
    }


async def _expert_and_prompts(database_url: str):
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            persona = await session.get(Persona, _EXPERT_ID)
            if persona is None:
                pytest.skip(f"persona {_EXPERT_ID} is not in the database")
            profile = profile_from_dict(persona.profile, persona.name)
            prompts = await require_prompts_for_persona(session, persona)
            kind = persona.kind
            await session.rollback()
            async with factory() as other:
                assert await other.scalar(text("SELECT 1")) == 1
        return profile, prompts, kind
    finally:
        await engine.dispose()


async def _shown_turn(message: str, history: list[tuple[str, str]]):
    if not _opted_in():
        pytest.skip(f"set {_ENV_FLAG}=1 to call the live model")
    env_file = _dotenv_values()
    _apply_live_settings(env_file)
    profile, prompts, kind = await _expert_and_prompts(_live_database_url(env_file))
    state = WorkspaceState(
        view="documents",
        active_artifact_id="draft-live",
        documents=[WorkspaceDocumentTab(source_id="src-22")],
    )
    extra = f"{workspace_turn_text(prompts, state)}\n\n{format_workspace_documents(_documents())}"
    exposed, retrieval = await expose_workspace_tools(
        prompts=prompts,
        specs=workspace_openai_tools(prompts),
        message=message,
        workspace_state=state,
    )
    assert retrieval.fallback is False, retrieval.error_category
    messages = _chat_messages(
        profile,
        "character",
        history,
        message,
        prompts=prompts,
        extra_system=extra,
        profile_kind=kind,
    )
    sent = messages[-1]["content"]
    assert _MARKER not in sent
    assert "8 600 kr" not in sent
    assert sent.endswith(message)
    reply = await complete_with_tools(
        messages,
        exposed,
        prompt_key="chat.mode.in_character",
    )
    return (reply.content or "").strip(), [call.function.name for call in (reply.tool_calls or [])]


@pytest.mark.asyncio
async def test_the_expert_reads_the_document_on_screen_after_a_denial():
    text_reply, names = await _shown_turn(
        _USER,
        [
            ("user", "Kolla om du ser förhandlingspunkterna."),
            ("assistant", _DENIAL),
            ("user", "Kolla nu då."),
            ("assistant", _DENIAL),
        ],
    )
    lowered = _plain(text_reply)
    assert "read_source" in names, text_reply
    assert "ser den inte" not in lowered, text_reply
    assert "finns inte bland" not in lowered, text_reply
    assert "show_document" not in names
    assert "show_artifact" not in names


@pytest.mark.asyncio
async def test_the_expert_does_not_repeat_the_review_when_already_heard():
    text_reply, _names = await _shown_turn(
        _THANKS,
        [
            ("user", _USER),
            ("assistant", _REVIEW),
            ("user", _THANKS),
            ("assistant", _REVIEW),
        ],
    )
    lowered = _plain(text_reply)
    assert _plain(_MARKER) not in lowered, text_reply
    assert "punkt för punkt" not in lowered, text_reply
