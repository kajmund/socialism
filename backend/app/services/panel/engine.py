"""Run generic_panel sessions — moderator, turn-taking, scratchpads, analysis."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession
from app.llm import complete_text
from app.services.dd.company_mcp import complete_text_with_company_tools
from app.services.panel.schemas import (
    PanelExpertSlot,
    PanelSessionConfig,
    PanelTurn,
)
from app.services.panel.watch import run_turn
from app.services.prompt_catalog import render_prompt


def _expert_system(prompts: dict[str, str], slot: PanelExpertSlot) -> str:
    return (
        render_prompt(prompts, "panel.expert.system", label=slot.label, profile=slot.profile)
        + "\n\n"
        + render_prompt(prompts, "panel.expert.tools")
    )


def _expert_list(config: PanelSessionConfig) -> str:
    return "\n".join(f"- {slot.label}: {slot.profile or slot.label}" for slot in config.expert_slots)


def _transcript_text(transcript: list[PanelTurn]) -> str:
    lines: list[str] = []
    for turn in transcript:
        name = turn.speaker if turn.phase != "scratchpad" else f"{turn.speaker} (scratchpad)"
        lines.append(f"{name}: {turn.content}")
    return "\n".join(lines)


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
        {"role": "system", "content": _expert_system(prompts, slot)},
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
        {"role": "system", "content": _expert_system(prompts, slot)},
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
    return (await complete_text_with_company_tools(messages)).strip()


async def _expert_turn(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    scratchpad: str,
    prompts: dict[str, str],
) -> str:
    messages = [
        {"role": "system", "content": _expert_system(prompts, slot)},
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
    return (await complete_text_with_company_tools(messages)).strip()


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

    await run_turn(
        db,
        panel,
        transcript,
        speaker="moderator",
        phase="opening",
        produce_content=lambda: _moderator_opening(config, prompts),
    )

    for round_index in range(1, config.max_rounds + 1):
        raise_hand_queue: list[str] = []
        for slot in config.expert_slots:
            async def produce_raise_hand(
                expert_slot: PanelExpertSlot = slot,
            ) -> str:
                wants_turn = await _expert_raise_hand(
                    expert_slot,
                    config,
                    transcript,
                    scratchpads.get(expert_slot.slot_id, ""),
                    prompts,
                )
                return "JA" if wants_turn else "NEJ"

            turn = await run_turn(
                db,
                panel,
                transcript,
                speaker=slot.label,
                phase="raise_hand",
                round_index=round_index,
                slot_id=slot.slot_id,
                produce_content=produce_raise_hand,
            )
            if turn.content == "JA":
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

            async def produce_scratchpad(
                expert_slot: PanelExpertSlot = slot,
                pad_slot_id: str = slot_id,
            ) -> str:
                updated_pad = await _expert_scratchpad(
                    expert_slot,
                    config,
                    transcript,
                    scratchpads.get(pad_slot_id, ""),
                    prompts,
                )
                scratchpads[pad_slot_id] = updated_pad
                return updated_pad

            await run_turn(
                db,
                panel,
                transcript,
                speaker=slot.label,
                phase="scratchpad",
                round_index=round_index,
                slot_id=slot_id,
                produce_content=produce_scratchpad,
            )

            await run_turn(
                db,
                panel,
                transcript,
                speaker=slot.label,
                phase="expert",
                round_index=round_index,
                slot_id=slot_id,
                produce_content=lambda expert_slot=slot, pad_slot_id=slot_id: _expert_turn(
                    expert_slot,
                    config,
                    transcript,
                    scratchpads.get(pad_slot_id, ""),
                    prompts,
                ),
            )

    summary_turn = await run_turn(
        db,
        panel,
        transcript,
        speaker="moderator",
        phase="analysis",
        produce_content=lambda: _moderator_analysis(config, transcript, prompts),
    )

    panel.scratchpads = scratchpads
    panel.analysis = summary_turn.content
    panel.status = "succeeded"
    panel.error = None
    await db.flush()
    await db.refresh(panel)
    return panel
