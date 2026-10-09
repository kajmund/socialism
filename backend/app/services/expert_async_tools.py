"""Run expert tools inside the turn that owns their final user-visible answer."""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona, PersonaMessage
from app.llm import complete_text, complete_with_tools
from app.llm.runtime_override import SelectionRole
from app.llm.tool_messages import assistant_message_dict
from app.schemas.domain import ChatMode
from app.services.actor_profiles import ACTOR_TOOL_IDS, ActorProfileTools, actor_tool_specs
from app.services.dd.company_mcp import (
    COMPANY_TOOL_NAMES,
    CompanyMcpClient,
    consult_calls_from_promise,
    last_user_question,
    parse_tool_args,
    run_company_tool,
    tool_calls_from_leaked_markup,
    visible_assistant_text,
)
from app.services.expert_session_tools import (
    CONSULT_TOOL_NAME, EVIDENCE_TOOL_NAME, RESEARCH_TOOL_NAME,
    consult_tool_spec, evidence_tool_spec, research_tool_spec,
)
from app.services.expert_chat_evidence import evidence_tool_handler_for_chat
from app.services.expert_chat_research_tool import research_tool_handler_for_chat
from app.services.expert_reasoning import RoutingDecision
from app.services.expert_tools import filter_openai_tools
from app.services.jobs import job_session_factory
from app.services.leaked_tool_text import read_promise_arguments
from app.services.expert_workspace_tool_run import run_workspace_tool_call
from app.services.expert_worker_spawn import SPAWN_TOOL_NAME, run_spawn_workers
from app.services.live_speech_progress import emit_tool_progress
from app.services.oasis_agent_tools import SEARCH_TOOL_NAMES, run_search_tool, search_tool_specs
from app.services.prompt_catalog import render_prompt
from app.services.workspace_chat_tools import CLIENT_TOOL_NAMES, SERVER_TOOL_NAMES

logger = logging.getLogger(__name__)

History = list[tuple[str, str, str | None]]
_active: ContextVar[LibraryToolScope | None] = ContextVar("library_tool_scope", default=None)


@dataclass(frozen=True)
class PlannedCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AckTurn:
    text: str
    calls: tuple[PlannedCall, ...]


@dataclass
class ToolWork:
    persona_id: str
    mode: ChatMode
    actor_user_id: str | None
    history: History
    user_message: str
    calls: tuple[PlannedCall, ...]
    workspace_id: str | None = None
    workspace_state: dict | None = None
    reasoning_profile: SelectionRole | None = None
    reasoning_decision: RoutingDecision | None = None
    turn_started_at: float | None = None
    episode: Any = None
    spawn_exposed: bool = False
    failed_calls: int = 0
    turn_id: str = ""


class LibraryToolScope:
    def __init__(
        self,
        *,
        enabled: bool,
        persona_id: str,
        mode: ChatMode,
        actor_user_id: str | None,
        history: History,
        user_message: str,
        workspace: tuple[str, dict] | None = None,
    ) -> None:
        self.enabled = enabled
        self.persona_id = persona_id
        self.customer_id: int | None = None
        self.mode = mode
        self.actor_user_id = actor_user_id
        self.history = history
        self.user_message = user_message
        self.turn_id = uuid4().hex
        self.workspace_id = None if workspace is None else workspace[0]
        self.workspace_state = None if workspace is None else workspace[1]
        self.client_calls: list[PlannedCall] = []
        self.reasoning_profile: SelectionRole | None = None
        self.reasoning_decision: RoutingDecision | None = None
        self.turn_started_at: float | None = None
        self.tool_retrieval = None
        self.spawn_exposed = False
        self._calls: list[PlannedCall] = []
        self._token: Any = None
        self._planned_call_ids: set[str] = set()

    async def enter(self) -> None:
        if not self.enabled:
            return
        self._token = _active.set(self)

    def defer(self, calls: tuple[PlannedCall, ...] | list[PlannedCall]) -> None:
        for call in calls:
            if call.id in self._planned_call_ids:
                continue
            self._planned_call_ids.add(call.id)
            if call.name in CLIENT_TOOL_NAMES:
                self.client_calls.append(call)
            else:
                self._calls.append(call)

    @property
    def tool_count(self) -> int:
        return len(self._calls) + len(self.client_calls)

    @property
    def has_deferred_calls(self) -> bool:
        return bool(self._calls)

    async def finish(self) -> None:
        if not self.enabled:
            return
        if self._token is not None:
            _active.reset(self._token)
            self._token = None


