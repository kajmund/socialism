"""Validate and run spawn_workers as one parallel batch."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from app.config import settings
from app.observability.events import log_event
from app.services.expert_worker_runtime import WorkerIdentity, run_worker_task
from app.services.expert_worker_schema import schema_error
from app.services.expert_worker_scope import allowed_scope_ids
from app.services.prompt_catalog import default_prompts, render_prompt
from app.services.research.concurrency import map_with_limit

SPAWN_TOOL_NAME = "spawn_workers"
SPAWN_PROMPT_KEY = "chat.expert.spawn_workers"
EVENT_DATASET_EXPERT_CHAT = "socialism.expert_chat"
READ_TOOLS = frozenset({"read_source", "search_knowledge"})
WORKER_PROFILES = frozenset({"fast", "balanced"})
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerScope:
    source_id: str
    ids: tuple[str, ...]


@dataclass(frozen=True)
class WorkerTask:
    task: str
    scope: WorkerScope
    context: str
    allowed_tools: tuple[str, ...]
    output_schema: dict[str, Any]


@dataclass(frozen=True)
class SpawnRequest:
    worker_profile: Literal["fast", "balanced"]
    tasks: tuple[WorkerTask, ...]


def spawn_workers_spec(prompts: dict[str, str]) -> dict[str, Any] | None:
    if not (prompts.get(SPAWN_PROMPT_KEY) or "").strip():
        return None
    return {
        "type": "function",
        "function": {
            "name": SPAWN_TOOL_NAME,
            "description": render_prompt(prompts, SPAWN_PROMPT_KEY),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["worker_profile", "tasks"],
                "properties": {
                    "worker_profile": {"type": "string", "enum": ["fast", "balanced"]},
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "task",
                                "scope",
                                "context",
                                "allowed_tools",
                                "output_schema",
                            ],
                            "properties": {
                                "task": {"type": "string"},
                                "scope": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["source_id", "ids"],
                                    "properties": {
                                        "source_id": {"type": "string"},
                                        "ids": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                },
                                "context": {"type": "string"},
                                "allowed_tools": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "output_schema": {"type": "object"},
                            },
                        },
                    },
                },
            },
        },
    }


def resolved_source_ids(workspace_state: dict[str, Any] | None) -> set[str]:
    if not workspace_state:
        return set()
    documents = workspace_state.get("documents") or []
    mentions = workspace_state.get("document_mentions") or []
    ids = {
        str(row.get("source_id"))
        for row in documents
        if isinstance(row, dict) and row.get("source_id")
    }
    ids.update(
        str(row.get("source_object_id"))
        for row in mentions
        if isinstance(row, dict) and row.get("source_object_id")
    )
    return ids


def parse_spawn_request(arguments: dict[str, Any]) -> SpawnRequest | str:
    profile = arguments.get("worker_profile")
    if profile not in WORKER_PROFILES:
        return "unknown_worker_profile"
    raw_tasks = arguments.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return "empty_tasks"
    if len(raw_tasks) > settings.expert_reasoning_spawn_max_tasks:
        return "too_many_tasks"
    tasks: list[WorkerTask] = []
    for raw in raw_tasks:
        parsed = _parse_task(raw)
        if isinstance(parsed, str):
            return parsed
        tasks.append(parsed)
    return SpawnRequest(worker_profile=profile, tasks=tuple(tasks))


def validate_spawn_request(
    request: SpawnRequest,
    *,
    workspace_state: dict[str, Any] | None,
    allowed_ids: Mapping[str, set[str]],
) -> str | None:
    known = resolved_source_ids(workspace_state)
    if not known:
        return "scope_outside_document"
    for task in request.tasks:
        if task.scope.source_id not in known:
            return "scope_outside_document"
        permitted = allowed_ids.get(task.scope.source_id, set())
        if any(item not in permitted for item in task.scope.ids):
            return "scope_outside_document"
        forbidden = set(task.allowed_tools) - READ_TOOLS
        if forbidden:
            return "tool_not_on_read_list"
    return None


async def run_spawn_workers(call: object, work: object) -> str:
    started = time.perf_counter()
    parsed = parse_spawn_request(getattr(call, "arguments", {}))
    if isinstance(parsed, str):
        return _failed_call(parsed)
    invalid = validate_spawn_request(
        parsed,
        workspace_state=getattr(work, "workspace_state", None),
        allowed_ids=await allowed_scope_ids(
            getattr(work, "episode", None),
            [task.scope.source_id for task in parsed.tasks],
        ),
    )
    if invalid:
        return _failed_call(invalid)
    identity, prompts = await _load_identity(
        WorkerIdentity(
            persona_id=str(getattr(work, "persona_id", "")),
            name="",
            workspace_id=getattr(work, "workspace_id", None),
            actor_user_id=getattr(work, "actor_user_id", None),
            workspace_state=getattr(work, "workspace_state", None),
        )
    )
    slots = asyncio.Semaphore(settings.expert_reasoning_spawn_concurrency)
    results = await map_with_limit(
        slots,
        parsed.tasks,
        lambda task: run_worker_task(
            task,
            identity=identity,
            worker_profile=parsed.worker_profile,
            prompts=prompts,
        ),
    )
    failed = sum(1 for row in results if not row.get("ok"))
    _log_spawn(
        parsed,
        latency_ms=(time.perf_counter() - started) * 1000,
        failed=failed,
    )
    return json.dumps(results, ensure_ascii=False)


def _parse_task(raw: object) -> WorkerTask | str:
    if not isinstance(raw, dict):
        return "missing_fields"
    task = raw.get("task")
    context = raw.get("context")
    tools = raw.get("allowed_tools")
    schema = raw.get("output_schema")
    scope = _parse_scope(raw.get("scope"))
    missing = (
        not isinstance(task, str)
        or not task.strip()
        or not isinstance(context, str)
        or not isinstance(tools, list)
        or any(not isinstance(name, str) for name in tools)
    )
    if missing:
        return "missing_fields"
    if schema_error(schema) is not None or not isinstance(schema, dict):
        return "invalid_output_schema"
    if isinstance(scope, str):
        return scope
    return WorkerTask(
        task=task.strip(),
        scope=scope,
        context=context,
        allowed_tools=tuple(tools),
        output_schema=schema,
    )


def _parse_scope(raw: object) -> WorkerScope | str:
    if not isinstance(raw, dict):
        return "missing_fields"
    source_id = raw.get("source_id")
    ids = raw.get("ids")
    if not isinstance(source_id, str) or not source_id.strip():
        return "missing_fields"
    if not isinstance(ids, list) or not ids or any(not isinstance(item, str) or not item for item in ids):
        return "missing_fields"
    return WorkerScope(source_id=source_id, ids=tuple(ids))


async def _load_identity(
    identity: WorkerIdentity,
) -> tuple[WorkerIdentity, dict[str, str]]:
    # jobs → research is cyclic if imported while app.llm is still loading.
    from app.database.models import Persona
    from app.services.jobs import job_session_factory
    from app.services.prompt_store import require_prompts_for_persona

    factory = job_session_factory()
    async with factory() as session:
        persona = await session.get(Persona, identity.persona_id)
        name = identity.persona_id if persona is None else persona.name
        language = (identity.workspace_state or {}).get("language") or "sv"
        prompts = default_prompts(language)
        if persona is not None:
            prompts = await require_prompts_for_persona(session, persona)
        await session.commit()
    loaded = WorkerIdentity(
        persona_id=identity.persona_id,
        name=name,
        workspace_id=identity.workspace_id,
        actor_user_id=identity.actor_user_id,
        workspace_state=identity.workspace_state,
    )
    return loaded, prompts


def _failed_call(error: str) -> str:
    return json.dumps({"ok": False, "error": error}, ensure_ascii=False)


def withhold_incomplete_spawn(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if _spawn_notice_seen(messages):
        return None
    counts = _incomplete_spawn_counts(messages)
    if counts is None:
        return None
    ok, failed = counts
    return {
        "role": "user",
        "content": json.dumps(
            {"spawn_complete": False, "worker_ok": ok, "worker_failed": failed},
            ensure_ascii=False,
        ),
    }


def _incomplete_spawn_counts(messages: Sequence[Mapping[str, Any]]) -> tuple[int, int] | None:
    ok = failed = 0
    seen = False
    for message in messages:
        if message.get("role") != "tool" or message.get("name") != SPAWN_TOOL_NAME:
            continue
        rows = _spawn_rows(message.get("content"))
        if rows is None:
            continue
        seen = True
        for row in rows:
            if row.get("ok") is True:
                ok += 1
            else:
                failed += 1
    if not seen or failed == 0:
        return None
    return ok, failed


def _spawn_notice_seen(messages: Sequence[Mapping[str, Any]]) -> bool:
    for message in messages:
        if message.get("role") != "user" or not isinstance(message.get("content"), str):
            continue
        try:
            payload = json.loads(message["content"])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("spawn_complete") is False:
            return True
    return False


def _spawn_rows(content: object) -> list[dict[str, Any]] | None:
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return None
    if isinstance(content, list):
        return [row for row in content if isinstance(row, dict)]
    if isinstance(content, dict) and content.get("ok") is False:
        return [content]
    return None


def _log_spawn(request: SpawnRequest, *, latency_ms: float, failed: int) -> None:
    tools = sorted({name for task in request.tasks for name in task.allowed_tools})
    log_event(
        logger,
        "expert_chat.reasoning_routed",
        dataset=EVENT_DATASET_EXPERT_CHAT,
        outcome="success",
        duration_ms=latency_ms,
        fields={
            "routing": {
                "phase": "spawn",
                "spawn_exposed": True,
                "worker_count": len(request.tasks),
                "worker_profile": request.worker_profile,
                "allowed_tools": tools,
                "worker_latency_ms": latency_ms,
                "worker_failed_count": failed,
            }
        },
    )
