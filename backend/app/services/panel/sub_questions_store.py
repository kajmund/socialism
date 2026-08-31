"""Persist and seed module-scoped panel sub-questions."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSubQuestion
from app.serializers import utcnow


def _unused_sort_order(taken: set[int], preferred: int) -> int:
    if preferred not in taken:
        return preferred
    return max(taken) + 1


class SubQuestionDefaultLike(Protocol):
    key: str
    label: str
    sort_order: int


async def get_sub_questions(
    session: AsyncSession,
    module: str,
    *,
    active_only: bool = True,
) -> list[PanelSubQuestion]:
    """Return sub-questions for a module, ordered by sort_order then key."""
    stmt = select(PanelSubQuestion).where(PanelSubQuestion.module == module)
    if active_only:
        stmt = stmt.where(PanelSubQuestion.active.is_(True))
    stmt = stmt.order_by(PanelSubQuestion.sort_order, PanelSubQuestion.key)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_sub_question(session: AsyncSession, row_id: int) -> PanelSubQuestion | None:
    return await session.get(PanelSubQuestion, row_id)


async def next_sub_question_sort_order(session: AsyncSession, module: str) -> int:
    rows = await get_sub_questions(session, module, active_only=False)
    if not rows:
        return 0
    return max(row.sort_order for row in rows) + 1


async def create_sub_question(
    session: AsyncSession,
    *,
    module: str,
    key: str,
    label: str,
    sort_order: int,
    active: bool = True,
) -> PanelSubQuestion:
    row = PanelSubQuestion(
        module=module,
        key=key,
        label=label,
        sort_order=sort_order,
        active=active,
        updated_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def update_sub_question(
    session: AsyncSession,
    row: PanelSubQuestion,
    *,
    label: str | None = None,
    sort_order: int | None = None,
    active: bool | None = None,
) -> PanelSubQuestion:
    if label is not None:
        row.label = label
    if sort_order is not None:
        row.sort_order = sort_order
    if active is not None:
        row.active = active
    row.updated_at = utcnow()
    await session.flush()
    await session.refresh(row)
    return row


async def ensure_sub_question_defaults(
    session: AsyncSession,
    module: str,
    defaults: list[SubQuestionDefaultLike] | tuple[SubQuestionDefaultLike, ...],
) -> int:
    """Insert missing (module, key) rows. Does not overwrite existing rows."""
    result = await session.execute(
        select(PanelSubQuestion).where(PanelSubQuestion.module == module)
    )
    existing_rows = list(result.scalars().all())
    existing_keys = {row.key for row in existing_rows}
    taken_orders = {row.sort_order for row in existing_rows}
    added = 0
    for default in defaults:
        if default.key in existing_keys:
            continue
        sort_order = _unused_sort_order(taken_orders, default.sort_order)
        session.add(
            PanelSubQuestion(
                module=module,
                key=default.key,
                label=default.label,
                sort_order=sort_order,
                active=True,
                updated_at=utcnow(),
            )
        )
        added += 1
        existing_keys.add(default.key)
        taken_orders.add(sort_order)
    if added:
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return 0
    return added
