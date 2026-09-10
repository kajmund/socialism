"""Run generic_panel sessions — moderator, turn-taking, scratchpads, analysis."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession
from app.llm import complete_text
from app.services.dd.company_mcp import complete_text_with_company_tools
from app.services.expert_tools import expert_tool_prompt_extra
from app.services.panel.raise_hand import raise_hand_is_yes
from app.services.panel.research import (
    ExpertResearchNeeds,
    build_research_plan,
    collect_expert_research_needs,
    format_expert_research_need_turn,
    format_research_plan_turn,
)
from app.services.panel.schemas import (
    PanelExpertSlot,
    PanelSessionConfig,
    PanelTurn,
)
from app.services.panel.synthesis import (
    public_transcript_text,
    synthesize_generic_panel_result,
)
from app.services.panel.watch import run_turn
from app.services.prompt_catalog import render_prompt


def _expert_system(
    prompts: dict[str, str],
    slot: PanelExpertSlot,
    *,
    with_tools: bool = False,
) -> str:
    text = render_prompt(
        prompts, "panel.expert.system", label=slot.label, profile=slot.profile
    )
    if not with_tools:
        return text
    extra = expert_tool_prompt_extra(prompts, slot.tools)
    if not extra:
        return text
    return text + "\n\n" + extra


def _expert_list(config: PanelSessionConfig) -> str:
    return "\n".join(f"- {slot.label}: {slot.profile or slot.label}" for slot in config.expert_slots)


def _transcript_text(transcript: list[PanelTurn]) -> str:
    lines: list[str] = []
    for turn in transcript:
        name = turn.speaker if turn.phase != "scratchpad" else f"{turn.speaker} (scratchpad)"
        lines.append(f"{name}: {turn.content}")
    return "\n".join(lines)


def _session_brief(config: PanelSessionConfig) -> str:
    return (config.brief or "").strip()


def _messages_with_brief(
    *,
    identity: str,
    brief: str,
    user_content: str,
    evidence_prompt: str | None = None,
) -> list[dict[str, str]]:
    """Keep document brief as its own system message — same as structured_scoring."""
    messages = [{"role": "system", "content": identity}]
    if brief:
        messages.append({"role": "system", "content": brief})
    if evidence_prompt:
        messages.append({"role": "system", "content": evidence_prompt})
    messages.append({"role": "user", "content": user_content})
    return messages


async def _moderator_opening(
    config: PanelSessionConfig,
    prompts: dict[str, str],
    *,
    evidence_prompt: str | None = None,
) -> str:
    messages = _messages_with_brief(
        identity=render_prompt(prompts, "panel.moderator.system"),
        brief=_session_brief(config),
        evidence_prompt=evidence_prompt,
        user_content=render_prompt(
            prompts,
            "panel.moderator.opening",
            topic=config.topic,
            brief=config.brief or config.topic,
            expert_list=_expert_list(config),
        ),
    )
    return (await complete_text(messages)).strip()


async def _moderator_next_question(
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    prompts: dict[str, str],
    *,
    round_index: int,
    evidence_prompt: str | None = None,
) -> str:
    messages = _messages_with_brief(
        identity=render_prompt(prompts, "panel.moderator.system"),
        brief=_session_brief(config),
        evidence_prompt=evidence_prompt,
        user_content=render_prompt(
            prompts,
            "panel.moderator.next_question",
            topic=config.topic,
            transcript=_transcript_text(transcript),
            expert_list=_expert_list(config),
            round_index=round_index,
        ),
    )
    return (await complete_text(messages)).strip()


async def _moderator_missing_expertise(
    config: PanelSessionConfig,
    prompts: dict[str, str],
    *,
    evidence_prompt: str | None = None,
) -> str:
    messages = _messages_with_brief(
        identity=render_prompt(prompts, "panel.moderator.system"),
        brief=_session_brief(config),
        evidence_prompt=evidence_prompt,
        user_content=render_prompt(
            prompts,
            "panel.moderator.missing_expertise",
            topic=config.topic,
            brief=config.brief or config.topic,
            expert_list=_expert_list(config),
        ),
    )
    return (await complete_text(messages)).strip()


async def _expert_raise_hand(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    scratchpad: str,
    prompts: dict[str, str],
    *,
    evidence_prompt: str | None = None,
) -> bool:
    messages = _messages_with_brief(
        identity=_expert_system(prompts, slot),
        brief=_session_brief(config),
        evidence_prompt=evidence_prompt,
        user_content=render_prompt(
            prompts,
            "panel.expert.raise_hand",
            topic=config.topic,
            transcript=_transcript_text(transcript),
            scratchpad=scratchpad or "(tom)",
        ),
    )
    answer = (await complete_text(messages)).strip()
    return raise_hand_is_yes(answer)


async def _expert_complete(
    messages: list[dict[str, str]],
    slot: PanelExpertSlot,
    *,
    allow_expert_tools: bool,
) -> str:
    """Frozen-evidence mode uses plain completion even if the slot lists tools."""
    if not allow_expert_tools:
        return (await complete_text(messages)).strip()
    return (
        await complete_text_with_company_tools(
            messages, allowed_tools=frozenset(slot.tools)
        )
    ).strip()


async def _expert_scratchpad(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    scratchpad: str,
    prompts: dict[str, str],
    *,
    evidence_prompt: str | None = None,
    allow_expert_tools: bool = True,
) -> str:
    messages = _messages_with_brief(
        identity=_expert_system(prompts, slot, with_tools=allow_expert_tools),
        brief=_session_brief(config),
        evidence_prompt=evidence_prompt,
        user_content=render_prompt(
            prompts,
            "panel.expert.scratchpad",
            topic=config.topic,
            transcript=_transcript_text(transcript),
            scratchpad=scratchpad or "(tom)",
        ),
    )
    return await _expert_complete(
        messages, slot, allow_expert_tools=allow_expert_tools
    )


async def _expert_turn(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    scratchpad: str,
    prompts: dict[str, str],
    *,
    evidence_prompt: str | None = None,
    allow_expert_tools: bool = True,
) -> str:
    messages = _messages_with_brief(
        identity=_expert_system(prompts, slot, with_tools=allow_expert_tools),
        brief=_session_brief(config),
        evidence_prompt=evidence_prompt,
        user_content=render_prompt(
            prompts,
            "panel.expert.turn",
            topic=config.topic,
            transcript=_transcript_text(transcript),
            scratchpad=scratchpad or "(tom)",
        ),
    )
    return await _expert_complete(
        messages, slot, allow_expert_tools=allow_expert_tools
    )


async def _moderator_analysis(
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    prompts: dict[str, str],
    *,
    evidence_prompt: str | None = None,
) -> str:
    messages = _messages_with_brief(
        identity=render_prompt(prompts, "panel.moderator.system"),
        brief=_session_brief(config),
        evidence_prompt=evidence_prompt,
        user_content=render_prompt(
            prompts,
            "panel.moderator.analysis",
            topic=config.topic,
            transcript=public_transcript_text(transcript),
        ),
    )
    return (await complete_text(messages)).strip()


def _slot_by_id(config: PanelSessionConfig, slot_id: str) -> PanelExpertSlot:
    for slot in config.expert_slots:
        if slot.slot_id == slot_id:
            return slot
    raise RuntimeError(f"Unknown expert slot: {slot_id}")


async def _run_research_plan_phase(
    db: AsyncSession,
    panel: PanelSession,
    transcript: list[PanelTurn],
    config: PanelSessionConfig,
    prompts: dict[str, str],
    *,
    opening: str,
) -> bool:
    """Collect research needs. Returns True if any expert has domain competence."""
    proposals: list[tuple[PanelExpertSlot, ExpertResearchNeeds]] = []
    competent_slot_ids: list[str] = []
    for slot in config.expert_slots:

        async def produce_research_need(
            expert_slot: PanelExpertSlot = slot,
        ) -> str:
            bundle = await collect_expert_research_needs(
                expert_slot, config, opening, prompts
            )
            if bundle.has_domain_competence:
                competent_slot_ids.append(expert_slot.slot_id)
            proposals.append((expert_slot, bundle))
            return format_expert_research_need_turn(bundle)

        await run_turn(
            db,
            panel,
            transcript,
            speaker=slot.label,
            phase="research_need",
            slot_id=slot.slot_id,
            produce_content=produce_research_need,
        )

    async def produce_research_plan() -> str:
        plan = await build_research_plan(config, opening, proposals, prompts)
        panel.research_plan = plan.model_dump(mode="json")
        await db.flush()
        return format_research_plan_turn(plan)

    await run_turn(
        db,
        panel,
        transcript,
        speaker="moderator",
        phase="research_plan",
        produce_content=produce_research_plan,
    )
    return bool(competent_slot_ids)


async def run_generic_panel(
    db: AsyncSession,
    panel: PanelSession,
    prompts: dict[str, str],
    *,
    frozen_evidence: bool = False,
    evidence_prompt: str | None = None,
    allowed_evidence_refs: frozenset[str] | None = None,
) -> PanelSession:
    """Execute generic_panel protocol on a panel row (mutates and commits caller session).

    ``frozen_evidence=True`` is the Attempt path: skip ResearchPlan generation
    and disable expert tool/search calls even when slots list default tools.
    Standalone sessions keep the existing research-plan phase and tools.
    """
    config = PanelSessionConfig.model_validate(panel.config or {})
    allow_expert_tools = not frozen_evidence
    transcript: list[PanelTurn] = []
    scratchpads: dict[str, str] = dict(panel.scratchpads or {})
    for slot in config.expert_slots:
        scratchpads.setdefault(slot.slot_id, "")

    opening_turn = await run_turn(
        db,
        panel,
        transcript,
        speaker="moderator",
        phase="opening",
        produce_content=lambda: _moderator_opening(
            config, prompts, evidence_prompt=evidence_prompt
        ),
    )
    has_relevant_expert = True
    if not frozen_evidence:
        has_relevant_expert = await _run_research_plan_phase(
            db,
            panel,
            transcript,
            config,
            prompts,
            opening=opening_turn.content,
        )

    if not has_relevant_expert:
        await run_turn(
            db,
            panel,
            transcript,
            speaker="moderator",
            phase="unanswered",
            produce_content=lambda: _moderator_missing_expertise(
                config, prompts, evidence_prompt=evidence_prompt
            ),
        )
    for round_index in range(1, config.max_rounds + 1):
        if not has_relevant_expert:
            break
        if round_index > 1:
            await run_turn(
                db,
                panel,
                transcript,
                speaker="moderator",
                phase="sub_question",
                round_index=round_index,
                produce_content=lambda r=round_index: _moderator_next_question(
                    config,
                    transcript,
                    prompts,
                    round_index=r,
                    evidence_prompt=evidence_prompt,
                ),
            )
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
                    evidence_prompt=evidence_prompt,
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

        # Only raisers get scratchpad + expert-turn. An empty queue is valid.
        for slot_id in raise_hand_queue:
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
                    evidence_prompt=evidence_prompt,
                    allow_expert_tools=allow_expert_tools,
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
                    evidence_prompt=evidence_prompt,
                    allow_expert_tools=allow_expert_tools,
                ),
            )

    summary_turn = await run_turn(
        db,
        panel,
        transcript,
        speaker="moderator",
        phase="analysis",
        produce_content=lambda: _moderator_analysis(
            config, transcript, prompts, evidence_prompt=evidence_prompt
        ),
    )

    panel.scratchpads = scratchpads
    panel.analysis = summary_turn.content
    panel.result = (
        await synthesize_generic_panel_result(
            config=config,
            transcript=transcript,
            moderator_analysis=summary_turn.content,
            prompts=prompts,
            evidence_prompt=evidence_prompt,
            allowed_evidence_refs=allowed_evidence_refs,
        )
    ).model_dump(mode="json")
    panel.status = "succeeded"
    panel.error = None
    await db.flush()
    await db.refresh(panel)
    return panel
