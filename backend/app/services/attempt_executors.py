"""Method dispatcher for ExecutionAttempt.execute. Persistence stays generic."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.execution.errors import ExecutionError
from app.services.execution.service import get_attempt
from app.services.panel.attempt_execution import (
    AttemptPanelResult,
    execute_generic_panel_attempt,
)

AttemptExecutor = Callable[..., Awaitable[AttemptPanelResult]]

ATTEMPT_EXECUTORS: dict[str, AttemptExecutor] = {
    "generic_panel": execute_generic_panel_attempt,
}


class UnsupportedAttemptTypeError(ExecutionError):
    def __init__(self, attempt_type: str) -> None:
        super().__init__(f"Unsupported attempt_type: {attempt_type}")
        self.attempt_type = attempt_type


async def execute_registered_attempt(
    session: AsyncSession,
    *,
    attempt_id: str,
    prompts: dict[str, str],
) -> AttemptPanelResult:
    attempt = await get_attempt(session, attempt_id)
    executor = ATTEMPT_EXECUTORS.get(attempt.attempt_type)
    if executor is None:
        raise UnsupportedAttemptTypeError(attempt.attempt_type)
    return await executor(session, attempt_id=attempt_id, prompts=prompts)
