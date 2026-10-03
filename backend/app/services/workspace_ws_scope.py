"""Realtime delivery rechecks membership, including revocations after subscribe."""

from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import UserAccount
from app.services.workspace_api_scope import require_execution_attempt, require_job_scope


def workspace_event_authorizer(
    factory: async_sessionmaker[AsyncSession],
    user_id: str,
    *,
    attempt_id: str | None = None,
) -> Callable[[dict], Awaitable[bool]]:
    async def authorize(event: dict) -> bool:
        async with factory() as session:
            user = await session.get(UserAccount, user_id)
            if user is None:
                return False
            try:
                if attempt_id is not None:
                    await require_execution_attempt(session, user, attempt_id)
                else:
                    payload = event.get("job")
                    if not isinstance(payload, dict):
                        return False
                    job_id = payload.get("id")
                    if not isinstance(job_id, str):
                        return False
                    await require_job_scope(session, user, job_id)
            except HTTPException as exc:
                if exc.status_code not in (403, 404, 422):
                    raise
                return False
        return True

    return authorize
