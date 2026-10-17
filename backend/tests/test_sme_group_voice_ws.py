"""SME group voice WebSocket handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.api import sme_group_voice_ws
from app.services.sme_group_voice import GroupVoiceSession


def _call(*, language: str = "sv") -> sme_group_voice_ws._Call:
    return sme_group_voice_ws._Call(
        session=GroupVoiceSession(
            panel_id="1",
            member_ids={"expert-a"},
            member_names={"expert-a": "Expert"},
        ),
        runtime=None,
        emit=AsyncMock(),
        push_snapshot=AsyncMock(),
        user_id="user-1",
        customer_id=42,
        language=language,
        speaking_task={},
    )


@pytest.mark.asyncio
async def test_release_floor_loads_customer_scoped_keep_hand_prompt():
    call = _call(language="en")
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = AsyncMock()
    session_cm.__aexit__.return_value = None

    def factory() -> AsyncMock:
        return session_cm

    with patch.object(
        sme_group_voice_ws.jobs_service,
        "job_session_factory",
        return_value=factory,
    ), patch.object(
        sme_group_voice_ws,
        "require_active_prompts",
        new_callable=AsyncMock,
        return_value={"sme.group_voice.keep_hand": "Keep {name}?"},
    ) as load_prompts, patch.object(
        call.session,
        "decide_keep_hands",
        new_callable=AsyncMock,
    ) as decide:
        await sme_group_voice_ws._on_release_floor(
            call,
            {"type": "release_floor", "transcript": "recent talk"},
        )

    load_prompts.assert_awaited_once()
    assert load_prompts.await_args.kwargs == {
        "customer_id": 42,
        "module": "dd",
        "language": "en",
    }
    decide.assert_awaited_once()
    assert decide.await_args.kwargs["keep_hand_prompt"] == "Keep {name}?"
