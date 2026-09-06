"""structured_scoring method — expert × sub-question matrix with raise-hand gate."""

from __future__ import annotations

import json
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession
from app.llm import complete_text
from app.services.dd.company_mcp import run_company_tool_loop, visible_assistant_text
from app.services.dd.research import format_research_brief
from app.services.dd.schemas import DdCandidateCompany, DdResearchDossier
from app.services.dd.source_attribution import SourceBadge, resolve_source_badge
from app.services.dd.sub_questions import SubQuestionRef
from app.services.panel.result import envelope_from_dd_panel_result
from app.services.panel.schemas import (
    DdDissensusNote,
    DdExpertScore,
    DdPanelResult,
    DdUnansweredNote,
    PanelExpertSlot,
    PanelSessionConfig,
    PanelTurn,
)
from app.services.panel.spinndoctor_profile import (
    render_spinndoctor_identity,
    require_spinndoctor_profile,
)
from app.services.customer_scope import customer_id_for_panel_session
from app.services.panel.sub_questions_store import get_sub_questions
from app.services.panel.watch import run_turn
from app.services.prompt_catalog import render_prompt
from app.services.spindoctor_refs import strip_spindoctor_refs


async def _static_text(text: str) -> str:
    return text


def _candidate_brief(
    candidate: DdCandidateCompany,
    research: DdResearchDossier | None = None,
) -> str:
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
    if research is not None:
        lines.append("")
        lines.append(format_research_brief(research))
    return "\n".join(lines)


_RAISE_YES = frozenset({"JA", "YES"})
_RAISE_NO = frozenset({"NEJ", "NO"})
_RAISE_TOKEN = re.compile(r"[A-Za-zÅÄÖåäö]+")


def parse_raise_hand_reply(raw: str) -> tuple[bool, str]:
    """First token JA/YES vs NEJ/NO; keep the rest as the competence reason."""
    text = raw.strip()
    if not text:
        return False, "NEJ"
    first_line = text.split("\n", 1)[0]
    token_match = _RAISE_TOKEN.search(first_line)
    token = token_match.group(0).upper() if token_match else ""
    if token in _RAISE_YES:
        return True, text
    if token in _RAISE_NO:
        return False, text
    return False, text


def _candidate_has_figures(candidate: DdCandidateCompany) -> bool:
    if candidate.omsattning_sek is not None or candidate.anstallda is not None:
        return True
    return any(
        year.omsattning_sek is not None
        or year.resultat_sek is not None
        or year.anstallda is not None
        for year in candidate.rakenskaper
    )


def _transcript_text(transcript: list[PanelTurn]) -> str:
    lines: list[str] = []
    for turn in transcript:
        if turn.phase not in ("score", "unanswered"):
            continue
        lines.append(f"{turn.speaker}: {turn.content}")
    return "\n".join(lines) or "(inga poäng ännu)"


def _expert_list(slots: list[PanelExpertSlot]) -> str:
    return "\n".join(f"- {slot.label}: {slot.profile or slot.label}" for slot in slots)


def _visible_moderator_text(text: str) -> str:
    return strip_spindoctor_refs(text)


def _panel_brief(config: PanelSessionConfig) -> str:
    brief = (config.brief or config.topic or "").strip()
    if not brief:
        raise RuntimeError("structured_scoring session missing panel brief")
    return brief


def assemble_dd_moderator_messages(
    *,
    identity: str,
    brief: str,
    user_content: str,
) -> list[dict[str, str]]:
    """Catalog identity and panel brief are separate messages — not concatenated."""
    return [
        {"role": "system", "content": identity},
        {"role": "system", "content": brief},
        {"role": "user", "content": user_content},
    ]


async def build_dd_moderator_identity(
    session: AsyncSession,
    prompts: dict[str, str],
    *,
    customer_id: int,
) -> str:
    row = await require_spinndoctor_profile(session, customer_id=customer_id)
    identity = render_spinndoctor_identity(prompts, row)
    policy = render_prompt(prompts, "panel.dd.moderator.system")
    return f"{identity}\n\n{policy}"


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


