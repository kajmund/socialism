"""Authenticated native expert inbox within one private voice canvas."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database.models import UserAccount
from app.database.session import get_session
from app.services.voice_workspace_inbox import list_voice_inbox, mark_voice_expert_read
from app.services.workspace.service import require_workspace

router = APIRouter(prefix="/voice-workspaces", tags=["voice-workspace-inbox"])


class VoiceInboxItem(BaseModel):
    expert_id: str
    preview: str
    last_message_at: datetime | None
    unread_count: int


class VoiceReadResult(BaseModel):
    last_read_message_id: int | None


@router.get("/{canvas_id}/inbox", response_model=list[VoiceInboxItem])
async def inbox(canvas_id: str, *, session: AsyncSession = Depends(get_session),
                user: UserAccount = Depends(get_current_user)) -> list[dict]:
    canvas = await require_workspace(session, canvas_id, user)
    result = await list_voice_inbox(session, canvas)
    await session.rollback()
    return result


@router.post("/{canvas_id}/experts/{expert_id}/read", response_model=VoiceReadResult)
async def read(canvas_id: str, expert_id: str, *, session: AsyncSession = Depends(get_session),
               user: UserAccount = Depends(get_current_user)) -> dict:
    canvas = await require_workspace(session, canvas_id, user)
    last_id = await mark_voice_expert_read(session, canvas, expert_id)
    await session.commit()
    return {"last_read_message_id": last_id}
