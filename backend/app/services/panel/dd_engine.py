"""Run dd_panel sessions — Spinndoktor moderator, structured scoring matrix."""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession
from app.llm import complete_text
from app.services.dd.company_mcp import run_company_tool_loop, visible_assistant_text
from app.services.dd.schemas import DdCandidateCompany
from app.services.dd.source_attribution import SourceBadge, resolve_source_badge
from app.services.dd.sub_questions import DD_SUB_QUESTIONS, DdSubQuestion
from app.services.panel.schemas import (
    DdDissensusNote,
    DdExpertScore,
    DdPanelResult,
    PanelExpertSlot,
    PanelSessionConfig,
    PanelTurn,
)
from app.services.panel.watch import run_turn
from app.services.prompt_catalog import render_prompt
from app.services.spindoctor_refs import strip_spindoctor_refs


async def _static_text(text: str) -> str:
    return text


def _candidate_brief(candidate: DdCandidateCompany) -> str:
    lines = [
        f"Namn: {candidate.namn}",
        f"Organisationsnummer: {candidate.organisationsnummer}",
        f"Ålder: {candidate.alder_ar} år",
        f"Område: {candidate.omrade}",
        f"Resultat: {candidate.resultat}",
    ]
    if candidate.omsattning_sek is not None:
        lines.append(f"Omsättning: {candidate.omsattning_sek:,} SEK".replace(",", " "))
    if candidate.anstallda is not None:
        lines.append(f"Anställda: {candidate.anstallda}")
    if candidate.beskrivning:
        lines.append(f"Beskrivning: {candidate.beskrivning}")
    return "\n".join(lines)


def _transcript_text(transcript: list[PanelTurn]) -> str:
    lines: list[str] = []
    for turn in transcript:
        if turn.phase == "scratchpad":
            continue
        name = turn.speaker
        lines.append(f"{name}: {turn.content}")
    return "\n".join(lines)


def _expert_list(slots: list[PanelExpertSlot]) -> str:
    return "\n".join(f"- {slot.label}: {slot.profile or slot.label}" for slot in slots)


def _visible_moderator_text(text: str) -> str:
    return strip_spindoctor_refs(text)


def _slot_by_id(config: PanelSessionConfig, slot_id: str) -> PanelExpertSlot:
    for slot in config.expert_slots:
        if slot.slot_id == slot_id:
            return slot
    raise RuntimeError(f"Unknown expert slot: {slot_id}")


def _iter_json_objects(raw: str) -> list[dict[str, object]]:
    decoder = json.JSONDecoder()
    found: list[dict[str, object]] = []
    idx = 0
    while idx < len(raw):
        start = raw.find("{", idx)
        if start < 0:
            break
        try:
            data, end = decoder.raw_decode(raw, start)
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(data, dict):
            found.append(data)
        idx = end
    return found


def _parse_score_payload(raw: str) -> tuple[int, str]:
    for data in _iter_json_objects(raw):
        if "score" not in data:
            continue
        try:
            score = int(data["score"])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        motivation = str(data.get("motivation") or data.get("motivering") or "").strip()
        if score < 1 or score > 10 or not motivation:
            continue
        return score, motivation
    snippet = " ".join(raw.split())[:180]
    raise ValueError(f"Expert score response was not valid JSON: {snippet}")


def _dissensus_notes(scores: list[DdExpertScore]) -> list[DdDissensusNote]:
    by_question: dict[str, list[DdExpertScore]] = {}
    for row in scores:
        by_question.setdefault(row.sub_question_id, []).append(row)

    notes: list[DdDissensusNote] = []
    for question_id, rows in by_question.items():
        values = [row.score for row in rows]
        spread = max(values) - min(values)
        if spread >= 3:
            notes.append(
                DdDissensusNote(
                    sub_question_id=question_id,
                    sub_question_label=rows[0].sub_question_label,
                    min_score=min(values),
                    max_score=max(values),
                    spread=spread,
                )
            )
    return notes


async def _moderator_opening(config: PanelSessionConfig, prompts: dict[str, str]) -> str:
    messages = [
        {"role": "system", "content": render_prompt(prompts, "panel.moderator.system")},
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "panel.dd.moderator.opening",
                topic=config.topic,
                brief=config.brief or config.topic,
                expert_list=_expert_list(config.expert_slots),
            ),
        },
    ]
    return _visible_moderator_text(await complete_text(messages))


async def _moderator_sub_question(
    config: PanelSessionConfig,
    sub_question: DdSubQuestion,
    transcript: list[PanelTurn],
    prompts: dict[str, str],
) -> str:
    messages = [
        {"role": "system", "content": render_prompt(prompts, "panel.moderator.system")},
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "panel.dd.moderator.sub_question",
                topic=config.topic,
                sub_question=sub_question.label,
                transcript=_transcript_text(transcript),
            ),
        },
    ]
    return _visible_moderator_text(await complete_text(messages))


