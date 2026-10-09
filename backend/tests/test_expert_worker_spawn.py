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
from app.database.models import Kund, StoredObject
from app.llm import set_tools_completer
from app.services.document_navigation import SourceScopeIndex, source_scope_index
from app.services.expert_async_tools import PlannedCall, ToolWork, begin_library_tools
from app.services.expert_reasoning import assess_expert_reasoning
from app.services.expert_reasoning_episode import ExpertEpisode, continue_expert_episode
from app.services.expert_reasoning_turn import route_expert_turn
from app.services.expert_worker_runtime import (
    WorkerIdentity,
    _run_scoped_tool,
    _scope_error,
    run_worker_task,
)
from app.services.expert_worker_schema import instance_matches
from app.services.expert_worker_scope import allowed_scope_ids, confine_search_payload
from app.services.expert_worker_spawn import (
    SPAWN_TOOL_NAME,
    parse_spawn_request,
    run_spawn_workers,
    spawn_workers_spec,
    validate_spawn_request,
)
from app.services.jobs import set_job_session_factory
from app.services.knowledge.extractors import ExtractedBlock, ExtractedDocument
from app.services.knowledge.models import KnowledgeDocument, KnowledgeScope
from app.services.knowledge.persistence import persist_segmented_document
from app.services.knowledge.segmentation import DocumentSegmenter
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
_ALLOWED = {"doc-1": {"1", "2", "11"}}
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
    assert validate_spawn_request(
        parsed, workspace_state=_STATE, allowed_ids=_ALLOWED
    ) is None
    assert (
        validate_spawn_request(
            parsed, workspace_state={"documents": []}, allowed_ids=_ALLOWED
        )
        == "scope_outside_document"
    )
    forbidden = parse_spawn_request(
        _request(tasks=[{**_TASK, "allowed_tools": ["highlight_locations"]}])
    )
    assert not isinstance(forbidden, str)
    assert (
        validate_spawn_request(forbidden, workspace_state=_STATE, allowed_ids=_ALLOWED)
        == "tool_not_on_read_list"
    )
    outside = parse_spawn_request(
        _request(tasks=[{**_TASK, "scope": {"source_id": "other", "ids": ["1"]}}])
    )
    assert not isinstance(outside, str)
    assert (
        validate_spawn_request(outside, workspace_state=_STATE, allowed_ids=_ALLOWED)
        == "scope_outside_document"
    )
    unknown = parse_spawn_request(
        _request(tasks=[{**_TASK, "scope": {"source_id": "doc-1", "ids": ["1", "missing"]}}])
    )
    assert not isinstance(unknown, str)
    assert (
        validate_spawn_request(unknown, workspace_state=_STATE, allowed_ids=_ALLOWED)
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

    async def allow(_episode, source_ids):
        return {source_id: set(_ALLOWED["doc-1"]) for source_id in source_ids}

    monkeypatch.setattr("app.services.expert_worker_spawn.allowed_scope_ids", allow)
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


def test_invalid_json_schema_rejects_the_spawn():
    bad = {**_TASK, "output_schema": {"type": "array", "minItems": -1}}
    assert parse_spawn_request(_request(tasks=[bad])) == "invalid_output_schema"
    remote = {**_TASK, "output_schema": {"$ref": "https://example.test/schema"}}
    assert parse_spawn_request(_request(tasks=[remote])) == "invalid_output_schema"


def test_worker_result_that_breaks_the_schema_is_rejected():
    schema = {
        "type": "array",
        "minItems": 1,
        "maxItems": 2,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["assessment", "confidence"],
            "properties": {
                "assessment": {"type": "string", "enum": ["odd", "normal"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
    }
    assert instance_matches(schema, [{"assessment": "odd", "confidence": 0.4}])
    assert instance_matches(schema, [{"assessment": "odd", "confidence": 1.4}]) is False
    assert instance_matches(
        schema, [{"assessment": "odd", "confidence": 0.4, "extra": True}]
    ) is False
    assert instance_matches(schema, []) is False
    assert instance_matches(schema, [{"assessment": "wild", "confidence": 0.2}]) is False


def test_search_hits_outside_scope_are_dropped():
    payload = json.dumps(
        {
            "status": "completed",
            "items": [
                {"excerpt": "Priset är fast."},
                {"snapshot": {"text_unit_id": "unit-1", "excerpt": "Priset är fast."}},
                {
                    "excerpt": "Vite utgår.",
                    "snapshot": {"section_id": "sec-9", "excerpt": "Vite utgår."},
                },
            ],
        }
    )
    passages = (
        ("unit-1", "sec-1", "Priset är fast."),
        ("unit-9", "sec-9", "Vite utgår."),
    )
    limited = json.loads(confine_search_payload(payload, frozenset({"sec-1"}), passages))
    assert [item.get("excerpt") or item["snapshot"]["text_unit_id"] for item in limited["items"]] == [
        "Priset är fast.",
        "unit-1",
    ]


@pytest.mark.asyncio
async def test_search_knowledge_cannot_read_outside_assigned_scope(monkeypatch):
    payload = json.dumps(
        {
            "status": "completed",
            "text": "Vite utgår i hela avtalet.",
            "items": [
                {
                    "excerpt": "Priset är fast.",
                    "snapshot": {"section_id": "sec-1", "excerpt": "Priset är fast."},
                },
                {
                    "excerpt": "Vite utgår.",
                    "snapshot": {"text_unit_id": "unit-9", "excerpt": "Vite utgår."},
                },
            ],
        }
    )

    async def run_call(_planned, _work):
        return payload

    async def index(_source_id):
        return SourceScopeIndex(
            ids=frozenset({"sec-1", "sec-9", "unit-1", "unit-9"}),
            titles=(("sec-1", "Klausul 1"), ("sec-9", "Klausul 9")),
            passages=(
                ("unit-1", "sec-1", "Priset är fast."),
                ("unit-9", "sec-9", "Vite utgår."),
            ),
        )

    monkeypatch.setattr(
        "app.services.expert_workspace_tool_run.run_workspace_tool_call", run_call
    )
    monkeypatch.setattr("app.services.expert_worker_runtime.load_source_scope", index)
    call = SimpleNamespace(
        id="c1",
        function=SimpleNamespace(
            name="search_knowledge",
            arguments=json.dumps({"query": "villkor", "source_id": "doc-1"}),
        ),
    )
    task = SimpleNamespace(scope=SimpleNamespace(source_id="doc-1", ids=("sec-1",)))
    text = await _run_scoped_tool(
        call,
        task,
        WorkerIdentity("p", "Djup", "w", "u", _STATE),
    )
    assert "Vite" not in text
    assert json.loads(text)["items"][0]["snapshot"]["section_id"] == "sec-1"


def test_read_title_outside_scope_is_rejected():
    scope = SimpleNamespace(source_id="doc-1", ids=("sec-1",))
    titles = {"sec-1": "Klausul 1", "sec-9": "Klausul 9"}
    assert _scope_error(
        "read_source",
        {"source_id": "doc-1", "section": "Klausul 1"},
        scope,
        titles=titles,
    ) is None
    assert (
        _scope_error(
            "read_source",
            {"source_id": "doc-1", "section": "Klausul 9"},
            scope,
            titles=titles,
        )
        == "scope_outside_document"
    )
    assert (
        _scope_error(
            "search_knowledge",
            {"source_id": "doc-1", "query": "pris", "section_ids": ["sec-9"]},
            scope,
        )
        == "scope_outside_document"
    )


@pytest.mark.asyncio
async def test_worker_json_outside_the_schema_fails_that_task(monkeypatch):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["confidence"],
        "properties": {"confidence": {"type": "number", "minimum": 0, "maximum": 1}},
    }

    async def complete(_messages, *, prompt_key=None):
        del prompt_key
        return json.dumps({"confidence": 4})

    monkeypatch.setattr("app.services.expert_worker_runtime.complete_text", complete)
    parsed = parse_spawn_request(
        _request(tasks=[{**_TASK, "allowed_tools": [], "output_schema": schema}])
    )
    assert not isinstance(parsed, str)
    result = await run_worker_task(
        parsed.tasks[0],
        identity=WorkerIdentity("p", "Djup", "w", "u", _STATE),
        worker_profile="fast",
        prompts=default_prompts("sv"),
    )
    assert result == {"ok": False, "error": "schema_mismatch"}


@pytest.mark.asyncio
async def test_scope_ids_must_belong_to_the_document_and_a_tool_result(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/scope.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    set_job_session_factory(factory)
    try:
        async with factory() as session:
            kund = Kund(name="acme", slug="acme-scope", available_modules=["dd"])
            session.add(kund)
            await session.flush()
            session.add(
                StoredObject(
                    id="doc-1",
                    customer_id=kund.id,
                    workspace_id=None,
                    module="dd",
                    kind="underlag",
                    bucket="scope",
                    object_key="agreement.txt",
                    filename="agreement.txt",
                    content_type="text/plain",
                    size_bytes=32,
                )
            )
            await session.flush()
            segmented = DocumentSegmenter().segment(
                ExtractedDocument(
                    blocks=[
                        ExtractedBlock(
                            text="Priset är fast.",
                            locator="page:1",
                            metadata={"heading_level": 1},
                        ),
                        ExtractedBlock(
                            text="Vite utgår.",
                            locator="page:2",
                            metadata={"heading_level": 1},
                        ),
                    ]
                ),
                KnowledgeDocument(
                    document_id="doc-a",
                    provider="supabase",
                    external_id="acme/agreement.txt",
                    title="Agreement",
                    mime_type="text/plain",
                    scope=KnowledgeScope(customer_id=kund.id, module="dd"),
                    source_type="uploaded_file",
                    canonical_uri="acme/agreement.txt",
                ),
                content_hash="hash-scope",
            )
            await persist_segmented_document(
                session,
                customer_id=kund.id,
                source_object_id="doc-1",
                segmented=segmented,
            )
            await session.commit()
            index = await source_scope_index(session, "doc-1")
        cited, omitted = sorted(index.ids)[:2]
        episode = SimpleNamespace(
            messages=(
                {
                    "role": "tool",
                    "name": "read_source",
                    "content": json.dumps({"sections": [{"id": cited}]}),
                },
            )
        )
        allowed = await allowed_scope_ids(episode, ["doc-1"])
        assert cited in allowed["doc-1"]
        assert omitted not in allowed["doc-1"]
        parsed = parse_spawn_request(
            _request(tasks=[{**_TASK, "scope": {"source_id": "doc-1", "ids": [omitted]}}])
        )
        assert not isinstance(parsed, str)
        assert (
            validate_spawn_request(parsed, workspace_state=_STATE, allowed_ids=allowed)
            == "scope_outside_document"
        )
        cited_request = parse_spawn_request(
            _request(tasks=[{**_TASK, "scope": {"source_id": "doc-1", "ids": [cited]}}])
        )
        assert not isinstance(cited_request, str)
        assert (
            validate_spawn_request(
                cited_request, workspace_state=_STATE, allowed_ids=allowed
            )
            is None
        )
    finally:
        set_job_session_factory(None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_partial_spawn_does_not_report_the_task_finished():
    replies = iter(
        (
            SimpleNamespace(content="Jag har gått igenom hela avtalet.", tool_calls=None),
            SimpleNamespace(
                content="Två delar saknas, så avtalet är inte genomgånget.",
                tool_calls=None,
            ),
        )
    )
    seen: list[str] = []

    async def tools(messages, _specs=None):
        seen.append(str(messages[-1]["content"]))
        return next(replies)

    async def unused_call(_call, _work):
        raise AssertionError("spawn result was already recorded")

    async def unused_publish(_calls):
        raise AssertionError("no client call")

    set_tools_completer(tools)
    try:
        text, _reasoning = await continue_expert_episode(
            ToolWork(
                persona_id="e",
                mode="interview",
                actor_user_id=None,
                history=[],
                user_message="Gå igenom avtalet.",
                calls=(PlannedCall("c1", SPAWN_TOOL_NAME, {}),),
                episode=ExpertEpisode(
                    messages=(
                        {"role": "user", "content": "Gå igenom avtalet."},
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": SPAWN_TOOL_NAME,
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        },
                    ),
                    specs=(),
                    prompt_key=None,
                    reasoning_content=None,
                ),
            ),
            (
                json.dumps(
                    [
                        {"ok": True, "result": []},
                        {"ok": False, "error": "timeout"},
                    ]
                ),
            ),
            run_call=unused_call,
            publish=unused_publish,
        )
    finally:
        set_tools_completer(None)
    assert text == "Två delar saknas, så avtalet är inte genomgånget."
    assert json.loads(seen[1])["spawn_complete"] is False
    assert json.loads(seen[1])["worker_failed"] == 1
