"""Live panel session watch — WebSocket fan-out and replay payloads."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession
from app.realtime.panel_broadcast import panel_broadcast
from app.services.panel.schemas import PanelSessionConfig, PanelTurn, PanelTurnPhase


def new_turn_id() -> str:
    return f"turn_{secrets.token_hex(6)}"


def load_transcript(panel: PanelSession) -> list[PanelTurn]:
    raw = panel.transcript if isinstance(panel.transcript, list) else []
    return [PanelTurn.model_validate(item) for item in raw]


def existing_turn(
    transcript: list[PanelTurn],
    *,
    speaker: str,
    phase: PanelTurnPhase,
    round_index: int | None = None,
    slot_id: str | None = None,
    sub_question_id: str | None = None,
) -> PanelTurn | None:
    for turn in transcript:
        if (
            turn.speaker == speaker
            and turn.phase == phase
            and turn.round_index == round_index
            and turn.slot_id == slot_id
            and turn.sub_question_id == sub_question_id
        ):
            return turn
    return None


def build_panel_replay_payload(panel: PanelSession) -> dict[str, Any]:
    config = PanelSessionConfig.model_validate(panel.config or {})
    turns = [turn.model_dump(mode="json") for turn in load_transcript(panel)]
    return {
        "type": "panel.replay",
        "session_id": panel.id,
        "protocol": panel.protocol,
        "status": panel.status,
        "expert_slots": [slot.model_dump(mode="json") for slot in config.expert_slots],
        "turns": turns,
    }


async def publish_turn_started(
    session_id: str,
    *,
    turn_id: str,
    speaker: str,
    phase: PanelTurnPhase,
    round_index: int | None = None,
    slot_id: str | None = None,
    sub_question_id: str | None = None,
) -> None:
    await panel_broadcast.publish(
        session_id,
        {
            "type": "turn.started",
            "session_id": session_id,
            "turn_id": turn_id,
            "speaker": speaker,
            "phase": phase,
            "round_index": round_index,
            "slot_id": slot_id,
            "sub_question_id": sub_question_id,
        },
    )


async def publish_turn_completed(session_id: str, turn: PanelTurn) -> None:
    await panel_broadcast.publish(
        session_id,
        {
            "type": "turn.completed",
            "session_id": session_id,
            "turn": turn.model_dump(mode="json"),
        },
    )


async def publish_panel_finished(
    session_id: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "type": "panel.finished",
        "session_id": session_id,
        "status": status,
    }
    if error:
        payload["error"] = error
    await panel_broadcast.publish(session_id, payload)


async def append_turn_live(
    db: AsyncSession,
    panel: PanelSession,
    transcript: list[PanelTurn],
    turn: PanelTurn,
    *,
    scratchpads: dict[str, str] | None = None,
) -> PanelTurn:
    existing = existing_turn(
        transcript,
        speaker=turn.speaker,
        phase=turn.phase,
        round_index=turn.round_index,
        slot_id=turn.slot_id,
        sub_question_id=turn.sub_question_id,
    )
    if existing is not None:
        return existing
    transcript.append(turn)
    panel.transcript = [row.model_dump(mode="json") for row in transcript]
    if scratchpads is not None:
        panel.scratchpads = dict(scratchpads)
    await db.flush()
    await db.commit()
    await publish_turn_completed(panel.id, turn)
    return turn


async def run_turn(
    db: AsyncSession,
    panel: PanelSession,
    transcript: list[PanelTurn],
    *,
    speaker: str,
    phase: PanelTurnPhase,
    produce_content: Callable[[], Awaitable[str]],
    round_index: int | None = None,
    slot_id: str | None = None,
    sub_question_id: str | None = None,
    scratchpads: dict[str, str] | None = None,
) -> PanelTurn:
    existing = existing_turn(
        transcript,
        speaker=speaker,
        phase=phase,
        round_index=round_index,
        slot_id=slot_id,
        sub_question_id=sub_question_id,
    )
    if existing is not None:
        return existing
    turn_id = new_turn_id()
    await publish_turn_started(
        panel.id,
        turn_id=turn_id,
        speaker=speaker,
        phase=phase,
        round_index=round_index,
        slot_id=slot_id,
        sub_question_id=sub_question_id,
    )
    content = await produce_content()
    turn = PanelTurn(
        turn_id=turn_id,
        speaker=speaker,
        phase=phase,
        content=content.strip(),
        round_index=round_index,
        slot_id=slot_id,
        sub_question_id=sub_question_id,
    )
    return await append_turn_live(
        db, panel, transcript, turn, scratchpads=scratchpads
    )
