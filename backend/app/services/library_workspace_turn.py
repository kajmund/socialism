"""Workspace prompt, tools, and document open for one expert text turn."""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import UserAccount
from app.schemas.workspace import WorkspaceState
from app.services.expert_async_tools import LibraryToolScope
from app.services.expert_tool_followup import queue_document_open
from app.services.workspace.service import require_workspace
from app.services.workspace_chat_tools import workspace_openai_tools, workspace_turn_text
from app.services.workspace_document_context import source_for_open_request


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
        await require_workspace(session, workspace_id, actor)
    except HTTPException as exc:
        raise ChatTurnError(str(exc.detail), status_code=exc.status_code) from exc
    kept = [name for name in tool_names if name != "start_research"]
    return (
        workspace_turn_text(prompts, workspace_state),
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
    await _release_read(session)
    if opened:
        queue_document_open(scope, opened)
    if on_client_tools is None or not scope.client_calls:
        return
    await on_client_tools(
        [{"name": call.name, "arguments": call.arguments} for call in scope.client_calls]
    )


async def _release_read(session: AsyncSession) -> None:
    if not session.in_transaction():
        return
    previous = session.expire_on_rollback
    session.expire_on_rollback = False
    try:
        await session.rollback()
    finally:
        session.expire_on_rollback = previous


def chat_tools_for_turn(names: list[str], *, workspace: bool) -> list[str]:
    if not workspace:
        return names
    return [name for name in names if name != "start_research"]
