"""Small lifecycle helpers for owned SME expert turns."""

import asyncio
import logging

from app.schemas.domain import PersonaChatResponse

logger = logging.getLogger(__name__)


def log_rerun_failure(task: asyncio.Task[PersonaChatResponse]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("Reclaimed expert turn failed", exc_info=exc)
