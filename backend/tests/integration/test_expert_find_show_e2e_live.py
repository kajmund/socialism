"""Live latency probe from expert request to show_document_set handoff.

Opt-in because it calls both Jev and the configured expert model:

    RUN_EXPERT_FIND_SHOW_E2E=1 uv run pytest -s \
      tests/integration/test_expert_find_show_e2e_live.py
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database.base import Base
from app.database.models import CanonicalDocumentRecord, Kund, StoredObject, UserAccount
from app.llm import complete_with_tools, reset_client
from app.llm.chat import _chat_messages
from app.llm.tool_messages import assistant_message_dict
from app.schemas.domain import EditablePersona
from app.schemas.workspace import WorkspaceState
from app.services.document_find.fixture import add_document, vector
from app.services.document_qa.tenants import TenantCatalogs, set_tenant_catalogs
from app.services.document_tool_retrieval import expose_workspace_tools
from app.services.prompt_catalog import default_prompts
from app.services.workspace import tool_handlers as handlers
from app.services.workspace.tool_handlers import ToolContext, find_documents
from app.services.workspace_chat_tools import workspace_openai_tools, workspace_turn_text
from app.services.workspace_task_context import workspace_task_context
from app.services.workspaces import ensure_company_workspace

pytestmark = pytest.mark.integration

_ENV_FLAG = "RUN_EXPERT_FIND_SHOW_E2E"
_MESSAGE = "Visa alla hyresavtal."
_DIMENSION = 8
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
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
)


def _opted_in() -> bool:
    return os.environ.get(_ENV_FLAG) == "1"


def _apply_live_settings() -> None:
    values = {}
    for line in (_BACKEND_ROOT / ".env").read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, raw = stripped.split("=", 1)
            values[key.strip()] = raw.strip().strip("\"'")
    for env_name, field in _LIVE_SETTINGS:
        raw = values.get(env_name, "")
        if not raw:
            continue
        current = getattr(settings, field)
        value: object = raw
        if isinstance(current, int) and not isinstance(current, bool):
            value = int(raw)
        elif isinstance(current, float):
            value = float(raw)
        setattr(settings, field, value)
    reset_client()


async def _seed(session, catalog) -> str:
    session.add(Kund(id=1, name="C1", slug="c1", available_modules=[]))
    session.add(UserAccount(id="user-1", email="user-1@test.local", role="user", kund_id=1))
    await session.flush()
    common = await ensure_company_workspace(session, customer_id=1)
    for index in range(5):
        document_id = f"lease-{index}"
        await add_document(
            catalog,
            document_id=document_id,
            title=f"Hyresavtal {index}",
            opening="Hyresavtal för lokal.",
            passages=[("Hyresavtal text.", vector(0.1, 0.9))],
        )
        session.add(StoredObject(
            id=f"src-{document_id}",
            customer_id=1,
            workspace_id=common.id,
            module="dd",
            kind="document",
            bucket="c1",
            object_key=f"src-{document_id}",
            filename=f"{document_id}.pdf",
            content_type="application/pdf",
            size_bytes=1,
        ))
        session.add(CanonicalDocumentRecord(
            id=document_id,
            scope_type="customer",
            scope_key="customer:1",
            customer_id=1,
            source_object_id=f"src-{document_id}",
            source_type="upload",
            canonical_uri=f"doc://{document_id}",
            title=f"Hyresavtal {index}",
            extra={},
        ))
    await session.commit()
    return common.id


def _assistant_tool_message(reply) -> dict:
    payload = assistant_message_dict(reply)
    return {
        "role": "assistant",
        "content": payload.get("content"),
        "tool_calls": payload["tool_calls"],
    }


def _assert_find_result(result: dict) -> None:
    assert result["strategy"] == "category"
    assert result["completeness"] == "complete"
    assert result["counters"]["embedding_calls"] == 0
    assert result["counters"]["jev_calls"] == 0


def _assert_handoff(second, result: dict, reroute) -> None:
    assert [call.function.name for call in second.tool_calls or []] == [
        "show_document_set"
    ]
    show_arguments = json.loads(second.tool_calls[0].function.arguments)
    assert show_arguments["source_ids"] == result["presentation_source_ids"]
    _assert_find_result(result)
    assert reroute.reroute is True


def _payload(result: dict, timings: dict[str, float]) -> dict:
    return {
        "chain": "expert_find_documents_jev_show_document_set",
        "documents": result["document_count"],
        "strategy": result["strategy"],
        "timings_ms": {key: round(value, 3) for key, value in timings.items()},
        "calls": {"llm": 2, "jev": 2, "embedding": 0},
        "measurement_boundary": "show_document_set tool call produced",
        "frontend_render_included": False,
    }


@pytest.mark.asyncio
async def test_expert_find_show_handoff_latency(tmp_path, monkeypatch):
    if not _opted_in():
        pytest.skip(f"set {_ENV_FLAG}=1 to call Jev and the live expert model")
    _apply_live_settings()

    registry = TenantCatalogs(tmp_path / "tenants", dimension=_DIMENSION)
    set_tenant_catalogs(registry)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/chain.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as seed_session:
        common_id = await _seed(seed_session, registry.open_for(1))
    prompts = default_prompts("sv")
    state = WorkspaceState()
    catalog_specs = workspace_openai_tools(prompts)
    timings: dict[str, float] = {}
    started = time.perf_counter()
    try:
        initial_started = time.perf_counter()
        exposed, initial_route = await expose_workspace_tools(
            prompts=prompts,
            specs=catalog_specs,
            message=_MESSAGE,
            workspace_state=state,
        )
        timings["initial_jev_ms"] = (time.perf_counter() - initial_started) * 1000
        relevant = (
            name
            for name in initial_route.ranking
            if initial_route.scores[name] >= settings.document_tool_relevance_floor
        )
        extra_system = "\n\n".join((
            workspace_turn_text(prompts, state),
            workspace_task_context(prompts, relevant),
        ))
        messages = _chat_messages(
            EditablePersona(name="Anna", kompetensomrade="Avtalsjuridik"),
            "character",
            [],
            _MESSAGE,
            prompts=prompts,
            extra_system=extra_system,
            profile_kind="expert",
        )

        first_started = time.perf_counter()
        first = await complete_with_tools(
            messages,
            exposed,
            prompt_key="chat.mode.in_character",
        )
        timings["first_llm_ms"] = (time.perf_counter() - first_started) * 1000
        assert [call.function.name for call in first.tool_calls or []] == [
            "find_documents"
        ]

        async with factory() as session:
            async def fake_require(_session, workspace_id, _user):
                return SimpleNamespace(
                    id=workspace_id,
                    customer_id=1,
                    owner_user_id="user-1",
                )

            monkeypatch.setattr(handlers, "require_workspace", fake_require)
            find_started = time.perf_counter()
            result = await find_documents(
                ToolContext(
                    session=session,
                    workspace=SimpleNamespace(
                        id="ws-1",
                        workspace_id=common_id,
                        customer_id=1,
                        owner_user_id="user-1",
                    ),
                    user=SimpleNamespace(id="user-1"),
                    operation=SimpleNamespace(external_started=False),
                    state=state,
                    language="sv",
                ),
                json.loads(first.tool_calls[0].function.arguments),
            )
            timings["find_documents_ms"] = (
                time.perf_counter() - find_started
            ) * 1000

        result_json = json.dumps(result, ensure_ascii=False)
        reroute_started = time.perf_counter()
        rerouted, reroute = await expose_workspace_tools(
            prompts=prompts,
            specs=catalog_specs,
            message=_MESSAGE,
            workspace_state=state,
            tool_result=result_json,
            reroute=True,
        )
        timings["post_result_jev_ms"] = (
            time.perf_counter() - reroute_started
        ) * 1000
        messages.extend((
            _assistant_tool_message(first),
            {
                "role": "tool",
                "tool_call_id": first.tool_calls[0].id,
                "name": "find_documents",
                "content": result_json,
            },
        ))
        second_started = time.perf_counter()
        second = await complete_with_tools(
            messages,
            rerouted,
            prompt_key="chat.mode.in_character",
            tool_choice="required" if reroute.require_tool else "auto",
        )
        timings["second_llm_ms"] = (time.perf_counter() - second_started) * 1000
        timings["handoff_total_ms"] = (time.perf_counter() - started) * 1000

        _assert_handoff(second, result, reroute)

        print(json.dumps(_payload(result, timings), ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()
        registry.close()
        set_tenant_catalogs(None)
