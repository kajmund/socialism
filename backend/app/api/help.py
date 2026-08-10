"""REST endpoints for in-app help chat history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.schemas.domain import HelpChatRequest, HelpChatResponse, HelpMessageOut
from app.services.help_chat import (
    ChatTurnError,
    clear_help_messages,
    list_help_messages,
    stream_help_chat_turn,
)

router = APIRouter(prefix="/help", tags=["help"])


@router.get("/messages", response_model=list[HelpMessageOut])
async def get_help_messages(
    session_id: str = Query(min_length=1, max_length=64),
    session: AsyncSession = Depends(get_session),
) -> list[HelpMessageOut]:
    return await list_help_messages(session, session_id)


@router.delete("/messages", status_code=204)
async def delete_help_messages(
    session_id: str = Query(min_length=1, max_length=64),
    session: AsyncSession = Depends(get_session),
) -> None:
    await clear_help_messages(session, session_id)


@router.post("/chat", response_model=HelpChatResponse)
async def post_help_chat(
    body: HelpChatRequest,
    session: AsyncSession = Depends(get_session),
) -> HelpChatResponse:
    done: HelpChatResponse | None = None
    try:
        async for item in stream_help_chat_turn(
            session,
            session_id=body.session_id,
            locale=body.locale,
            message=body.message,
        ):
            if isinstance(item, HelpChatResponse):
                done = item
    except ChatTurnError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if done is None:
        raise HTTPException(status_code=500, detail="Help chat produced no reply")
    return done
