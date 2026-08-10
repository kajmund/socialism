"""CRUD for feedback items (bugs / ideas / opinions)."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import FeedbackItem
from app.schemas.domain import (
    FeedbackItemCreate,
    FeedbackItemOut,
    FeedbackItemUpdate,
    FeedbackKind,
    FeedbackStatus,
    format_date,
)


def serialize_feedback_item(row: FeedbackItem) -> FeedbackItemOut:
    return FeedbackItemOut(
        id=row.id,
        kind=row.kind,  # type: ignore[arg-type]
        title=row.title,
        body=row.body,
        status=row.status,  # type: ignore[arg-type]
        source=row.source,  # type: ignore[arg-type]
        session_id=row.session_id,
        view_path=row.view_path,
        created_at=format_date(row.created_at) if row.created_at else "",
        updated_at=format_date(row.updated_at) if row.updated_at else "",
    )


async def get_feedback_item(session: AsyncSession, item_id: int) -> FeedbackItem:
    row = await session.get(FeedbackItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    return row


async def list_feedback_items(
    session: AsyncSession,
    *,
    status: FeedbackStatus | None = None,
    kind: FeedbackKind | None = None,
    include_archived: bool = False,
    limit: int = 100,
) -> list[FeedbackItem]:
    stmt = select(FeedbackItem).order_by(FeedbackItem.created_at.desc())
    if status is not None:
        stmt = stmt.where(FeedbackItem.status == status)
    elif not include_archived:
        stmt = stmt.where(FeedbackItem.status != "archived")
    if kind is not None:
        stmt = stmt.where(FeedbackItem.kind == kind)
    stmt = stmt.limit(max(1, min(limit, 200)))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_feedback_item(
    session: AsyncSession,
    body: FeedbackItemCreate,
    *,
    commit: bool = True,
) -> FeedbackItem:
    row = FeedbackItem(
        kind=body.kind,
        title=body.title.strip(),
        body=(body.body or "").strip(),
        status="open",
        source=body.source,
        session_id=body.session_id,
        view_path=body.view_path,
    )
    session.add(row)
    if commit:
        await session.commit()
        await session.refresh(row)
    else:
        await session.flush()
        await session.refresh(row)
    return row


async def update_feedback_item(
    session: AsyncSession,
    item_id: int,
    body: FeedbackItemUpdate,
) -> FeedbackItem:
    row = await get_feedback_item(session, item_id)
    data = body.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        data["title"] = str(data["title"]).strip()
    if "body" in data and data["body"] is not None:
        data["body"] = str(data["body"]).strip()
    for key, value in data.items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return row