async def _expert_score(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    sub_question: DdSubQuestion,
    source: SourceBadge,
    transcript: list[PanelTurn],
    prompts: dict[str, str],
) -> tuple[int, str]:
    messages = [
        {
            "role": "system",
            "content": (
                render_prompt(
                    prompts, "panel.expert.system", label=slot.label, profile=slot.profile
                )
                + "\n\n"
                + render_prompt(prompts, "panel.expert.tools")
            ),
        },
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "panel.dd.expert.score",
                topic=config.topic,
                brief=config.brief,
                sub_question=sub_question.label,
                source_kind=source.kind,
                source_label=source.label,
                source_detail=source.detail,
                transcript=_transcript_text(transcript),
            ),
        },
    ]
    working, _found = await run_company_tool_loop(messages, with_search=True)
    raw = visible_assistant_text(working[-1]).strip()
    try:
        return _parse_score_payload(raw)
    except ValueError:
        working.append(
            {
                "role": "user",
                "content": render_prompt(prompts, "panel.dd.expert.score_json"),
            }
        )
        raw = (await complete_text(working)).strip()
        return _parse_score_payload(raw)


async def _moderator_summary(
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    scores: list[DdExpertScore],
    dissensus: list[DdDissensusNote],
    prompts: dict[str, str],
) -> str:
    score_lines = [
        f"- {row.expert_label} / {row.sub_question_label}: {row.score}/10 ({row.source.label})"
        for row in scores
    ]
    dissensus_lines = [
        f"- {note.sub_question_label}: spridning {note.spread} (lägst {note.min_score}, högst {note.max_score})"
        for note in dissensus
    ] or ["- Ingen tydlig dissensus (spridning < 3)"]

    messages = [
        {"role": "system", "content": render_prompt(prompts, "panel.moderator.system")},
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "panel.dd.moderator.summary",
                topic=config.topic,
                transcript=_transcript_text(transcript),
                score_table="\n".join(score_lines),
                dissensus="\n".join(dissensus_lines),
            ),
        },
    ]
    return _visible_moderator_text(await complete_text(messages))


async def run_dd_panel(
    db: AsyncSession,
    panel: PanelSession,
    prompts: dict[str, str],
) -> PanelSession:
    """Execute dd_panel protocol — structured expert × sub-question scoring."""
    config = PanelSessionConfig.model_validate(panel.config or {})
    if config.candidate is None:
        raise RuntimeError("dd_panel session missing candidate in config")

    candidate = config.candidate
    transcript: list[PanelTurn] = []
    scratchpads: dict[str, str] = dict(panel.scratchpads or {})
    for slot in config.expert_slots:
        scratchpads.setdefault(slot.slot_id, "")

    await run_turn(
        db,
        panel,
        transcript,
        speaker="Spinndoktor",
        phase="opening",
        produce_content=lambda: _moderator_opening(config, prompts),
    )

    scores: list[DdExpertScore] = []
    for round_index, sub_question in enumerate(DD_SUB_QUESTIONS, start=1):
        await run_turn(
            db,
            panel,
            transcript,
            speaker="Spinndoktor",
            phase="sub_question",
            round_index=round_index,
            sub_question_id=sub_question.id,
            produce_content=lambda sq=sub_question: _moderator_sub_question(
                config, sq, transcript, prompts
            ),
        )

        for slot in config.expert_slots:
            source = resolve_source_badge(
                sub_question_label=sub_question.label,
                candidate_name=candidate.namn,
                extra_context=candidate.beskrivning,
            )
            score_value, motivation = await _expert_score(
                slot,
                config,
                sub_question,
                source,
                transcript,
                prompts,
            )
            score_row = DdExpertScore(
                expert_slot_id=slot.slot_id,
                expert_label=slot.label,
                sub_question_id=sub_question.id,
                sub_question_label=sub_question.label,
                score=score_value,
                motivation=motivation,
                source=source,
            )
            scores.append(score_row)
            public = (
                f"Poäng {score_value}/10 — {motivation} "
                f"[Källa: {source.label}: {source.detail}]"
            )
            await run_turn(
                db,
                panel,
                transcript,
                speaker=slot.label,
                phase="score",
                round_index=round_index,
                slot_id=slot.slot_id,
                sub_question_id=sub_question.id,
                produce_content=lambda text=public: _static_text(text),
            )

    dissensus = _dissensus_notes(scores)
    summary_turn = await run_turn(
        db,
        panel,
        transcript,
        speaker="Spinndoktor",
        phase="analysis",
        produce_content=lambda: _moderator_summary(
            config, transcript, scores, dissensus, prompts
        ),
    )
    summary = summary_turn.content

    result = DdPanelResult(
        candidate=candidate,
        scores=scores,
        dissensus=dissensus,
        summary=summary,
    )

    panel.scratchpads = scratchpads
    panel.analysis = summary
    panel.result = result.model_dump(mode="json")
    panel.status = "succeeded"
    panel.error = None
    await db.flush()
    await db.refresh(panel)
    return panel
