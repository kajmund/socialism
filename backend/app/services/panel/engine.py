"""Run generic_panel sessions — moderator, turn-taking, scratchpads, analysis."""

from __future__ import annotations

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession
from app.llm import complete_text
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig, PanelTurn
from app.services.prompt_catalog import render_prompt


def _expert_list(config: PanelSessionConfig) -> str:
    return "\n".join(f"- {slot.label}: {slot.profile or slot.label}" for slot in config.expert_slots)


def _transcript_text(transcript: list[PanelTurn]) -> str:
    lines: list[str] = []
    for turn in transcript:
        name = turn.speaker if turn.phase != "scratchpad" else f"{turn.speaker} (scratchpad)"
        lines.append(f"{name}: {turn.content}")
    return "\n".join(lines)


def _append_turn(
    transcript: list[PanelTurn],
    *,
    speaker: str,
    phase: PanelTurn["phase"],
    content: str,
    round_index: int | None = None,
    slot_id: str | None = None,
) -> PanelTurn:
    turn = PanelTurn(
        turn_id=f"turn_{secrets.token_hex(6)}",
        speaker=speaker,
        phase=phase,
        content=content.strip(),
        round_index=round_index,
        slot_id=slot_id,
    )
    transcript.append(turn)
    return turn


async def _moderator_opening(config: PanelSessionConfig, prompts: dict[str, str]) -> str:
    messages = [
        {"role": "system", "content": render_prompt(prompts, "panel.moderator.system")},
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "panel.moderator.opening",
                topic=config.topic,
                brief=config.brief or config.topic,
                expert_list=_expert_list(config),
            ),
        },
    ]
    return (await complete_text(messages)).strip()


async def _expert_raise_hand(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    scratchpad: str,
    prompts: dict[str, str],
) -> bool:
    messages = [
        {"role": "system", "content": render_prompt(prompts, "panel.expert.system", label=slot.label, profile=slot.profile)},
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "panel.expert.raise_hand",
                topic=config.topic,
                transcript=_transcript_text(transcript),
                scratchpad=scratchpad or "(tom)",
            ),
        },
    ]
    answer = (await complete_text(messages)).strip().upper()
    return answer.startswith("JA") or answer.startswith("YES") or answer.startswith("RAISE")


async def _expert_scratchpad(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    scratchpad: str,
    prompts: dict[str, str],
) -> str:
    messages = [
        {"role": "system", "content": render_prompt(prompts, "panel.expert.system", label=slot.label, profile=slot.profile)},
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "panel.expert.scratchpad",
                topic=config.topic,
                transcript=_transcript_text(transcript),
                scratchpad=scratchpad or "(tom)",
            ),
        },
    ]
    return (await complete_text(messages)).strip()


async def _expert_turn(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    scratchpad: str,
    prompts: dict[str, str],
) -> str:
    messages = [
        {"role": "system", "content": render_prompt(prompts, "panel.expert.system", label=slot.label, profile=slot.profile)},
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "panel.expert.turn",
                topic=config.topic,
                transcript=_transcript_text(transcript),
                scratchpad=scratchpad or "(tom)",
            ),
        },
    ]
    return (await complete_text(messages)).strip()


async def _moderator_analysis(
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    prompts: dict[str, str],
) -> str:
    messages = [
        {"role": "system", "content": render_prompt(prompts, "panel.moderator.system")},
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "panel.moderator.analysis",
                topic=config.topic,
                transcript=_transcript_text(transcript),
            ),
        },
    ]
    return (await complete_text(messages)).strip()


def _slot_by_id(config: PanelSessionConfig, slot_id: str) -> PanelExpertSlot:
    for slot in config.expert_slots:
        if slot.slot_id == slot_id:
            return slot
    raise RuntimeError(f"Unknown expert slot: {slot_id}")


async def run_generic_panel(
    db: AsyncSession,
    panel: PanelSession,
    prompts: dict[str, str],
) -> PanelSession:
    """Execute generic_panel protocol on a panel row (mutates and commits caller session)."""
    config = PanelSessionConfig.model_validate(panel.config or {})
    transcript: list[PanelTurn] = []
    scratchpads: dict[str, str] = dict(panel.scratchpads or {})
    for slot in config.expert_slots:
        scratchpads.setdefault(slot.slot_id, "")

    opening = await _moderator_opening(config, prompts)
    _append_turn(transcript, speaker="moderator", phase="opening", content=opening)

    for round_index in range(1, config.max_rounds + 1):
        raise_hand_queue: list[str] = []
        for slot in config.expert_slots:
            wants_turn = await _expert_raise_hand(
                slot,
                config,
                transcript,
                scratchpads.get(slot.slot_id, ""),
                prompts,
            )
            note = "JA" if wants_turn else "NEJ"
            _append_turn(
                transcript,
                speaker=slot.label,
                phase="raise_hand",
                content=note,
                round_index=round_index,
                slot_id=slot.slot_id,
            )
            if wants_turn:
                raise_hand_queue.append(slot.slot_id)

        spoken: set[str] = set()
        turn_order = raise_hand_queue + [
            slot.slot_id for slot in config.expert_slots if slot.slot_id not in raise_hand_queue
        ]

        for slot_id in turn_order:
            if slot_id in spoken:
                continue
            spoken.add(slot_id)
            slot = _slot_by_id(config, slot_id)

            updated_pad = await _expert_scratchpad(
                slot,
                config,
                transcript,
                scratchpads.get(slot_id, ""),
                prompts,
            )
            scratchpads[slot_id] = updated_pad
            _append_turn(
                transcript,
                speaker=slot.label,
                phase="scratchpad",
                content=updated_pad,
                round_index=round_index,
                slot_id=slot_id,
            )

            public = await _expert_turn(
                slot,
                config,
                transcript,
                scratchpads.get(slot_id, ""),
                prompts,
            )
            _append_turn(
                transcript,
                speaker=slot.label,
                phase="expert",
                content=public,
                round_index=round_index,
                slot_id=slot_id,
            )

    analysis = await _moderator_analysis(config, transcript, prompts)
    _append_turn(transcript, speaker="moderator", phase="analysis", content=analysis)

    panel.transcript = [t.model_dump(mode="json") for t in transcript]
    panel.scratchpads = scratchpads
    panel.analysis = analysis
    panel.status = "succeeded"
    panel.error = None
    await db.flush()
    await db.refresh(panel)
    return panel
