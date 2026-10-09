"""Admit a Live Speech turn and reload workspace state without holding I/O."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PersonaMessage
from app.database.workspace_models import VoiceWorkspace
from app.schemas.domain import EXPERT_CHAT_MODE
from app.schemas.workspace import WorkspaceState
from app.services.persona_chat import library_chat_filter
from app.services.sme_expert_turns import accept_expert_turn, mark_expert_turn_running

_RECENT_TURN_LIMIT = 6
_RECENT_TURN_CHARS = 400


async def recent_interview_turns(
    session: AsyncSession, expert_id: str
) -> tuple[tuple[str, str], ...]:
    rows = (
        await session.scalars(
            select(PersonaMessage)
            .where(*library_chat_filter(expert_id, EXPERT_CHAT_MODE))
            .order_by(PersonaMessage.id.desc())
            .limit(_RECENT_TURN_LIMIT)
        )
    ).all()
    return tuple((row.role, row.content[:_RECENT_TURN_CHARS]) for row in reversed(rows))


async def admit_voice_turn(factory, scope, request_id: str, text: str):
    async with factory() as session:
        turn, should_run = await accept_expert_turn(
            session,
            request_id=request_id,
            customer_id=scope.customer_id,
            user_id=scope.user_id,
            persona_id=scope.expert_id,
            message=text,
            image_sha256=None,
        )
        if not should_run or turn.lease_token is None:
            raise RuntimeError("voice_turn_not_admitted")
        marked = await mark_expert_turn_running(
            session,
            request_id,
            fence=turn.fence,
            token=turn.lease_token,
        )
        await session.commit()
    if not marked:
        raise RuntimeError("voice_turn_not_admitted")
    return turn


async def current_workspace_state(factory, scope) -> WorkspaceState:
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, scope.workspace_id)
        if (
            workspace is None
            or workspace.owner_user_id != scope.user_id
            or workspace.customer_id != scope.customer_id
        ):
            raise RuntimeError("voice_workspace_access_lost")
        state = WorkspaceState.model_validate(workspace.state)
        state.expert_id = scope.expert_id
        await session.rollback()
    return state