def begin_library_tools(
    *,
    persona_id: str,
    mode: ChatMode,
    actor_user_id: str | None,
    history: History,
    user_message: str,
    enabled: bool,
    workspace: tuple[str, dict] | None = None,
) -> LibraryToolScope:
    return LibraryToolScope(
        enabled=enabled,
        persona_id=persona_id,
        mode=mode,
        actor_user_id=actor_user_id,
        history=history,
        user_message=user_message,
        workspace=workspace,
    )


def active_library_tools() -> LibraryToolScope | None:
    scope = _active.get()
    if scope is None or not scope.enabled:
        return None
    return scope


async def acknowledge_expert_tools(
    messages: list[dict[str, Any]],
    *,
    allowed_tools: frozenset[str],
    prompts: dict[str, str],
    prompt_key: str | None,
    extra_specs: list[dict[str, Any]] | None = None,
    workspace_state: dict | None = None,
) -> AckTurn:
    specs = [*await _tool_specs(allowed_tools), *(extra_specs or [])]
    reply = await complete_with_tools(
        messages,
        specs,
        prompt_key=prompt_key,
        tool_choice="auto",
    )
    payload = assistant_message_dict(reply)
    text = visible_assistant_text(payload)
    calls = _planned_calls(
        reply,
        text,
        messages,
        offered=frozenset(str(spec["function"]["name"]) for spec in specs),
        consult=CONSULT_TOOL_NAME in allowed_tools,
        workspace_state=workspace_state,
    )
    # expert_reasoning_episode imports this module for the tool loop.
    from app.services.expert_reasoning_episode import remember_expert_episode

    if calls and not text:
        text = (
            await complete_text(
                [
                    *messages,
                    {"role": "user", "content": render_prompt(prompts, "chat.expert.tool_ack")},
                ],
                prompt_key="chat.expert.tool_ack",
            )
        ).strip()
    remember_expert_episode(
        messages, payload, tuple(calls), specs, prompt_key=prompt_key, display_text=text,
    )
    return AckTurn(text=text, calls=tuple(calls))


def tool_result_extra(prompts: dict[str, str], result: str) -> str:
    safe = result.replace("{", "{{").replace("}", "}}")
    return render_prompt(prompts, "chat.expert.tool_result", result=safe)