async def _moderator_opening(
    config: PanelSessionConfig,
    prompts: dict[str, str],
    identity: str,
) -> str:
    messages = assemble_dd_moderator_messages(
        identity=identity,
        brief=_panel_brief(config),
        user_content=render_prompt(
            prompts,
            "panel.dd.moderator.opening",
            topic=config.topic,
            brief=config.brief or config.topic,
            expert_list=_expert_list(config.expert_slots),
        ),
    )
    return _visible_moderator_text(await complete_text(messages))


async def _moderator_sub_question(
    config: PanelSessionConfig,
    sub_question: SubQuestionRef,
    transcript: list[PanelTurn],
    prompts: dict[str, str],
    identity: str,
) -> str:
    messages = assemble_dd_moderator_messages(
        identity=identity,
        brief=_panel_brief(config),
        user_content=render_prompt(
            prompts,
            "panel.dd.moderator.sub_question",
            topic=config.topic,
            sub_question=sub_question.label,
            expert_list=_expert_list(config.expert_slots),
            transcript=_transcript_text(transcript),
        ),
    )
    return _visible_moderator_text(await complete_text(messages))


async def _expert_raise_hand_dd(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    sub_question: SubQuestionRef,
    prompts: dict[str, str],
) -> tuple[bool, str]:
    messages = [
        {
            "role": "system",
            "content": render_prompt(
                prompts, "panel.expert.system", label=slot.label, profile=slot.profile
            ),
        },
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "panel.dd.expert.raise_hand",
                topic=config.topic,
                sub_question=sub_question.label,
                brief=config.brief,
                label=slot.label,
            ),
        },
    ]
    answer = (await complete_text(messages)).strip()
    wants, visible = parse_raise_hand_reply(answer)
    return wants, visible


