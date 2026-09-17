"""Durable SME expert-chat turns keyed by client request_id."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import PersonaMessage, SmeExpertTurn
from app.schemas.domain import PersonaChatResponse
from app.schemas.sme import SmeExpertTurnOut, SmeMessageOut
from app.serializers import utcnow
from app.services.persona_chat import ChatTurnError, stream_library_chat_turn

logger = logging.getLogger(__name__)

SME_EXPERT_TURN_STATUSES = frozenset({"accepted", "running", "succeeded", "failed"})
_ACTIVE_STATUSES = frozenset({"accepted", "running"})
ReclaimOutcome = Literal["held", "succeeded", "failed", "rerun"]

EXPERT_TURN_LEASE_SECONDS = 60
EXPERT_TURN_UNRECOVERABLE = "expert_turn_unrecoverable"


class SmeExpertTurnConflict(Exception):
    """request_id is already bound to another owner or payload."""


def _expert_lease_ttl() -> timedelta:
    return timedelta(seconds=EXPERT_TURN_LEASE_SECONDS)


def expert_turn_heartbeat_seconds() -> float:
    return max(0.05, EXPERT_TURN_LEASE_SECONDS / 3)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _lease_expired(turn: SmeExpertTurn, now: datetime) -> bool:
    if turn.lease_expires_at is None:
        return True
    return _aware(turn.lease_expires_at) <= now


def _assert_same_binding(
    turn: SmeExpertTurn,
    *,
    customer_id: int,
    user_id: str,
    persona_id: str,
    message: str,
    image_sha256: str | None,
) -> None:
    if (
        turn.customer_id != customer_id
        or turn.user_id != user_id
        or turn.persona_id != persona_id
        or turn.message != message
        or turn.image_sha256 != image_sha256
    ):
        raise SmeExpertTurnConflict("request_id conflict")


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
        return await _accept_existing(
            session,
            existing,
            customer_id=customer_id,
            user_id=user_id,
            persona_id=persona_id,
            message=message,
            image_sha256=image_sha256,
        )
    now = utcnow()
    turn = SmeExpertTurn(
        request_id=request_id,
        customer_id=customer_id,
        user_id=user_id,
        persona_id=persona_id,
        message=message,
        image_sha256=image_sha256,
        status="accepted",
        fence=1,
        lease_token=uuid4().hex,
        lease_expires_at=now + _expert_lease_ttl(),
        created_at=now,
        updated_at=now,
    )
    try:
        async with session.begin_nested():
            session.add(turn)
            await session.flush()
    except IntegrityError:
        loaded = await session.get(SmeExpertTurn, request_id)
        if loaded is None:
            raise
        return await _accept_existing(
            session,
            loaded,
            customer_id=customer_id,
            user_id=user_id,
            persona_id=persona_id,
            message=message,
            image_sha256=image_sha256,
        )
    return turn, True


async def _accept_existing(
    session: AsyncSession,
    existing: SmeExpertTurn,
    *,
    customer_id: int,
    user_id: str,
    persona_id: str,
    message: str,
    image_sha256: str | None,
) -> tuple[SmeExpertTurn, bool]:
    _assert_same_binding(
        existing,
        customer_id=customer_id,
        user_id=user_id,
        persona_id=persona_id,
        message=message,
        image_sha256=image_sha256,
    )
    if existing.status not in _ACTIVE_STATUSES:
        return existing, False
    outcome = await reclaim_expired_expert_turn(session, existing)
    return existing, outcome == "rerun"


async def mark_expert_turn_running(
    session: AsyncSession,
    request_id: str,
    *,
    fence: int,
    token: str,
) -> bool:
    now = utcnow()
    result = await session.execute(
        update(SmeExpertTurn)
        .where(
            SmeExpertTurn.request_id == request_id,
            SmeExpertTurn.fence == fence,
            SmeExpertTurn.lease_token == token,
            SmeExpertTurn.status == "accepted",
        )
        .values(
            status="running",
            lease_expires_at=now + _expert_lease_ttl(),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


async def renew_expert_turn_lease(
    session: AsyncSession,
    request_id: str,
    *,
    token: str,
    fence: int,
) -> bool:
    now = utcnow()
    result = await session.execute(
        update(SmeExpertTurn)
        .where(
            SmeExpertTurn.request_id == request_id,
            SmeExpertTurn.lease_token == token,
            SmeExpertTurn.fence == fence,
            SmeExpertTurn.status.in_(tuple(_ACTIVE_STATUSES)),
        )
        .values(
            lease_expires_at=now + _expert_lease_ttl(),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
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
            lease_token=None,
            lease_expires_at=None,
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
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


async def _messages_since_turn(
    session: AsyncSession,
    turn: SmeExpertTurn,
) -> list[PersonaMessage]:
    result = await session.execute(
        select(PersonaMessage)
        .where(
            PersonaMessage.persona_id == turn.persona_id,
            PersonaMessage.mode == "interview",
            PersonaMessage.run_id.is_(None),
        )
        .order_by(PersonaMessage.id.asc())
    )
    start = _aware(turn.created_at)
    return [row for row in result.scalars().all() if _aware(row.created_at) >= start]


def _classify_saved_turn(
    rows: list[PersonaMessage],
    turn: SmeExpertTurn,
) -> Literal["none", "complete", "orphan", "unsafe"]:
    matches = [
        index
        for index, row in enumerate(rows)
        if row.role == "user"
        and row.content == turn.message
        and row.image_sha256 == turn.image_sha256
    ]
    if not matches:
        return "unsafe" if rows else "none"
    index = matches[0]
    if index + 1 < len(rows) and rows[index + 1].role == "assistant":
        return "complete"
    if index == len(rows) - 1:
        return "orphan"
    return "unsafe"


async def reclaim_expired_expert_turn(
    session: AsyncSession,
    turn: SmeExpertTurn,
) -> ReclaimOutcome:
    """Fence a stale worker and recover, rerun, or fail the turn."""
    if turn.status not in _ACTIVE_STATUSES:
        return "held"
    now = utcnow()
    if not _lease_expired(turn, now):
        return "held"
    fenced = await session.execute(
        update(SmeExpertTurn)
        .where(
            SmeExpertTurn.request_id == turn.request_id,
            SmeExpertTurn.fence == turn.fence,
            SmeExpertTurn.status.in_(tuple(_ACTIVE_STATUSES)),
            or_(
                SmeExpertTurn.lease_expires_at.is_(None),
                SmeExpertTurn.lease_expires_at <= now,
            ),
        )
        .values(
            fence=turn.fence + 1,
            lease_token=None,
            lease_expires_at=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if fenced.rowcount != 1:
        await session.refresh(turn)
        return "held"
    await session.refresh(turn)
    rows = await _messages_since_turn(session, turn)
    kind = _classify_saved_turn(rows, turn)
    if kind == "complete":
        await finish_expert_turn(
            session,
            turn.request_id,
            fence=turn.fence,
            status="succeeded",
        )
        await session.refresh(turn)
        return "succeeded"
    if kind == "orphan":
        await session.delete(rows[-1])
        await session.flush()
        kind = "none"
    if kind == "none":
        token = uuid4().hex
        adopted = await session.execute(
            update(SmeExpertTurn)
            .where(
                SmeExpertTurn.request_id == turn.request_id,
                SmeExpertTurn.fence == turn.fence,
                SmeExpertTurn.status.in_(tuple(_ACTIVE_STATUSES)),
            )
            .values(
                status="running",
                error=None,
                lease_token=token,
                lease_expires_at=now + _expert_lease_ttl(),
                updated_at=utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        if adopted.rowcount != 1:
            await session.refresh(turn)
            return "held"
        await session.refresh(turn)
        return "rerun"
    await finish_expert_turn(
        session,
        turn.request_id,
        fence=turn.fence,
        status="failed",
        error=EXPERT_TURN_UNRECOVERABLE,
    )
    await session.refresh(turn)
    return "failed"


class ExpertTurnHeartbeat:
    """Renew a held expert-turn lease until stopped. Stale token/fence never renews."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        request_id: str,
        *,
        token: str,
        fence: int,
    ) -> None:
        self._session_factory = session_factory
        self._request_id = request_id
        self._token = token
        self._fence = fence
        self.lost = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> ExpertTurnHeartbeat:
        self._task = asyncio.create_task(self._run())
        return self

    async def _run(self) -> None:
        interval = expert_turn_heartbeat_seconds()
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            async with self._session_factory() as session:
                held = await renew_expert_turn_lease(
                    session,
                    self._request_id,
                    token=self._token,
                    fence=self._fence,
                )
                await session.commit()
            if not held:
                self.lost.set()
                return

    async def aclose(self) -> None:
        self._stop.set()
        task = self._task
        if task is None:
            return
        self._task = None
        await task


