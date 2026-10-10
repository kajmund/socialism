"""Automatic expert turns for SME group voice.

When the floor is granted, admit a real expert turn, run it, and speak the result.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from app.services.sme_expert_turns import accept_expert_turn, execute_expert_turn
from app.services.sme_group_voice import GroupVoiceSession
from app.services.sme_group_voice_runtime import GroupVoiceAudioRuntime
from app.services import jobs as jobs_service

logger = logging.getLogger(__name__)


async def run_floor_turn(
    *,
    session: GroupVoiceSession,
    runtime: GroupVoiceAudioRuntime,
    user_text: str,
    user_id: str,
    customer_id: int,
) -> None:
    """If an expert holds the floor, generate their reply and speak it."""
    persona_id = session.floor
    if not persona_id:
        return
    request_id = f"group-voice-{uuid4().hex}"
    factory = jobs_service.job_session_factory()
    try:
        async with factory() as db:
            turn, should_run = await accept_expert_turn(
                db,
                request_id=request_id,
                customer_id=customer_id,
                user_id=user_id,
                persona_id=persona_id,
                message=user_text,
                image_sha256=None,
            )
            await db.commit()
            if not should_run:
                return
            token = turn.lease_token or ""
            fence = turn.fence
        done = await execute_expert_turn(
            factory,
            request_id=request_id,
            persona_id=persona_id,
            message=user_text,
            image_sha256=None,
            fence=fence,
            token=token,
            on_token=lambda _delta: None,
            workspace_id=None,
            workspace_state=None,
            on_client_tools=None,
        )
        reply = (done.reply or "").strip()
        if reply and session.floor == persona_id:
            await runtime.speak_as(persona_id, reply)
    except Exception:
        logger.exception("group voice expert turn failed for %s", persona_id)
