"""Run one read-only worker: short DB reads, then LLM, never both at once."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Literal

from app.config import settings
from app.llm import complete_text, complete_with_tools
from app.llm.tool_messages import tool_result_message
from app.services.expert_reasoning import bound_expert_profile
from app.services.expert_worker_schema import instance_matches
from app.services.expert_worker_scope import (
    confine_search_payload,
    load_source_scope,
    read_section_allowed,
)
from app.services.prompt_catalog import default_prompts, render_prompt
from app.services.workspace_chat_tools import workspace_openai_tools

logger = logging.getLogger(__name__)

WORKER_PROMPT_KEY = "chat.expert.worker_task"
_MAX_ROUNDS = 4


@dataclass(frozen=True)
class WorkerIdentity:
    persona_id: str
    name: str
    workspace_id: str | None
    actor_user_id: str | None
    workspace_state: dict[str, Any] | None


async def run_worker_task(
    task: object,
    *,
    identity: WorkerIdentity,
    worker_profile: Literal["fast", "balanced"],
    prompts: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        async with asyncio.timeout(settings.expert_reasoning_spawn_timeout_seconds):
            with bound_expert_profile(worker_profile):
                return await _run(task, identity, prompts or default_prompts("sv"))
    except TimeoutError:
        return {"ok": False, "error": "timeout"}
    except Exception:
        logger.exception("Expert worker failed")
        return {"ok": False, "error": "worker_failed"}


async def _run(
    task: object, identity: WorkerIdentity, prompts: dict[str, str]
) -> dict[str, Any]:
    schema = task.output_schema
    messages = [
        {
            "role": "system",
            "content": render_prompt(
                prompts,
                WORKER_PROMPT_KEY,
                expert_name=identity.name,
                task=task.task,
                context=task.context,
                scope_json=json.dumps(
                    {"source_id": task.scope.source_id, "ids": list(task.scope.ids)},
                    ensure_ascii=False,
                ),
                schema_json=json.dumps(schema, ensure_ascii=False),
            ),
        }
    ]
    specs = [
        spec
        for spec in workspace_openai_tools(prompts)
        if spec["function"]["name"] in task.allowed_tools
    ]
    if not specs:
        text = await complete_text(messages, prompt_key=WORKER_PROMPT_KEY)
        return _parse_result(text, schema)
    return await _tool_loop(
        messages, specs, task=task, identity=identity, schema=schema
    )


async def _tool_loop(
    messages: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    *,
    task: object,
    identity: WorkerIdentity,
    schema: dict[str, Any],
) -> dict[str, Any]:
    last = ""
    for _ in range(_MAX_ROUNDS):
        reply = await complete_with_tools(
            messages, specs, prompt_key=WORKER_PROMPT_KEY
        )
        calls = list(getattr(reply, "tool_calls", None) or [])
        text = str(getattr(reply, "content", "") or "")
        if text:
            last = text
        if not calls:
            return _parse_result(last, schema)
        messages.append({
            "role": "assistant",
            "content": text,
            "tool_calls": [
                {
                    "id": str(call.id),
                    "type": "function",
                    "function": {
                        "name": str(call.function.name),
                        "arguments": _raw_args(call.function.arguments),
                    },
                }
                for call in calls
            ],
        })
        for call in calls:
            content = await _run_scoped_tool(call, task, identity)
            messages.append(
                tool_result_message(
                    tool_call_id=str(call.id),
                    content=content,
                    name=str(call.function.name),
                )
            )
    return _parse_result(last, schema)


async def _run_scoped_tool(call: object, task: object, identity: WorkerIdentity) -> str:
    # Jobs/research import a cycle if this module loads expert_workspace_tool_run
    # during app.llm initialization.
    from app.services.dd.company_mcp import parse_tool_args
    from app.services.document_navigation import bound_worker_sections
    from app.services.expert_workspace_tool_run import run_workspace_tool_call

    name = str(call.function.name)
    arguments = parse_tool_args(call.function.arguments)
    index = await load_source_scope(task.scope.source_id)
    blocked = _scope_error(name, arguments, task.scope, titles=dict(index.titles))
    if blocked:
        return json.dumps({"ok": False, "error": blocked}, ensure_ascii=False)
    if name == "search_knowledge":
        arguments = {**arguments, "source_id": task.scope.source_id, "scope": "workspace"}
    work = SimpleNamespace(
        workspace_id=identity.workspace_id,
        actor_user_id=identity.actor_user_id,
        workspace_state=identity.workspace_state,
    )
    planned = SimpleNamespace(id=str(call.id), name=name, arguments=arguments)
    with bound_worker_sections(frozenset(task.scope.ids)):
        payload = await run_workspace_tool_call(planned, work)
    if name != "search_knowledge":
        return payload
    return confine_search_payload(payload, frozenset(task.scope.ids), index.passages)


def _scope_error(
    name: str,
    arguments: dict[str, Any],
    scope: object,
    titles: dict[str, str] | None = None,
) -> str | None:
    if name not in {"read_source", "search_knowledge"}:
        return "tool_not_on_read_list"
    source_id = arguments.get("source_id")
    if source_id not in (None, scope.source_id):
        return "scope_outside_document"
    if name == "search_knowledge":
        return _search_argument_error(arguments, scope)
    if read_section_allowed(arguments.get("section"), scope.ids, titles or {}):
        return None
    return "scope_outside_document"


def _search_argument_error(arguments: dict[str, Any], scope: object) -> str | None:
    # The model-facing search schema has no section field. confine_search_payload
    # drops hits outside the assignment; only an explicit id list is rejected here.
    requested = arguments.get("section_ids")
    if requested is None:
        return None
    if (
        isinstance(requested, list)
        and requested
        and all(isinstance(item, str) and item in scope.ids for item in requested)
    ):
        return None
    return "scope_outside_document"


def _parse_result(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(_json_payload(text))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"ok": False, "error": "invalid_json"}
    if not instance_matches(schema, parsed):
        return {"ok": False, "error": "schema_mismatch"}
    return {"ok": True, "result": parsed}


def _json_payload(text: str) -> str:
    start = min((index for index in (text.find("{"), text.find("[")) if index >= 0), default=-1)
    if start < 0:
        raise ValueError("invalid_json")
    end_object = text.rfind("}")
    end_array = text.rfind("]")
    end = max(end_object, end_array)
    if end < start:
        raise ValueError("invalid_json")
    return text[start : end + 1]


def _raw_args(raw: object) -> str:
    if isinstance(raw, str):
        return raw
    return json.dumps(raw, ensure_ascii=False)