async def execute_expert_turn(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    request_id: str,
    persona_id: str,
    message: str,
    image_sha256: str | None,
    fence: int,
    token: str,
    on_token: Callable[[str], Awaitable[None]] | None = None,
) -> PersonaChatResponse:
    heartbeat = ExpertTurnHeartbeat(
        session_factory,
        request_id,
        token=token,
        fence=fence,
    ).start()
    try:
        done: PersonaChatResponse | None = None
        async with session_factory() as session:
            stream = stream_library_chat_turn(
                session,
                persona_id=persona_id,
                mode="interview",
                message=message,
                image_sha256=image_sha256,
            )
            try:
                async for item in stream:
                    if heartbeat.lost.is_set():
                        raise ChatTurnError("stale_expert_turn", status_code=409)
                    if isinstance(item, PersonaChatResponse):
                        done = item
                    elif on_token is not None:
                        await on_token(item)
            finally:
                await stream.aclose()
        if heartbeat.lost.is_set():
            raise ChatTurnError("stale_expert_turn", status_code=409)
        if done is None:
            raise ChatTurnError("Chat turn produced no reply", status_code=502)
        async with session_factory() as session:
            wrote = await finish_expert_turn(
                session,
                request_id,
                fence=fence,
                status="succeeded",
            )
            await session.commit()
        if not wrote:
            raise ChatTurnError("stale_expert_turn", status_code=409)
        return done
    except ChatTurnError as exc:
        if exc.status_code != 409:
            await _fail_owned_expert_turn(
                session_factory,
                request_id,
                fence=fence,
                error=exc.detail,
            )
        raise
    except Exception:
        await _fail_owned_expert_turn(
            session_factory,
            request_id,
            fence=fence,
            error="Chat error",
        )
        raise
    finally:
        await heartbeat.aclose()


async def _fail_owned_expert_turn(
    session_factory: async_sessionmaker[AsyncSession],
    request_id: str,
    *,
    fence: int,
    error: str,
) -> None:
    async with session_factory() as session:
        await finish_expert_turn(
            session,
            request_id,
            fence=fence,
            status="failed",
            error=error,
        )
        await session.commit()


def schedule_expert_turn_rerun(
    session_factory: async_sessionmaker[AsyncSession],
    turn: SmeExpertTurn,
) -> asyncio.Task[PersonaChatResponse]:
    if turn.lease_token is None:
        raise RuntimeError("reclaimed expert turn is missing lease_token")
    task = asyncio.create_task(
        execute_expert_turn(
            session_factory,
            request_id=turn.request_id,
            persona_id=turn.persona_id,
            message=turn.message,
            image_sha256=turn.image_sha256,
            fence=turn.fence,
            token=turn.lease_token,
        )
    )
    task.add_done_callback(_log_rerun_failure)
    return task


def _log_rerun_failure(task: asyncio.Task[PersonaChatResponse]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("Reclaimed expert turn failed", exc_info=exc)
