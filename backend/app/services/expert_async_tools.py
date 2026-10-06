"""Return the expert's own short line, then run tools and weave the result in later."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Persona, PersonaMessage, UserAccount
from app.llm import complete_text, complete_with_tools
from app.llm.tool_messages import assistant_message_dict
from app.schemas.domain import ChatMode
from app.schemas.workspace import WorkspaceState
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
from app.services.expert_tools import filter_openai_tools
from app.services.jobs import enqueue_job, job_session_factory
from app.services.oasis_agent_tools import SEARCH_TOOL_NAMES, run_search_tool, search_tool_specs
from app.services.prompt_catalog import render_prompt
from app.services.workspace_chat_tools import CLIENT_TOOL_NAMES, SERVER_TOOL_NAMES

logger = logging.getLogger(__name__)

History = list[tuple[str, str, str | None]]
_active: ContextVar[LibraryToolScope | None] = ContextVar("library_tool_scope", default=None)
_threads: dict[tuple[str, str], _Thread] = {}
_tasks: set[asyncio.Task[None]] = set()


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


@dataclass
class _Thread:
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    busy: int = 0
    inflight: int = 0
    waking: bool = False
    pending: list[str] = field(default_factory=list)


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
        self.mode = mode
        self.actor_user_id = actor_user_id
        self.history = history
        self.user_message = user_message
        self.workspace_id = None if workspace is None else workspace[0]
        self.workspace_state = None if workspace is None else workspace[1]
        self.pending_result = ""
        self.client_calls: list[PlannedCall] = []
        self._calls: list[PlannedCall] = []
        self._thread: _Thread | None = None
        self._token: Any = None
        self._counted = False

    async def enter(self) -> None:
        if not self.enabled:
            return
        self._token = _active.set(self)
        thread = _threads.setdefault((self.persona_id, self.mode), _Thread())
        self._thread = thread
        async with thread.cond:
            thread.busy += 1
            self._counted = True
        await self._take_ready(thread)

    async def _take_ready(self, thread: _Thread) -> None:
        try:
            async with asyncio.timeout(settings.llm_timeout_seconds * 5):
                async with thread.cond:
                    while thread.inflight or thread.waking:
                        await thread.cond.wait()
                    self.pending_result = "\n\n".join(thread.pending)
                    thread.pending.clear()
        except TimeoutError:
            self.pending_result = ""

    def defer(self, calls: tuple[PlannedCall, ...] | list[PlannedCall]) -> None:
        for call in calls:
            if call.name in CLIENT_TOOL_NAMES:
                self.client_calls.append(call)
            else:
                self._calls.append(call)

    async def finish(self, *, deliver: bool) -> None:
        if not self.enabled:
            return
        if self._token is not None:
            _active.reset(self._token)
            self._token = None
        thread = self._thread
        if thread is None:
            return
        calls = tuple(self._calls) if deliver else ()
        async with thread.cond:
            if calls:
                thread.inflight += 1
            if self._counted:
                thread.busy -= 1
                self._counted = False
            thread.cond.notify_all()
        if calls:
            _track(_run_deferred(thread, _work(self, calls)))


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


def reset_library_tool_threads() -> None:
    _threads.clear()


async def wait_library_tool_tasks() -> None:
    while _tasks:
        await asyncio.gather(*list(_tasks))


async def acknowledge_expert_tools(
    messages: list[dict[str, Any]],
    *,
    allowed_tools: frozenset[str],
    prompts: dict[str, str],
    prompt_key: str | None,
    extra_specs: list[dict[str, Any]] | None = None,
) -> AckTurn:
    specs = [*await _tool_specs(allowed_tools), *(extra_specs or [])]
    reply = await complete_with_tools(messages, specs, prompt_key=prompt_key)
    payload = assistant_message_dict(reply)
    text = visible_assistant_text(payload)
    calls = _planned_calls(
        reply,
        text,
        messages,
        consult=CONSULT_TOOL_NAME in allowed_tools,
    )
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
    consult: bool,
) -> list[PlannedCall]:
    raw = list(getattr(reply, "tool_calls", None) or [])
    if not raw:
        raw = tool_calls_from_leaked_markup(str(getattr(reply, "content", "") or ""))
    if not raw and consult:
        raw = consult_calls_from_promise(text, last_user_question(messages))
    planned: list[PlannedCall] = []
    for call in raw:
        planned.append(
            PlannedCall(str(call.id), str(call.function.name), parse_tool_args(call.function.arguments))
        )
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
    )


def _track(coro: Awaitable[None]) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run_deferred(thread: _Thread, work: ToolWork) -> None:
    result = ""
    try:
        result = await run_deferred_calls(work)
    except Exception:
        logger.exception("Expert tool follow-up failed for %s", work.persona_id)
        result = ""
    blob = ""
    async with thread.cond:
        if result:
            thread.pending.append(result)
        thread.inflight -= 1
        idle = (
            thread.busy == 0
            and thread.inflight == 0
            and bool(thread.pending)
            and not thread.waking
        )
        if idle:
            thread.waking = True
            blob = "\n\n".join(thread.pending)
            thread.pending.clear()
        thread.cond.notify_all()
    if idle:
        # followup imports this module, so the wake import stays at the call.
        from app.services.expert_tool_followup import _wake

        await _wake(thread, work, blob)


async def run_deferred_calls(work: ToolWork) -> str:
    parts: list[str] = []
    for call in work.calls:
        try:
            text = await _run_one(call, work)
        except Exception as exc:
            logger.exception("Expert tool %s failed", call.name)
            text = str(exc) or call.name
        if text:
            parts.append(f"{call.name}\n{text}")
    return "\n\n".join(parts)


async def _run_workspace_tool(call: PlannedCall, work: ToolWork) -> str:
    # expert_async_tools loads during app.modules.registry init, via llm.chat.
    # workspace.tools imports that registry, so this import cannot sit at module level.
    from app.services.workspace.tools import _turn_state, execute_workspace_tool

    if not work.workspace_id or not work.actor_user_id or work.workspace_state is None:
        raise ValueError("workspace_required")
    factory = job_session_factory()
    async with factory() as session:
        user = await session.get(UserAccount, work.actor_user_id)
        if user is None:
            raise ValueError("actor_not_found")
        session.expunge(user)
        await session.rollback()
        try:
            token = _turn_state.set(WorkspaceState.model_validate(work.workspace_state))
            try:
                result = await execute_workspace_tool(
                    session,
                    workspace_id=work.workspace_id,
                    user=user,
                    tool_name=call.name,
                    arguments=call.arguments,
                    idempotency_key=call.id,
                )
            finally:
                _turn_state.reset(token)
        except HTTPException as exc:
            await session.rollback()
            return str(exc.detail)
        await session.commit()
    if result.get("status") == "queued" and result.get("job_id"):
        enqueue_job(result["job_id"])
    text = json.dumps(result, ensure_ascii=False)
    return text if len(text) <= 12000 else text[:12000]


async def _run_one(call: PlannedCall, work: ToolWork) -> str:
    if call.name in SERVER_TOOL_NAMES:
        return await _run_workspace_tool(call, work)
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
