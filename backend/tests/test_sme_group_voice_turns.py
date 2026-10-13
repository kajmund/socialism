"""Group voice floor turn — floor must return to open after failed or empty turns."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.domain import PersonaChatResponse
from app.services.sme_group_voice import GroupVoiceSession
from app.services.sme_group_voice_runtime import GroupVoiceAudioRuntime, GroupVoiceAudioScope
from app.services.sme_group_voice_turns import run_floor_turn


def _session() -> GroupVoiceSession:
    return GroupVoiceSession(
        panel_id="1",
        member_ids={"expert-a"},
        member_names={"expert-a": "Expert"},
    )


def _runtime(session: GroupVoiceSession) -> GroupVoiceAudioRuntime:
    emit_json = AsyncMock()
    emit_audio = AsyncMock()
    return GroupVoiceAudioRuntime(
        session,
        GroupVoiceAudioScope(language="sv", voice_ids={"expert-a": "voice-1"}),
        emit_json=emit_json,
        emit_audio=emit_audio,
    )


@pytest.mark.asyncio
async def test_run_floor_turn_releases_floor_when_expert_turn_fails():
    session = _session()
    session.grant_floor("expert-a")
    runtime = _runtime(session)

    with patch(
        "app.services.sme_group_voice_turns.accept_expert_turn",
        new_callable=AsyncMock,
        return_value=(AsyncMock(lease_token="tok", fence=1), True),
    ), patch(
        "app.services.sme_group_voice_turns.execute_expert_turn",
        new_callable=AsyncMock,
        side_effect=RuntimeError("llm down"),
    ), patch(
        "app.services.sme_group_voice_turns.jobs_service.job_session_factory",
    ):
        await run_floor_turn(
            session=session,
            runtime=runtime,
            user_text="Hej Expert",
            user_id="user-1",
            customer_id=1,
        )

    assert session.floor is None


@pytest.mark.asyncio
async def test_run_floor_turn_releases_floor_on_empty_reply():
    session = _session()
    session.grant_floor("expert-a")
    runtime = _runtime(session)
    empty = PersonaChatResponse(reply="", messages=[])

    with patch(
        "app.services.sme_group_voice_turns.accept_expert_turn",
        new_callable=AsyncMock,
        return_value=(AsyncMock(lease_token="tok", fence=1), True),
    ), patch(
        "app.services.sme_group_voice_turns.execute_expert_turn",
        new_callable=AsyncMock,
        return_value=empty,
    ), patch(
        "app.services.sme_group_voice_turns.jobs_service.job_session_factory",
    ):
        await run_floor_turn(
            session=session,
            runtime=runtime,
            user_text="Hej Expert",
            user_id="user-1",
            customer_id=1,
        )

    assert session.floor is None
