"""Run generic_panel sessions — moderator, turn-taking, scratchpads, analysis."""

from __future__ import annotations

from app.services.actor_profiles import ActorToolHandler

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession, Population
from app.llm import complete_text
from app.services.dd.company_mcp import complete_text_with_company_tools
from app.services.expert_tools import expert_tool_prompt_extra
from app.services.expertgranskning.memory import get_expert_memory
from app.services.panel.competency import (
    UNASSESSABLE_PANEL_NOTE,
    CompetencyState,
    assess_panel_competency,
    competency_state_from_decisions,
)
from app.services.panel.raise_hand import raise_hand_is_yes
from app.services.panel.research import (
    ExpertResearchNeeds,
    apply_research_decisions,
    build_research_plan,
    collect_expert_research_needs,
    format_expert_research_need_turn,
    format_research_plan_turn,
)
from app.services.panel.review_intent import session_brief_for_llm
from app.services.panel.schemas import (
    PanelExpertSlot,
    PanelSessionConfig,
    PanelTurn,
)
from app.services.panel.synthesis import (
    public_transcript_text,
    synthesize_generic_panel_result,
)
from app.services.panel.watch import (
    commit_turn_checkpoint,
    existing_turn,
    load_transcript,
    run_turn,
)
from app.services.prompt_catalog import render_prompt
from app.services.review_contract import (
    display_speaker_label,
    messages_with_output_contract,
)


def _expert_system(
    prompts: dict[str, str],
    slot: PanelExpertSlot,
    *,
    with_tools: bool = False,
) -> str:
    text = render_prompt(prompts, "panel.expert.system", label=slot.label, profile=slot.profile)
    if not with_tools:
        return text
    extra = expert_tool_prompt_extra(prompts, slot.tools)
    if not extra:
        return text
    return text + "\n\n" + extra


def _expert_list(config: PanelSessionConfig) -> str:
    return "\n".join(
        f"- {slot.label}: {slot.profile or slot.label}" for slot in config.expert_slots
    )


def _transcript_text(transcript: list[PanelTurn]) -> str:
    lines: list[str] = []
    for turn in transcript:
        speaker = display_speaker_label(turn.speaker)
        name = speaker if turn.phase != "scratchpad" else f"{speaker} (scratchpad)"
        lines.append(f"{name}: {turn.content}")
    return "\n".join(lines)


def _session_brief(config: PanelSessionConfig, prompts: dict[str, str]) -> str:
    return session_brief_for_llm(config, prompts)


def _messages_with_brief(
    *,
    identity: str,
    brief: str,
    user_content: str,
    prompts: dict[str, str],
    evidence_prompt: str | None = None,
) -> list[dict[str, str]]:
    """Keep document brief as its own system message — same as structured_scoring."""
    messages = [{"role": "system", "content": identity}]
    if brief:
        messages.append({"role": "system", "content": brief})
    if evidence_prompt:
        messages.append({"role": "system", "content": evidence_prompt})
    messages.append({"role": "user", "content": user_content})
    return messages_with_output_contract(messages, prompts)


