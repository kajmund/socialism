"""Durable SME expert-chat turns keyed by client request_id."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PersonaMessage, SmeExpertTurn
from app.schemas.sme import SmeExpertTurnOut, SmeMessageOut
from app.serializers import utcnow

SME_EXPERT_TURN_STATUSES = frozenset({"accepted", "running", "succeeded", "failed"})
_ACTIVE_STATUSES = frozenset({"accepted", "running"})


class SmeExpertTurnConflict(Exception):
    """request_id is already bound to another user, customer, or expert."""


async def accept_expert_turn(
    session: AsyncSession,
    *,
    request_id: str,
    customer_id: int,
    user_id: str,
    persona_id: str,
    message: str,
    image_sha256: str | None,
) -> tuple[SmeExpertTurn, bool]:
    """Idempotent accept. Returns (turn, should_run)."""
    existing = await session.get(SmeExpertTurn, request_id)
    if existing is not None:
        _assert_same_owner(existing, customer_id=customer_id, user_id=user_id, persona_id=persona_id)
        return existing, existing.status == "accepted"
    turn = SmeExpertTurn(
        request_id=request_id,
        customer_id=customer_id,
        user_id=user_id,
        persona_id=persona_id,
        message=message,
        image_sha256=image_sha256,
        status="accepted",
        fence=1,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    try:
        async with session.begin_nested():
            session.add(turn)
            await session.flush()
    except IntegrityError:
        loaded = await session.get(SmeExpertTurn, request_id)
        if loaded is None:
            raise
        _assert_same_owner(loaded, customer_id=customer_id, user_id=user_id, persona_id=persona_id)
        return loaded, loaded.status == "accepted"
    return turn, True


def _assert_same_owner(
    turn: SmeExpertTurn,
    *,
    customer_id: int,
    user_id: str,
    persona_id: str,
) -> None:
    if (
        turn.customer_id != customer_id
        or turn.user_id != user_id
        or turn.persona_id != persona_id
    ):
        raise SmeExpertTurnConflict("request_id conflict")


async def mark_expert_turn_running(
    session: AsyncSession,
    request_id: str,
    *,
    fence: int,
) -> bool:
    result = await session.execute(
        update(SmeExpertTurn)
        .where(
            SmeExpertTurn.request_id == request_id,
            SmeExpertTurn.fence == fence,
            SmeExpertTurn.status == "accepted",
        )
        .values(status="running", updated_at=utcnow())
    )
    return result.rowcount == 1


async def finish_expert_turn(
    session: AsyncSession,
    request_id: str,
    *,
    fence: int,
    status: str,
    error: str | None = None,
) -> bool:
    if status not in {"succeeded", "failed"}:
        raise ValueError(f"Invalid expert turn status: {status}")
    result = await session.execute(
        update(SmeExpertTurn)
        .where(
            SmeExpertTurn.request_id == request_id,
            SmeExpertTurn.fence == fence,
            SmeExpertTurn.status.in_(tuple(_ACTIVE_STATUSES)),
        )
        .values(
            status=status,
            error=error,
            fence=fence + 1,
            updated_at=utcnow(),
        )
    )
    return result.rowcount == 1


async def get_owned_expert_turn(
    session: AsyncSession,
    request_id: str,
    *,
    customer_id: int,
    user_id: str,
) -> SmeExpertTurn | None:
    turn = await session.get(SmeExpertTurn, request_id)
    if turn is None:
        return None
    if turn.customer_id != customer_id or turn.user_id != user_id:
        return None
    return turn


async def serialize_expert_turn(
    session: AsyncSession,
    turn: SmeExpertTurn,
) -> SmeExpertTurnOut:
    messages: list[SmeMessageOut] = []
    if turn.status == "succeeded":
        result = await session.execute(
            select(PersonaMessage)
            .where(
                PersonaMessage.persona_id == turn.persona_id,
                PersonaMessage.mode == "interview",
                PersonaMessage.run_id.is_(None),
            )
            .order_by(PersonaMessage.id.asc())
        )
        messages = [
            SmeMessageOut(
                id=row.id,
                role=row.role,  # type: ignore[arg-type]
                content=row.content,
                created_at=row.created_at,
                persona_id=row.persona_id if row.role == "assistant" else None,
            )
            for row in result.scalars().all()
        ]
    return SmeExpertTurnOut(
        request_id=turn.request_id,
        thread_type="expert",
        thread_id=turn.persona_id,
        status=turn.status,  # type: ignore[arg-type]
        error=turn.error,
        messages=messages,
    )
