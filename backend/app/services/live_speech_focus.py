"""STT focus authorization: reload transcription keywords from readable sources."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services import jobs as jobs_service
from app.services.live_speech_stt_terms import (
    keywords_from_text_units,
    readable_focus_texts,
)

if TYPE_CHECKING:
    from app.services.live_speech_runtime import LiveSpeechRuntime

logger = logging.getLogger(__name__)


async def focus_sources(runtime: LiveSpeechRuntime, source_ids: list[str]) -> None:
    """Reauthorize each requested source against the readable scope, then update STT.

    The client supplies arbitrary ids, so every id is reauthorized against the
    session canvas and the user's readable workspace memberships before any of
    its text is loaded. Unreadable ids are dropped and logged; their text is
    never sent to the external STT.
    """
    scope = runtime.scope
    factory = jobs_service.job_session_factory()
    async with factory() as session:
        texts, dropped = await readable_focus_texts(
            session,
            customer_id=scope.customer_id,
            user_id=scope.user_id,
            canvas_workspace_id=scope.workspace_id,
            source_ids=source_ids,
        )
        await session.rollback()
    for source_id in dropped:
        logger.warning(
            "live_speech.focus_source_dropped source_id=%s customer_id=%s",
            source_id,
            scope.customer_id,
        )
    await runtime._stt.update(
        keywords=keywords_from_text_units(texts, base=runtime._base_keywords),
    )