async def _moderator_opening(
    config: PanelSessionConfig,
    prompts: dict[str, str],
    *,
    evidence_prompt: str | None = None,
) -> str:
    messages = _messages_with_brief(
        identity=render_prompt(prompts, "panel.moderator.system"),
        brief=_session_brief(config, prompts),
        evidence_prompt=evidence_prompt,
        prompts=prompts,
        user_content=render_prompt(
            prompts,
            "panel.moderator.opening",
            topic=config.topic,
            brief=_session_brief(config, prompts) or config.topic,
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
        brief=_session_brief(config, prompts),
        evidence_prompt=evidence_prompt,
        prompts=prompts,
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
        brief=_session_brief(config, prompts),
        evidence_prompt=evidence_prompt,
        prompts=prompts,
        user_content=render_prompt(
            prompts,
            "panel.moderator.missing_expertise",
            topic=config.topic,
            brief=_session_brief(config, prompts) or config.topic,
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
        brief=_session_brief(config, prompts),
        evidence_prompt=evidence_prompt,
        prompts=prompts,
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
    actor_tool_handler: ActorToolHandler | None = None,
) -> str:
    """Frozen-evidence mode uses plain completion even if the slot lists tools."""
    if not allow_expert_tools:
        return (await complete_text(messages)).strip()
    return (
        await complete_text_with_company_tools(
            messages, allowed_tools=frozenset(slot.tools), actor_tool_handler=actor_tool_handler
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
    actor_tool_handler: ActorToolHandler | None = None,
) -> str:
    messages = _messages_with_brief(
        identity=_expert_system(prompts, slot, with_tools=allow_expert_tools),
        brief=_session_brief(config, prompts),
        evidence_prompt=evidence_prompt,
        prompts=prompts,
        user_content=render_prompt(
            prompts,
            "panel.expert.scratchpad",
            topic=config.topic,
            transcript=_transcript_text(transcript),
            scratchpad=scratchpad or "(tom)",
        ),
    )
    return await _expert_complete(
        messages, slot, allow_expert_tools=allow_expert_tools, actor_tool_handler=actor_tool_handler
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
    actor_tool_handler: ActorToolHandler | None = None,
) -> str:
    messages = _messages_with_brief(
        identity=_expert_system(prompts, slot, with_tools=allow_expert_tools),
        brief=_session_brief(config, prompts),
        evidence_prompt=evidence_prompt,
        prompts=prompts,
        user_content=render_prompt(
            prompts,
            "panel.expert.turn",
            topic=config.topic,
            transcript=_transcript_text(transcript),
            scratchpad=scratchpad or "(tom)",
        ),
    )
    return await _expert_complete(
        messages, slot, allow_expert_tools=allow_expert_tools, actor_tool_handler=actor_tool_handler
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
        brief=_session_brief(config, prompts),
        evidence_prompt=evidence_prompt,
        prompts=prompts,
        user_content=render_prompt(
            prompts,
            "panel.moderator.analysis",
            topic=config.topic,
            transcript=public_transcript_text(transcript),
        ),
    )
    return (await complete_text(messages)).strip()


async def _static_unassessable_note() -> str:
    return UNASSESSABLE_PANEL_NOTE


async def _static_text(value: str) -> str:
    return value


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
    scratchpads: dict[str, str],
    *,
    opening: str,
) -> CompetencyState:
    """Collect research needs. Competency is taken from the same structured reply."""
    proposals: list[tuple[PanelExpertSlot, ExpertResearchNeeds]] = []
    for slot in config.expert_slots:
        stored = existing_turn(
            transcript,
            speaker=slot.label,
            phase="research_need",
            slot_id=slot.slot_id,
        )

        if stored is not None:
            if stored.checkpoint is None:
                raise RuntimeError(f"Committed research need has no checkpoint: {stored.turn_id}")
            bundle = ExpertResearchNeeds.model_validate(stored.checkpoint)
            proposals.append((slot, bundle))
            continue

        bundle = await collect_expert_research_needs(slot, config, opening, prompts)
        proposals.append((slot, bundle))
        await run_turn(
            db,
            panel,
            transcript,
            speaker=slot.label,
            phase="research_need",
            slot_id=slot.slot_id,
            produce_content=lambda value=format_expert_research_need_turn(bundle, locale=config.locale): (
                _static_text(value)
            ),
            scratchpads=scratchpads,
            checkpoint=bundle.model_dump(mode="json"),
        )

    async def produce_research_plan() -> str:
        plan = await build_research_plan(config, opening, proposals, prompts)
        panel.research_plan = plan.model_dump(mode="json")
        return format_research_plan_turn(plan, locale=config.locale)

    await run_turn(
        db,
        panel,
        transcript,
        speaker="moderator",
        phase="research_plan",
        produce_content=produce_research_plan,
        scratchpads=scratchpads,
    )
    return apply_research_decisions(
        competency_state_from_decisions(proposals),
        proposals,
    )


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
    Competency is still assessed (profile vs question, no evidence).
    Standalone sessions keep the existing research-plan phase and tools.
    """
    config = PanelSessionConfig.model_validate(panel.config or {})
    allow_expert_tools = not frozen_evidence
    actor_tool_handler = None
    if allow_expert_tools and panel.job_id:
        from app.database.models import Job
        from app.services.actor_profiles import ActorProfileTools

        job = await db.get(Job, panel.job_id)
        owner = (job.request or {}).get("owner_user_id") if job else None
        if owner and job.customer_id is not None:
            actor_tool_handler = ActorProfileTools(
                db,
                user_id=owner,
                customer_id=job.customer_id,
                conversation=f"review:{panel.id}",
                requested_by_id=owner,
            )
    if panel.status == "succeeded" and panel.result:
        return panel
    transcript = load_transcript(panel)
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
        scratchpads=scratchpads,
    )
    saved_competency = (
        opening_turn.checkpoint.get("competency") if opening_turn.checkpoint is not None else None
    )
    if saved_competency is not None:
        competency = CompetencyState.model_validate(saved_competency)
    elif frozen_evidence:
        competency = await assess_panel_competency(config, prompts)
    else:
        competency = await _run_research_plan_phase(
            db,
            panel,
            transcript,
            config,
            prompts,
            scratchpads,
            opening=opening_turn.content,
        )
    if saved_competency is None:
        await commit_turn_checkpoint(
            db,
            panel,
            transcript,
            opening_turn,
            {"competency": competency.model_dump(mode="json")},
        )
    competent_ids = competency.competent_slot_ids()

    if not competency.has_relevant_expert():
        await run_turn(
            db,
            panel,
            transcript,
            speaker="moderator",
            phase="unanswered",
            produce_content=(
                _static_unassessable_note
                if competency.all_unassessable()
                else lambda: _moderator_missing_expertise(
                    config, prompts, evidence_prompt=evidence_prompt
                )
            ),
            scratchpads=scratchpads,
        )
    for round_index in range(1, config.max_rounds + 1):
        if not competency.has_relevant_expert():
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
                scratchpads=scratchpads,
            )
        raise_hand_queue: list[str] = []
        for slot in config.expert_slots:
            if slot.slot_id not in competent_ids:
                continue

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
                scratchpads=scratchpads,
            )
            # A later JA cannot override a failed competency decision.
            if turn.content == "JA" and slot.slot_id in competent_ids:
                raise_hand_queue.append(slot.slot_id)

        raise_hand_queue = [slot_id for slot_id in raise_hand_queue if slot_id in competent_ids]

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
                    actor_tool_handler=actor_tool_handler,
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
                scratchpads=scratchpads,
            )

            known_ids = {row.turn_id for row in transcript}
            expert_turn = await run_turn(
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
                    actor_tool_handler=actor_tool_handler,
                ),
                scratchpads=scratchpads,
            )
            if (
                expert_turn.turn_id not in known_ids
                and config.module == "expertgranskning"
                and panel.panel_id is not None
            ):
                population = await db.get(Population, panel.panel_id)
                if population is None:
                    raise RuntimeError(f"Expert panel not found for memory: {panel.panel_id}")
                question = next(
                    (
                        turn.content
                        for turn in reversed(transcript[:-1])
                        if turn.speaker == "moderator" and turn.phase in {"opening", "sub_question"}
                    ),
                    config.topic,
                )
                await get_expert_memory().add_chat_turn(
                    customer_id=population.customer_id,
                    expert_id=slot.slot_id,
                    user_message=question,
                    assistant_message=expert_turn.content,
                    source="panel_chat",
                    session_id=panel.id,
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
        scratchpads=scratchpads,
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
            competency=competency,
        )
    ).model_dump(mode="json")
    panel.status = "succeeded"
    panel.error = None
    await db.flush()
    await db.commit()
    await db.refresh(panel)
    return panel
