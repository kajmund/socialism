"""Persist and seed module-scoped panel sub-questions."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSubQuestion
from app.serializers import utcnow


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


async def ensure_sub_question_defaults(
    session: AsyncSession,
    module: str,
    defaults: list[SubQuestionDefaultLike] | tuple[SubQuestionDefaultLike, ...],
) -> int:
    """Insert missing (module, key) rows. Does not overwrite existing rows."""
    result = await session.execute(
        select(PanelSubQuestion).where(PanelSubQuestion.module == module)
    )
    existing_keys = {row.key for row in result.scalars().all()}
    added = 0
    for default in defaults:
        if default.key in existing_keys:
            continue
        session.add(
            PanelSubQuestion(
                module=module,
                key=default.key,
                label=default.label,
                sort_order=default.sort_order,
                active=True,
                updated_at=utcnow(),
            )
        )
        added += 1
        existing_keys.add(default.key)
    if added:
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return 0
    return added
