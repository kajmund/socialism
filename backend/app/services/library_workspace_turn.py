"""Workspace prompt, tools, and document open for one expert text turn."""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UserAccount
from app.realtime.library_chat_broadcast import library_chat_broadcast
from app.schemas.workspace import WorkspaceState
from app.services.expert_async_tools import LibraryToolScope, PlannedCall
from app.services.expert_tool_followup import queue_document_open
from app.services.workspace.service import require_workspace
from app.services.sme_open_document import format_workspace_documents
from app.services.workspace_chat_tools import workspace_openai_tools, workspace_turn_text
from app.services.workspace_turn_state import bind_open_titles, log_dynamic_context
from app.services.workspace_document_context import (
    artifact_for_open_request,
    present_document_call,
    ready_document_ids,
    source_for_open_request,
    voice_document_context,
)
from app.services.workspace_parent_documents import voice_document_inventory

async def prepare_workspace_chat(
    session: AsyncSession,
    *,
    prompts: dict[str, str],
    workspace_id: str | None,
    workspace_state: WorkspaceState | None,
    actor_user_id: str | None,
    tool_names: list[str],
) -> tuple[str, list[dict[str, Any]], dict | None]:
    # persona_chat imports this module, so ChatTurnError cannot be imported at module scope.
    from app.services.persona_chat import ChatTurnError

    if workspace_id is None:
        return "", [], None
    if actor_user_id is None or workspace_state is None:
        raise ChatTurnError("workspace_required", status_code=422)
    actor = await session.get(UserAccount, actor_user_id)
    if actor is None:
        raise ChatTurnError("actor_not_found", status_code=404)
    try:
        workspace = await require_workspace(session, workspace_id, actor)
    except HTTPException as exc:
        raise ChatTurnError(str(exc.detail), status_code=exc.status_code) from exc
    documents = await voice_document_context(session, workspace, actor, state=workspace_state)
    bind_open_titles(documents)
    note = format_workspace_documents(documents)
    turn = workspace_turn_text(prompts, workspace_state, documents=documents)
    kept = [name for name in tool_names if name != "start_research"]
    context = f"{turn}\n\n{note}" if note else turn
    log_dynamic_context(context)
    return (
        context,
        workspace_openai_tools(prompts, skip=frozenset(kept)),
        workspace_state.model_dump(),
    )


async def finish_workspace_turn(
    session: AsyncSession,
    scope: LibraryToolScope,
    on_client_tools: Callable[[list[dict[str, Any]]], Awaitable[None]] | None,
    *,
    workspace_id: str | None,
    actor_user_id: str | None,
    message: str,
    history: list[tuple[str, str, str | None]],
) -> None:
    opened = await source_for_open_request(
        session,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        message=message,
        history=history,
    )
    draft_id = None if opened else await artifact_for_open_request(
        session,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        message=message,
        history=history,
    )
    artifact_ids = await ready_document_ids(session, workspace_id) if workspace_id else set()
    inventory: list[dict] = []
    if workspace_id and actor_user_id and any(call.name == "show_document_set" for call in scope.client_calls):
        actor = await session.get(UserAccount, actor_user_id)
        if actor is not None:
            try:
                workspace = await require_workspace(session, workspace_id, actor)
            except HTTPException:
                workspace = None
            if workspace is not None:
                inventory = await voice_document_inventory(session, workspace, actor)
    await _release_read(session)
    # A multi-document gallery wins over the single-file open heuristic.
    if opened and not any(call.name == "show_document_set" for call in scope.client_calls):
        queue_document_open(scope, opened)
    elif draft_id and not any(call.name == "show_document_set" for call in scope.client_calls):
        _queue_draft_open(scope, draft_id)
    presented: list[PlannedCall] = []
    for call in scope.client_calls:
        name, arguments = present_document_call(
            call.name, dict(call.arguments), artifact_ids, inventory=inventory,
        )
        presented.append(PlannedCall(call.id, name, arguments))
    scope.client_calls = presented
    payload = [_client_tool_event(scope.persona_id, call.name, call.arguments) for call in scope.client_calls]
    if not payload:
        return
    if on_client_tools is not None:
        await on_client_tools(payload)
        return
    await _broadcast_expert_tools(scope, payload)


def _client_tool_event(persona_id: str, name: str, arguments: dict) -> dict:
    delivered = dict(arguments)
    if name == "focus_anchor" and persona_id:
        delivered["expert_id"] = persona_id
    return {"name": name, "arguments": delivered}


async def _broadcast_expert_tools(scope: LibraryToolScope, calls: list[dict[str, Any]]) -> None:
    """Turns without a tool callback still open the document on the expert channel."""
    if scope.customer_id is None:
        return
    for call in calls:
        await library_chat_broadcast.publish(scope.customer_id, scope.persona_id, {
            "type": "workspace_tool",
            "thread_type": "expert",
            "thread_id": scope.persona_id,
            "mode": scope.mode,
            "name": call["name"],
            "arguments": call["arguments"],
            "owner_turn_id": scope.turn_id,
        })


async def _release_read(session: AsyncSession) -> None:
    """Return a read-only transaction to the pool without expiring loaded objects.

    Rollback always expires the identity map, and AsyncSession has no
    expire_on_rollback. The chat session is created with expire_on_commit=False,
    so committing the read releases the connection and leaves those objects usable.
    """
    if not session.in_transaction():
        return
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("workspace_read_has_pending_writes")
    await session.commit()


def _queue_draft_open(scope: LibraryToolScope, artifact_id: str) -> None:
    already = any(
        call.name == "show_artifact" and call.arguments.get("artifact_id") == artifact_id
        for call in scope.client_calls
    )
    if already:
        return
    scope.client_calls.append(PlannedCall(f"open-{artifact_id}", "show_artifact", {"artifact_id": artifact_id}))


def chat_tools_for_turn(names: list[str], *, workspace: bool) -> list[str]:
    if not workspace:
        return names
    return [name for name in names if name != "start_research"]