async def _expert_score(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    sub_question: SubQuestionRef,
    source: SourceBadge,
    transcript: list[PanelTurn],
    prompts: dict[str, str],
) -> tuple[int, str]:
    system = render_prompt(
        prompts, "panel.expert.system", label=slot.label, profile=slot.profile
    )
    if slot.tools:
        system = system + "\n\n" + render_prompt(prompts, "panel.expert.tools")
    messages = [
        {
            "role": "system",
            "content": system,
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
    if slot.tools:
        working, _found = await run_company_tool_loop(
            messages, with_search=True, allowed_tools=frozenset(slot.tools)
        )
        raw = visible_assistant_text(working[-1]).strip()
    else:
        working = list(messages)
        raw = (await complete_text(working)).strip()
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


async def _moderator_no_answer(
    config: PanelSessionConfig,
    sub_question: SubQuestionRef,
    expert_slots: list[PanelExpertSlot],
    prompts: dict[str, str],
    identity: str,
) -> str:
    messages = assemble_dd_moderator_messages(
        identity=identity,
        brief=_panel_brief(config),
        user_content=render_prompt(
            prompts,
            "panel.dd.moderator.no_answer",
            topic=config.topic,
            sub_question=sub_question.label,
            expert_list=", ".join(s.label for s in expert_slots),
        ),
    )
    return _visible_moderator_text((await complete_text(messages)).strip())


async def _moderator_summary(
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    scores: list[DdExpertScore],
    dissensus: list[DdDissensusNote],
    unanswered: list[DdUnansweredNote],
    prompts: dict[str, str],
    identity: str,
) -> str:
    score_lines = [
        f"- {row.expert_label} / {row.sub_question_label}: {row.score}/10 ({row.source.label})"
        for row in scores
    ]
    dissensus_lines = [
        f"- {note.sub_question_label}: spridning {note.spread} (lägst {note.min_score}, högst {note.max_score})"
        for note in dissensus
    ] or ["- Ingen tydlig dissensus (spridning < 3)"]
    unanswered_lines = [
        f"- {note.sub_question_label}: {note.moderator_note}"
        for note in unanswered
    ] or ["- Inga obesvarade delfrågor"]

    messages = assemble_dd_moderator_messages(
        identity=identity,
        brief=_panel_brief(config),
        user_content=render_prompt(
            prompts,
            "panel.dd.moderator.summary",
            topic=config.topic,
            transcript=_transcript_text(transcript),
            score_table="\n".join(score_lines),
            dissensus="\n".join(dissensus_lines),
            unanswered="\n".join(unanswered_lines),
        ),
    )
    return _visible_moderator_text(await complete_text(messages))


async def run_structured_scoring(
    db: AsyncSession,
    panel: PanelSession,
    prompts: dict[str, str],
) -> PanelSession:
    """Execute structured scoring — expert × sub-question matrix with raise-hand gate."""
    config = PanelSessionConfig.model_validate(panel.config or {})
    if config.candidate is None:
        raise RuntimeError("structured_scoring session missing candidate in config")
    module_id = config.module
    if not module_id:
        raise RuntimeError("structured_scoring requires config.module")

    candidate = config.candidate
    transcript: list[PanelTurn] = []
    scratchpads: dict[str, str] = dict(panel.scratchpads or {})
    for slot in config.expert_slots:
        scratchpads.setdefault(slot.slot_id, "")

    customer_id = await customer_id_for_panel_session(db, panel.id)
    identity = await build_dd_moderator_identity(db, prompts, customer_id=customer_id)

    await run_turn(
        db,
        panel,
        transcript,
        speaker="Spinndoktor",
        phase="opening",
        produce_content=lambda: _moderator_opening(config, prompts, identity),
    )

    scores: list[DdExpertScore] = []
    unanswered: list[DdUnansweredNote] = []
    rows = await get_sub_questions(db, module_id)
    if not rows:
        raise RuntimeError(f"No active panel sub-questions for module {module_id!r}")
    sub_questions = [SubQuestionRef(id=row.key, label=row.label) for row in rows]
    for round_index, sub_question in enumerate(sub_questions, start=1):
        await run_turn(
            db,
            panel,
            transcript,
            speaker="Spinndoktor",
            phase="sub_question",
            round_index=round_index,
            sub_question_id=sub_question.id,
            produce_content=lambda sq=sub_question: _moderator_sub_question(
                config, sq, transcript, prompts, identity
            ),
        )

        participating: list[PanelExpertSlot] = []
        for slot in config.expert_slots:

            async def produce_raise_hand(s=slot, sq=sub_question) -> str:
                _wants, visible = await _expert_raise_hand_dd(s, config, sq, prompts)
                return visible

            turn = await run_turn(
                db,
                panel,
                transcript,
                speaker=slot.label,
                phase="raise_hand",
                round_index=round_index,
                slot_id=slot.slot_id,
                sub_question_id=sub_question.id,
                produce_content=produce_raise_hand,
            )
            if parse_raise_hand_reply(turn.content)[0]:
                participating.append(slot)

        if not participating:
            note_turn = await run_turn(
                db,
                panel,
                transcript,
                speaker="Spinndoktor",
                phase="unanswered",
                round_index=round_index,
                sub_question_id=sub_question.id,
                produce_content=lambda sq=sub_question: _moderator_no_answer(
                    config, sq, config.expert_slots, prompts, identity
                ),
            )
            unanswered.append(
                DdUnansweredNote(
                    sub_question_id=sub_question.id,
                    sub_question_label=sub_question.label,
                    moderator_note=note_turn.content,
                )
            )
            continue

        for slot in participating:
            source = resolve_source_badge(
                figures_in_brief=_candidate_has_figures(candidate),
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
            config, transcript, scores, dissensus, unanswered, prompts, identity
        ),
    )
    summary = summary_turn.content

    result = DdPanelResult(
        candidate=candidate,
        scores=scores,
        dissensus=dissensus,
        unanswered=unanswered,
        summary=summary,
    )

    panel.scratchpads = scratchpads
    panel.analysis = summary
    panel.result = envelope_from_dd_panel_result(result).model_dump(mode="json")
    panel.status = "succeeded"
    panel.error = None
    await db.flush()
    await db.refresh(panel)
    return panel
