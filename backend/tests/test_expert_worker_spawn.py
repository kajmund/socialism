"""Spawn workers: gate, invalid calls, partial failure, and released connections."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.services.expert_async_tools import begin_library_tools
from app.services.expert_reasoning import assess_expert_reasoning
from app.services.expert_reasoning_turn import route_expert_turn
from app.services.expert_worker_runtime import (
    WorkerIdentity,
    _scope_error,
    run_worker_task,
)
from app.services.expert_worker_schema import instance_matches
from app.services.expert_worker_spawn import (
    SPAWN_TOOL_NAME,
    parse_spawn_request,
    run_spawn_workers,
    spawn_workers_spec,
    validate_spawn_request,
)
from app.services.jobs import set_job_session_factory
from app.services.prompt_catalog import default_prompts
from tests.test_expert_reasoning import _FakeJev


_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["anchor_id", "assessment", "reason", "confidence"],
        "properties": {
            "anchor_id": {"type": "string"},
            "assessment": {"type": "string"},
            "reason": {"type": "string"},
            "confidence": {"type": "number"},
        },
    },
}
_STATE = {
    "language": "sv",
    "documents": [{"source_id": "doc-1", "page": 1}],
    "document_mentions": [],
}
_TASK = {
    "task": "Granska klausuler 1-10",
    "scope": {"source_id": "doc-1", "ids": ["1", "2"]},
    "context": "Avvikande kommersiella villkor",
    "allowed_tools": ["read_source"],
    "output_schema": _SCHEMA,
}


def _request(**overrides):
    body = {"worker_profile": "fast", "tasks": [_TASK], **overrides}
    return body


def test_spawn_spec_import_does_not_cycle():
    script = "from app.services.expert_worker_spawn import spawn_workers_spec; assert spawn_workers_spec({}) is None"
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_missing_spawn_prompt_does_not_build_a_spec():
    assert spawn_workers_spec({}) is None


def test_schema_accepts_worker_rows():
    assert instance_matches(
        _SCHEMA,
        [{"anchor_id": "1", "assessment": "odd", "reason": "x", "confidence": 0.8}],
    )
    assert instance_matches(_SCHEMA, {"anchor_id": "1"}) is False


def test_invalid_spawn_calls_fail_the_whole_request():
    assert parse_spawn_request({"worker_profile": "deep", "tasks": [_TASK]}) == (
        "unknown_worker_profile"
    )
    assert parse_spawn_request({"worker_profile": "fast", "tasks": []}) == "empty_tasks"
    parsed = parse_spawn_request(_request())
    assert not isinstance(parsed, str)
    assert validate_spawn_request(parsed, workspace_state=_STATE) is None
    assert (
        validate_spawn_request(parsed, workspace_state={"documents": []})
        == "scope_outside_document"
    )
    forbidden = parse_spawn_request(
        _request(tasks=[{**_TASK, "allowed_tools": ["highlight_locations"]}])
    )
    assert not isinstance(forbidden, str)
    assert (
        validate_spawn_request(forbidden, workspace_state=_STATE)
        == "tool_not_on_read_list"
    )
    outside = parse_spawn_request(
        _request(tasks=[{**_TASK, "scope": {"source_id": "other", "ids": ["1"]}}])
    )
    assert not isinstance(outside, str)
    assert (
        validate_spawn_request(outside, workspace_state=_STATE)
        == "scope_outside_document"
    )


def test_worker_read_must_stay_inside_scope():
    scope = SimpleNamespace(source_id="doc-1", ids=("1", "2"))
    assert _scope_error("read_source", {"source_id": "doc-1", "section": "1"}, scope) is None
    assert (
        _scope_error("read_source", {"source_id": "doc-1", "section": "99"}, scope)
        == "scope_outside_document"
    )
    assert (
        _scope_error("read_source", {"source_id": "other", "section": "1"}, scope)
        == "scope_outside_document"
    )
    assert _scope_error("highlight_locations", {}, scope) == "tool_not_on_read_list"


@pytest.mark.asyncio
async def test_run_spawn_rejects_invalid_batch_before_workers():
    text = await run_spawn_workers(
        SimpleNamespace(arguments={"worker_profile": "fast", "tasks": []}),
        SimpleNamespace(
            persona_id="p1",
            workspace_id="w1",
            actor_user_id="u1",
            workspace_state=_STATE,
        ),
    )
    assert json.loads(text) == {"ok": False, "error": "empty_tasks"}


@pytest.mark.asyncio
async def test_partial_worker_failure_keeps_other_results(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/spawn.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    set_job_session_factory(factory)
    seen: list[str] = []

    async def complete(messages, *, prompt_key=None):
        del prompt_key
        text = str(messages[0]["content"])
        seen.append(text)
        if "andra" in text:
            raise RuntimeError("boom")
        return json.dumps(
            [{"anchor_id": "1", "assessment": "odd", "reason": "x", "confidence": 0.7}]
        )

    monkeypatch.setattr("app.services.expert_worker_runtime.complete_text", complete)
    second = {
        **_TASK,
        "task": "Granska andra delen",
        "allowed_tools": [],
        "scope": {"source_id": "doc-1", "ids": ["11"]},
    }
    first = {**_TASK, "allowed_tools": []}
    try:
        text = await run_spawn_workers(
            SimpleNamespace(
                arguments={"worker_profile": "balanced", "tasks": [first, second]}
            ),
            SimpleNamespace(
                persona_id="missing",
                workspace_id="w1",
                actor_user_id="u1",
                workspace_state=_STATE,
            ),
        )
        rows = json.loads(text)
        assert rows[0]["ok"] is True
        assert rows[1] == {"ok": False, "error": "worker_failed"}
        assert len(seen) == 2
    finally:
        set_job_session_factory(None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_worker_llm_does_not_hold_database_connection(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/worker-pool.db",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def complete(messages, *, prompt_key=None):
        del messages, prompt_key
        async with factory() as other:
            assert await asyncio.wait_for(other.scalar(text("SELECT 1")), timeout=1) == 1
        return json.dumps(
            [{"anchor_id": "1", "assessment": "odd", "reason": "x", "confidence": 0.9}]
        )

    monkeypatch.setattr("app.services.expert_worker_runtime.complete_text", complete)
    task = parse_spawn_request(_request(tasks=[{**_TASK, "allowed_tools": []}]))
    assert not isinstance(task, str)
    identity = WorkerIdentity(
        persona_id="p1",
        name="Djup",
        workspace_id="w1",
        actor_user_id="u1",
        workspace_state=_STATE,
    )
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
            await session.commit()
            result = await run_worker_task(
                task.tasks[0],
                identity=identity,
                worker_profile="fast",
                prompts=default_prompts("sv"),
            )
        assert result["ok"] is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_route_exposes_spawn_only_on_deep_split_tasks(monkeypatch):
    answers = {
        key: {"noul": value}
        for key, value in {
            "simple_operation": 0.03,
            "analysis": 0.91,
            "multi_step": 0.94,
            "comparison": 0.41,
            "synthesis": 0.72,
            "conflicting_information": 0.11,
            "decomposable": 0.97,
            "parallelizable": 0.95,
        }.items()
    }
    monkeypatch.setattr(
        "app.services.expert_reasoning_turn.assess_expert_reasoning",
        lambda **kwargs: assess_expert_reasoning(**kwargs, jev=_FakeJev(answers)),
    )
    monkeypatch.setattr(
        "app.config.settings.document_tool_retrieval_enabled", False
    )
    scope = begin_library_tools(
        persona_id="p1",
        mode="interview",
        actor_user_id="u1",
        history=[],
        user_message="Gå igenom avtalet och markera märkliga klausuler.",
        enabled=True,
        workspace=("ws-1", _STATE),
    )
    specs: list[dict] = []
    profile = await route_expert_turn(
        scope, default_prompts("sv"), "expert", ([], specs)
    )
    assert profile == "deep"
    assert scope.spawn_exposed is True
    assert specs[-1]["function"]["name"] == SPAWN_TOOL_NAME


@pytest.mark.asyncio
async def test_route_keeps_deep_comparison_without_spawn(monkeypatch):
    answers = {
        key: {"noul": value}
        for key, value in {
            "simple_operation": 0.06,
            "analysis": 0.91,
            "multi_step": 0.71,
            "comparison": 0.96,
            "synthesis": 0.44,
            "conflicting_information": 0.08,
            "decomposable": 0.32,
            "parallelizable": 0.18,
        }.items()
    }
    monkeypatch.setattr(
        "app.services.expert_reasoning_turn.assess_expert_reasoning",
        lambda **kwargs: assess_expert_reasoning(**kwargs, jev=_FakeJev(answers)),
    )
    monkeypatch.setattr(
        "app.config.settings.document_tool_retrieval_enabled", False
    )
    scope = begin_library_tools(
        persona_id="p1",
        mode="interview",
        actor_user_id="u1",
        history=[],
        user_message="Jämför klausul 3 med klausul 7.",
        enabled=True,
        workspace=("ws-1", _STATE),
    )
    specs: list[dict] = []
    profile = await route_expert_turn(
        scope, default_prompts("sv"), "expert", ([], specs)
    )
    assert profile == "deep"
    assert scope.spawn_exposed is False
    assert specs == []


@pytest.mark.asyncio
async def test_missing_spawn_prompt_keeps_the_turn_without_the_tool(monkeypatch):
    answers = {
        key: {"noul": value}
        for key, value in {
            "simple_operation": 0.03,
            "analysis": 0.91,
            "multi_step": 0.94,
            "comparison": 0.41,
            "synthesis": 0.72,
            "conflicting_information": 0.11,
            "decomposable": 0.97,
            "parallelizable": 0.95,
        }.items()
    }
    monkeypatch.setattr(
        "app.services.expert_reasoning_turn.assess_expert_reasoning",
        lambda **kwargs: assess_expert_reasoning(**kwargs, jev=_FakeJev(answers)),
    )
    monkeypatch.setattr("app.config.settings.document_tool_retrieval_enabled", False)
    scope = begin_library_tools(
        persona_id="p1",
        mode="interview",
        actor_user_id="u1",
        history=[],
        user_message="Gå igenom avtalet.",
        enabled=True,
        workspace=("ws-1", _STATE),
    )
    prompts = {
        key: value
        for key, value in default_prompts("sv").items()
        if key != "chat.expert.spawn_workers"
    }
    specs: list[dict] = []
    profile = await route_expert_turn(scope, prompts, "expert", ([], specs))
    assert profile == "deep"
    assert scope.spawn_exposed is False
    assert specs == []


@pytest.mark.asyncio
async def test_route_failure_keeps_the_turn(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("jev down")

    monkeypatch.setattr(
        "app.services.expert_reasoning_turn.assess_expert_reasoning", boom
    )
    monkeypatch.setattr("app.config.settings.document_tool_retrieval_enabled", False)
    scope = begin_library_tools(
        persona_id="p1",
        mode="interview",
        actor_user_id="u1",
        history=[],
        user_message="Gå igenom avtalet.",
        enabled=True,
        workspace=("ws-1", _STATE),
    )
    profile = await route_expert_turn(scope, default_prompts("sv"), "expert", ([], []))
    assert profile is None


@pytest.mark.asyncio
async def test_too_many_tasks_is_a_failed_call(monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.expert_reasoning_spawn_max_tasks", 1
    )
    parsed = parse_spawn_request(_request(tasks=[_TASK, {**_TASK, "task": "två"}]))
    assert parsed == "too_many_tasks"