async def _tool_specs(allowed: frozenset[str]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    if allowed & COMPANY_TOOL_NAMES:
        async with CompanyMcpClient() as mcp:
            specs.extend(await mcp.openai_tools())
    specs.extend(search_tool_specs())
    specs.append(research_tool_spec())
    specs.append(evidence_tool_spec())
    specs.append(consult_tool_spec())
    specs.extend(actor_tool_specs())
    return filter_openai_tools(specs, allowed)


def _planned_calls(
    reply: object,
    text: str,
    messages: list[dict[str, Any]],
    *,
    offered: frozenset[str],
    consult: bool,
    workspace_state: dict | None = None,
) -> list[PlannedCall]:
    raw = list(getattr(reply, "tool_calls", None) or [])
    if not raw:
        raw = tool_calls_from_leaked_markup(str(getattr(reply, "content", "") or ""))
    if not raw and consult:
        raw = consult_calls_from_promise(text, last_user_question(messages))
    planned: list[PlannedCall] = []
    seen_ids: set[str] = set()
    for call in raw:
        call_id = str(call.id)
        name = str(call.function.name)
        if name not in offered or call_id in seen_ids:
            continue
        seen_ids.add(call_id)
        planned.append(PlannedCall(call_id, name, parse_tool_args(call.function.arguments)))
    if not planned and "read_source" in offered:
        promised = read_promise_arguments(text, workspace_state)
        if promised is not None:
            planned.append(PlannedCall("call_read_promise", "read_source", promised))
    return planned


def _work(scope: LibraryToolScope, calls: tuple[PlannedCall, ...]) -> ToolWork:
    return ToolWork(
        persona_id=scope.persona_id,
        mode=scope.mode,
        actor_user_id=scope.actor_user_id,
        history=list(scope.history),
        user_message=scope.user_message,
        calls=calls,
        workspace_id=scope.workspace_id,
        workspace_state=scope.workspace_state,
        reasoning_profile=scope.reasoning_profile,
        reasoning_decision=scope.reasoning_decision,
        turn_started_at=scope.turn_started_at,
        episode=getattr(scope, "episode", None),
        spawn_exposed=scope.spawn_exposed,
        turn_id=scope.turn_id,
    )


async def run_tool_calls(work: ToolWork) -> tuple[str, tuple[str, ...]]:
    parts: list[str] = []
    results: list[str] = []
    work.failed_calls = 0
    total = len(work.calls)
    for index, call in enumerate(work.calls):
        remaining = total - index
        await emit_tool_progress("started", call.name, remaining=remaining)
        try:
            text = await _run_one(call, work)
        except Exception as exc:
            logger.exception("Expert tool %s failed", call.name)
            work.failed_calls += 1
            text = str(exc) or call.name
        await emit_tool_progress(
            "partial",
            call.name,
            remaining=remaining - 1,
            summary=text,
        )
        results.append(text)
        if text:
            parts.append(f"{call.name}\n{text}")
    return "\n\n".join(parts), tuple(results)


async def complete_tool_episode(
    scope: LibraryToolScope,
    calls: tuple[PlannedCall, ...],
) -> str:
    """Run tool calls and their follow-up before the owning turn replies."""
    from app.services.expert_reasoning_episode import continue_expert_episode
    from app.services.expert_tool_followup import compose_tool_episode

    scope.defer(calls)
    calls = tuple(scope._calls)
    scope._calls.clear()
    work = _work(scope, calls)
    blob, results = await run_tool_calls(work) if calls else ("", ())

    async def publish(client_calls: list[PlannedCall]) -> None:
        if scope.customer_id is None:
            return
        from app.realtime.library_chat_broadcast import library_chat_broadcast

        for call in client_calls:
            await library_chat_broadcast.publish(scope.customer_id, scope.persona_id, {
                "type": "workspace_tool",
                "thread_type": "expert",
                "thread_id": scope.persona_id,
                "mode": scope.mode,
                "name": call.name,
                "arguments": call.arguments,
                "owner_turn_id": scope.turn_id,
            })

    text, reasoning = await compose_tool_episode(
        work,
        blob,
        results,
        continue_episode=continue_expert_episode,
        run_call=_run_one,
        publish=publish,
    )
    episode = getattr(scope, "episode", None)
    if episode is not None:
        scope.episode = replace(episode, reasoning_content=reasoning)
    return text.strip()


async def _run_one(call: PlannedCall, work: ToolWork) -> str:
    if call.name == SPAWN_TOOL_NAME:
        return await run_spawn_workers(call, work)
    if call.name in SERVER_TOOL_NAMES:
        return await run_workspace_tool_call(call, work)
    if call.name in COMPANY_TOOL_NAMES:
        return await run_company_tool(call.name, call.arguments)
    if call.name in SEARCH_TOOL_NAMES:
        return await asyncio.to_thread(run_search_tool, call.name, call.arguments)
    return await _run_session_tool(call, work)


async def _run_session_tool(call: PlannedCall, work: ToolWork) -> str:
    factory = job_session_factory()
    async with factory() as session:
        persona = await session.get(Persona, work.persona_id)
        if persona is None:
            raise ValueError("persona missing")
        text = await _dispatch_session_tool(session, persona, call, work)
        if session.in_transaction():
            await session.commit()
        return text


async def _dispatch_session_tool(
    session: AsyncSession,
    persona: Persona,
    call: PlannedCall,
    work: ToolWork,
) -> str:
    if call.name == RESEARCH_TOOL_NAME:
        handler = research_tool_handler_for_chat(
            session,
            persona=persona,
            history=work.history,
            user_message=work.user_message,
        )
        return await handler(call.arguments)
    if call.name == EVIDENCE_TOOL_NAME:
        prompts = await _prompts(session, persona)
        await session.commit()
        handler = evidence_tool_handler_for_chat(
            session,
            customer_id=persona.customer_id,
            prompts=prompts,
        )
        return await handler(call.arguments)
    if call.name == CONSULT_TOOL_NAME:
        # expert_consult imports chat.py, which imports this module.
        from app.services.expert_consult import consult_handler_for_persona

        prompts = await _prompts(session, persona)
        await session.commit()
        handler = consult_handler_for_persona(
            session,
            persona=persona,
            mode=work.mode,
            prompts=prompts,
        )
        if handler is None:
            raise ValueError("ask_expert is not available")
        return await handler(call.arguments)
    if call.name in ACTOR_TOOL_IDS:
        if not work.actor_user_id:
            raise ValueError("actor_not_found")
        return await ActorProfileTools(
            session,
            user_id=work.actor_user_id,
            customer_id=persona.customer_id,
            conversation=f"expert:{persona.id}:{work.mode}",
        )(call.name, call.arguments)
    raise ValueError(f"Unknown tool: {call.name}")


def _library_messages(persona_id: str, mode: str):
    return select(PersonaMessage).where(
        PersonaMessage.persona_id == persona_id,
        PersonaMessage.mode == mode,
        PersonaMessage.run_id.is_(None),
    ).order_by(PersonaMessage.id.asc())


async def _prompts(session: AsyncSession, persona: Persona) -> dict[str, str]:
    from app.services.prompt_store import require_prompts_for_persona

    return await require_prompts_for_persona(session, persona)


def _last_user_text(rows: list[PersonaMessage]) -> str:
    for row in reversed(rows):
        if row.role == "user" and row.content.strip():
            return row.content
    return ""
