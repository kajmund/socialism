"""Admin CRUD for feedback items collected from help chat."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.schemas.domain import (
    FeedbackItemCreate,
    FeedbackItemOut,
    FeedbackItemUpdate,
    FeedbackKind,
    FeedbackStatus,
)
from app.services.feedback import (
    create_feedback_item,
    get_feedback_item,
    list_feedback_items,
    serialize_feedback_item,
    update_feedback_item,
)

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.get("", response_model=list[FeedbackItemOut])
async def list_feedback(
    status: FeedbackStatus | None = Query(default=None),
    kind: FeedbackKind | None = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[FeedbackItemOut]:
    rows = await list_feedback_items(
        session,
        status=status,
        kind=kind,
        include_archived=include_archived or status == "archived",
        limit=limit,
    )
    return [serialize_feedback_item(row) for row in rows]


@router.get("/{item_id}", response_model=FeedbackItemOut)
async def get_feedback(
    item_id: int,
    session: AsyncSession = Depends(get_session),
) -> FeedbackItemOut:
    return serialize_feedback_item(await get_feedback_item(session, item_id))


@router.post("", response_model=FeedbackItemOut, status_code=201)
async def create_feedback(
    body: FeedbackItemCreate,
    session: AsyncSession = Depends(get_session),
) -> FeedbackItemOut:
    row = await create_feedback_item(session, body)
    return serialize_feedback_item(row)


@router.patch("/{item_id}", response_model=FeedbackItemOut)
async def patch_feedback(
    item_id: int,
    body: FeedbackItemUpdate,
    session: AsyncSession = Depends(get_session),
) -> FeedbackItemOut:
    row = await update_feedback_item(session, item_id, body)
    return serialize_feedback_item(row)
