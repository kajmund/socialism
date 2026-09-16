"""word_paragraph_review — moderator-led batched Word review.

A moderator filters each batch and writes review questions. Experts raise
a hand per question and comment only on questions they opted into. After
expert replies, overlapping observations are consolidated in a sliding
window with one-batch look-ahead, then persisted as soon as a batch owns
them. Nearby duplicates can still collapse across batch boundaries.
Rewrite suggestions publish when that batch finishes if at least two
experts comment on the same resolved paragraph anchor.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import ExpertgranskningResult, Job, PanelSession, WordAction
from app.serializers import utcnow
from app.services.expertgranskning.actor_context import (
    ActorContext,
    render_actor_context,
    resolve_actor_context,
)
from app.services.expertgranskning.comment_convergence import (
    WordConsolidatedComment,
    WordObservation,
    apply_word_comment_convergence,
    chunk_observations_for_convergence,
    collapse_intra_expert_duplicates,
    consolidated_from_observation,
    finalize_word_comment_convergence,
    format_observations_for_prompt,
    paragraph_indexes_for_observations,
)
from app.services.expertgranskning.intent_interview import (
    compose_expert_review_context,
    compose_intent_prefix,
)
from app.services.expertgranskning.memory import get_expert_memory
from app.services.expertgranskning.observation import (
    WordExpertCommentDraft,
    comment_exceeds_soft_cap,
    draft_from_observation,
    expand_expert_comment,
)
from app.services.expertgranskning.schemas import (
    ExpertgranskningWordJobRequest,
    WordBatchModeration,
    WordCommentConvergence,
    WordDocumentParagraph,
    WordDocumentSection,
    WordExpertComment,
    WordExpertObservation,
    WordExpertRaiseHand,
    WordExpertRoute,
    WordHeadingAssessment,
    WordParagraphComments,
    WordReviewQuestion,
    WordRewriteSuggestion,
)
from app.services.expertgranskning.watch import (
    publish_action_created,
    publish_expertgranskning_finished,
    publish_review_progress,
)
from app.services.expertgranskning.word_review_router import (
    WORD_REVIEW_MAX_ROUTED_EXPERTS,
    accepted_router_expert_ids,
    apply_router_ids,
    panel_experts_for_router,
    record_router_outcome,
    router_user_prompt,
)
from app.services.expertgranskning.word_review_timing import (
    WordReviewLimiter,
    WordReviewTimings,
    format_llm_usage_log,
)
from app.services.expertgranskning.word_review_units import (
    WordPublicationUnit,
    WordSectionDone,
    WordSectionFailed,
    WordSectionStats,
    batch_owned_indexes,
    leftover_observations,
    partition_owned_comments,
)
from app.services.expertgranskning.word_structured import complete_word_structured
from app.services.panel.expert_slots import load_expert_slots_from_population
from app.services.panel.schemas import PanelExpertSlot
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.review_contract import compose_review_system_context
from app.services.word.materialize import materialize_word_action
from app.services.word.tasks import (
    require_review_panel_task,
    selection_target_indexes,
)

logger = logging.getLogger(__name__)

_HEADING_1_TO_3 = re.compile(
    r"^(heading|rubrik)\s*[123]$",
    re.IGNORECASE,
)

WORD_BATCH_MAX_SIZE = 4
WORD_REVIEW_MAX_QUESTIONS_PER_BATCH = 2
WORD_REVIEW_MAX_RECOMMENDED_EXPERTS = WORD_REVIEW_MAX_ROUTED_EXPERTS

WordExpertCommentRow = tuple[
    PanelExpertSlot, WordReviewQuestion, WordExpertCommentDraft, int | None
]


@dataclass(frozen=True)
class WordBatchAnalysis:
    batch_index: int
    comments: list[WordExpertCommentRow]
    rewrites: list[tuple[WordDocumentParagraph, WordRewriteSuggestion]]
    paragraphs: list[WordDocumentParagraph]
    paragraph_reviews: int


# Output contract. Not part of the editable customer prompt.
_WORD_COMMENT_ANCHOR_SUFFIX = (
    "Allowed anchors: {indexes}. "
    "Return exactly one anchor_paragraph_index from this set. "
    "If several issues are material, return observations: one object per issue, "
    "each with its own anchor_paragraph_index from this set. "
    "Fields per observation: issue, analysis, source_perspective, "
    "target_perspective, statement_owner, recommendation_recipient, "
    "consequence, recommended_action, anchor_paragraph_index. "
    "Perspectives must be one of: user, document_author, counterpart, neutral. "
    "analysis is internal reasoning, not the Word margin text. "
    "Do not return one omnibus kommentar that covers several issues."
)
WORD_COMMENT_CONVERGENCE_SUFFIX = (
    "Output contract: return issues with observation_ids, paragraph_index, "
    "supporting_expert_ids, short_comment, explanation, materiality "
    "(high|medium|low), actionability (actionable|informational), "
    "novelty (new|overlap), should_materialize, and has_dissensus. "
    "short_comment is the Word margin text: one issue, about 30-70 words. "
    "explanation is the fuller reasoning. "
    "Merge only substantially identical issues. Preserve statement_owner and "
    "recommendation_recipient. Do not flip advice to the counterpart or "
    "reintroduce document-author voice as the user's voice. "
    "Do not return a kommentar field."
)


def word_comment_anchor_suffix(paragraph_indexes: Sequence[int]) -> str:
    indexes = ", ".join(str(index) for index in paragraph_indexes)
    return _WORD_COMMENT_ANCHOR_SUFFIX.format(indexes=indexes)


def render_comment_convergence_user_prompt(
    prompts: dict[str, str],
    *,
    section: WordDocumentSection,
    batch: list[WordDocumentParagraph],
    observations: list[WordObservation],
) -> str:
    """Render the editable convergence prompt, then append the output contract."""
    body = render_prompt(
        prompts,
        "expertgranskning.word.comment_convergence",
        section_heading=section.heading,
        batch_text=_batch_text(batch),
        observations=format_observations_for_prompt(observations),
    )
    return f"{body}\n\n{WORD_COMMENT_CONVERGENCE_SUFFIX}"


def render_expert_comment_user_prompt(
    prompts: dict[str, str],
    *,
    slot: PanelExpertSlot,
    section: WordDocumentSection,
    question: WordReviewQuestion,
    paragraphs: list[WordDocumentParagraph],
) -> str:
    """Render the editable comment prompt, then append the server-owned anchor contract."""
    body = render_prompt(
        prompts,
        "expertgranskning.word.expert.comment",
        label=slot.label,
        profile=slot.profile or slot.label,
        paragraph_text=_batch_text(paragraphs),
        list_string=", ".join(
            paragraph.list_string
            for paragraph in paragraphs
            if paragraph.list_string.strip()
        ),
        section_heading=section.heading,
        question=question.question,
        why_it_matters=question.why_it_matters,
        allowed_paragraph_indexes=", ".join(
            str(index) for index in question.paragraph_indexes
        ),
    )
    return f"{body}\n\n{word_comment_anchor_suffix(question.paragraph_indexes)}"


def paragraph_word_count(text: str) -> int:
    return len(text.split())


def is_heading_1_to_3(style: str) -> bool:
    return bool(_HEADING_1_TO_3.match(style.strip()))


def should_review_paragraph(paragraph: WordDocumentParagraph) -> bool:
    """Server-owned filter: skip short body text and Heading 1–3."""
    if is_heading_1_to_3(paragraph.style):
        return False
    return paragraph_word_count(paragraph.text) >= 4


def _expert_list(slots: list[PanelExpertSlot]) -> str:
    return "\n".join(
        f"- {slot.slot_id} ({slot.label}): {slot.profile or slot.label}"
        for slot in slots
    )


def _section_body(section: WordDocumentSection) -> str:
    parts = [section.heading.strip()] if section.heading.strip() else []
    parts.extend(paragraph.text.strip() for paragraph in section.paragraphs if paragraph.text.strip())
    return "\n\n".join(parts)


def _new_result_id() -> str:
    return f"egr_{secrets.token_hex(8)}"


def _clause_main_number(list_string: str) -> str | None:
    match = re.match(r"(\d+)", list_string.strip())
    return match.group(1) if match else None


def _format_brief_line(
    index: int,
    text: str,
    *,
    list_string: str = "",
    heading_style: str = "",
) -> str:
    parts = [f"[{index}]"]
    if heading_style.strip():
        parts.append(heading_style.strip())
    if list_string.strip():
        parts.append(list_string.strip())
    parts.append(text.strip())
    return " ".join(parts)


def _document_brief(payload: ExpertgranskningWordJobRequest) -> str:
    """Full document text with paragraph indexes, built once per job."""
    lines: list[str] = []
    for section in payload.sections:
        heading = section.heading.strip()
        if heading:
            lines.append(
                _format_brief_line(
                    section.heading_paragraph_index,
                    heading,
                    heading_style=section.heading_style,
                )
            )
        for paragraph in section.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            heading_style = paragraph.style if is_heading_1_to_3(paragraph.style) else ""
            lines.append(
                _format_brief_line(
                    paragraph.index,
                    text,
                    list_string=paragraph.list_string,
                    heading_style=heading_style,
                )
            )
    return "\n".join(lines)


def _batch_text(paragraphs: list[WordDocumentParagraph]) -> str:
    return "\n".join(
        _format_brief_line(
            paragraph.index,
            paragraph.text,
            list_string=paragraph.list_string,
        )
        for paragraph in paragraphs
    )


def build_batches(
    section: WordDocumentSection,
    max_size: int = WORD_BATCH_MAX_SIZE,
) -> list[list[WordDocumentParagraph]]:
    """Group reviewable paragraphs; never split a numbered clause."""
    reviewable = [paragraph for paragraph in section.paragraphs if should_review_paragraph(paragraph)]
    if not reviewable:
        return []

    groups: list[list[WordDocumentParagraph]] = []
    current: list[WordDocumentParagraph] = []
    current_key: str | None = None
    for paragraph in reviewable:
        key = _clause_main_number(paragraph.list_string)
        if current and key is not None and key == current_key:
            current.append(paragraph)
            continue
        if current:
            groups.append(current)
        current = [paragraph]
        current_key = key
    if current:
        groups.append(current)

    batches: list[list[WordDocumentParagraph]] = []
    batch: list[WordDocumentParagraph] = []
    for group in groups:
        if batch and len(batch) + len(group) > max_size:
            batches.append(batch)
            batch = []
        if not batch:
            batch = list(group)
        else:
            batch.extend(group)
        if len(batch) >= max_size:
            batches.append(batch)
            batch = []
    if batch:
        batches.append(batch)
    return batches


def _batches_for_target(
    section: WordDocumentSection,
    target: frozenset[int] | None,
    max_size: int = WORD_BATCH_MAX_SIZE,
) -> list[list[WordDocumentParagraph]]:
    batches = build_batches(section, max_size)
    if target is None:
        return batches
    filtered: list[list[WordDocumentParagraph]] = []
    for batch in batches:
        kept = [paragraph for paragraph in batch if paragraph.index in target]
        if kept:
            filtered.append(kept)
    return filtered


def heading_in_scope(
    section: WordDocumentSection,
    target: frozenset[int] | None,
) -> bool:
    if target is None:
        return True
    return section.heading_paragraph_index in target


async def _llm[T](
    limiter: WordReviewLimiter,
    category: str,
    messages: list[dict[str, str]],
    response_model: type[T],
    prompts: dict[str, str],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
) -> T:
    return await limiter.run(
        category,
        lambda: complete_word_structured(
            messages,
            response_model,
            prompts=prompts,
            timings=limiter.timings,
            model=model,
            max_tokens=max_tokens,
        ),
    )


def _messages_with_brief(
    *,
    identity: str,
    brief: str,
    user: str,
    review_context: str = "",
    actor_context: str = "",
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if identity.strip():
        messages.append({"role": "system", "content": identity})
    if actor_context.strip():
        messages.append({"role": "system", "content": actor_context})
    if review_context.strip():
        messages.append({"role": "system", "content": review_context})
    if brief.strip():
        messages.append({"role": "system", "content": brief})
    messages.append({"role": "user", "content": user})
    return messages


def _questions_text(questions: list[WordReviewQuestion]) -> str:
    blocks: list[str] = []
    for question in questions:
        indexes = ", ".join(str(index) for index in question.paragraph_indexes)
        block = f"[{question.id}] stycken {indexes}: {question.question}"
        if question.why_it_matters:
            block += f"\n  {question.why_it_matters}"
        blocks.append(block)
    return "\n".join(blocks)


def accepted_recommended_expert_ids(
    raw_ids: Sequence[str],
    panel_slot_ids: frozenset[str],
    *,
    limit: int = WORD_REVIEW_MAX_RECOMMENDED_EXPERTS,
) -> list[str]:
    """Keep at most `limit` known panel slot IDs, in first-seen order."""
    kept, _invalid = accepted_router_expert_ids(
        raw_ids, panel_slot_ids, limit=limit
    )
    return kept


def resolve_question_primary_anchor(
    indexes: list[int],
    raw_primary: int | None,
) -> int | None:
    """Sole remaining paragraph wins; otherwise the moderator's in-scope pick."""
    if len(indexes) == 1:
        return indexes[0]
    if raw_primary is not None and raw_primary in indexes:
        return raw_primary
    return None


def routed_and_unresolved_questions(
    questions: list[WordReviewQuestion],
) -> tuple[list[WordReviewQuestion], list[WordReviewQuestion]]:
    """Direct-route questions with valid recommendations; rest stay unresolved."""
    routed: list[WordReviewQuestion] = []
    unresolved: list[WordReviewQuestion] = []
    for question in questions:
        if question.recommended_expert_ids:
            routed.append(question)
        else:
            unresolved.append(question)
    return routed, unresolved


def _append_unique_assignment(
    assignments: list[tuple[PanelExpertSlot, WordReviewQuestion]],
    seen_pairs: set[tuple[str, str]],
    slot: PanelExpertSlot,
    question: WordReviewQuestion,
) -> None:
    key = (slot.slot_id, question.id)
    if key in seen_pairs:
        return
    seen_pairs.add(key)
    assignments.append((slot, question))


def accepted_review_questions(
    parsed: WordBatchModeration,
    batch: list[WordDocumentParagraph],
    *,
    target_indexes: frozenset[int] | None = None,
    panel_slot_ids: frozenset[str] | None = None,
    timings: WordReviewTimings | None = None,
    max_questions: int = WORD_REVIEW_MAX_QUESTIONS_PER_BATCH,
) -> list[WordReviewQuestion]:
    """Keep in-batch questions; drop a batch that does not need review."""
    if not parsed.needs_review:
        return []
    allowed = {paragraph.index for paragraph in batch}
    if target_indexes is not None:
        allowed &= target_indexes
    kept: list[WordReviewQuestion] = []
    seen_ids: set[str] = set()
    dropped_invalid_anchor = 0
    for question in parsed.questions:
        if len(kept) >= max_questions:
            break
        question_id = question.id.strip()
        if not question_id or question_id in seen_ids:
            continue
        if not question.question.strip():
            continue
        indexes: list[int] = []
        for index in question.paragraph_indexes:
            if index in allowed and index not in indexes:
                indexes.append(index)
        if not indexes:
            continue
        primary = resolve_question_primary_anchor(
            indexes, question.primary_anchor_paragraph_index
        )
        if primary is None:
            dropped_invalid_anchor += 1
            continue
        seen_ids.add(question_id)
        kept.append(
            WordReviewQuestion(
                id=question_id,
                paragraph_indexes=indexes,
                question=question.question.strip(),
                why_it_matters=question.why_it_matters.strip(),
                primary_anchor_paragraph_index=primary,
                recommended_expert_ids=[],
            )
        )
    if dropped_invalid_anchor:
        logger.info(
            "Dropped Word review questions with invalid primary anchor: %s",
            dropped_invalid_anchor,
        )
        if timings is not None:
            timings.record_dropped_invalid_anchor(dropped_invalid_anchor)
    return kept


def selected_review_questions(
    question_ids: list[str],
    questions: list[WordReviewQuestion],
    *,
    expert_id: str,
) -> list[WordReviewQuestion]:
    by_id = {question.id: question for question in questions}
    kept: list[WordReviewQuestion] = []
    seen: set[str] = set()
    for raw_id in question_ids:
        question_id = raw_id.strip()
        question = by_id.get(question_id)
        if question is None:
            logger.info(
                "Dropped unknown question id %s from expert %s",
                question_id,
                expert_id,
            )
            continue
        if question_id in seen:
            continue
        seen.add(question_id)
        kept.append(question)
    return kept


def _expert_identity(prompts: dict[str, str], slot: PanelExpertSlot) -> str:
    return render_prompt(
        prompts,
        "panel.expert.system",
        label=slot.label,
        profile=slot.profile or slot.label,
    )


async def _write_result(
    session: AsyncSession,
    *,
    job_id: str,
    customer_id: int,
    section_index: int,
    paragraph_index: int,
    expert_id: str,
    expert_namn: str,
    kommentar: str,
    is_heading_suggestion: bool,
    is_rewrite_suggestion: bool = False,
    foreslagen_text: str | None = None,
    explanation: str | None = None,
    request: dict | None = None,
    source_ordinal: int = 0,
    commit: bool = True,
) -> ExpertgranskningResult:
    row = ExpertgranskningResult(
        id=_new_result_id(),
        job_id=job_id,
        customer_id=customer_id,
        section_index=section_index,
        paragraph_index=paragraph_index,
        expert_id=expert_id,
        expert_namn=expert_namn,
        kommentar=kommentar,
        is_heading_suggestion=is_heading_suggestion,
        is_rewrite_suggestion=is_rewrite_suggestion,
        foreslagen_text=foreslagen_text,
        explanation=(explanation or "").strip() or None,
        created_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    action = await materialize_word_action(
        session,
        row,
        request=request,
        source_ordinal=source_ordinal,
    )
    if commit:
        await session.commit()
        if action is not None:
            await session.refresh(action)
            await publish_action_created(action)
    return row


def rewrite_suggestion_or_none(
    parsed: WordParagraphComments | WordRewriteSuggestion | None,
) -> WordRewriteSuggestion | None:
    if parsed is None:
        return None
    suggestion = (
        parsed.omskrivning_forslag
        if isinstance(parsed, WordParagraphComments)
        else parsed
    )
    if suggestion is None:
        return None
    if not suggestion.ny_text.strip():
        return None
    if "\n" in suggestion.ny_text.replace("\r\n", "\n").replace("\r", "\n"):
        return None
    return suggestion


async def _review_paragraph(
    *,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    section: WordDocumentSection,
    paragraph: WordDocumentParagraph,
) -> WordParagraphComments:
    """Legacy single-call path. Kept so customer prompt_overrides stay valid."""
    user = render_prompt(
        prompts,
        "expertgranskning.word.paragraph",
        expert_list=_expert_list(slots),
        section_heading=section.heading,
        paragraph_text=paragraph.text,
        style=paragraph.style,
    )
    return await complete_word_structured(
        [{"role": "user", "content": user}],
        WordParagraphComments,
        prompts=prompts,
    )


async def _review_heading(
    *,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    section: WordDocumentSection,
    limiter: WordReviewLimiter,
    review_intent: str = "",
    actor_context: str = "",
) -> WordHeadingAssessment:
    user = render_prompt(
        prompts,
        "expertgranskning.word.heading",
        expert_list=_expert_list(slots),
        heading=section.heading,
        section_text=_section_body(section),
    )
    return await _llm(
        limiter,
        "heading",
        _messages_with_brief(
            identity="",
            brief=review_intent,
            actor_context=actor_context,
            user=user,
        ),
        WordHeadingAssessment,
        prompts,
    )


async def _moderate_batch(
    *,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    brief: str,
    review_context: str,
    section: WordDocumentSection,
    batch: list[WordDocumentParagraph],
    limiter: WordReviewLimiter,
    target_indexes: frozenset[int] | None = None,
    actor_context: str = "",
) -> list[WordReviewQuestion]:
    user = render_prompt(
        prompts,
        "expertgranskning.word.moderator.batch",
        expert_list=_expert_list(slots),
        section_heading=section.heading,
        batch_text=_batch_text(batch),
        review_context=review_context or "(none)",
    )
    parsed = await _llm(
        limiter,
        "moderation",
        _messages_with_brief(
            identity="",
            brief=brief,
            review_context=review_context,
            actor_context=actor_context,
            user=user,
        ),
        WordBatchModeration,
        prompts,
    )
    return accepted_review_questions(
        parsed,
        batch,
        target_indexes=target_indexes,
        panel_slot_ids=frozenset(slot.slot_id for slot in slots),
        timings=limiter.timings,
    )


async def _route_question(
    *,
    prompts: dict[str, str],
    question: WordReviewQuestion,
    review_context: str,
    slots: list[PanelExpertSlot],
    limiter: WordReviewLimiter,
    actor_context: str = "",
) -> tuple[WordReviewQuestion, list[str], int]:
    candidates = panel_experts_for_router(slots)
    user = router_user_prompt(
        prompts=prompts,
        question=question,
        review_context=review_context,
        slots=candidates,
    )
    parsed = await _llm(
        limiter,
        "router",
        _messages_with_brief(
            identity="",
            brief="",
            actor_context=actor_context,
            user=user,
        ),
        WordExpertRoute,
        prompts,
        model=settings.word_review_router_model_override,
        max_tokens=(
            settings.word_review_router_max_tokens
            if settings.word_review_router_model_override
            else None
        ),
    )
    kept, invalid = accepted_router_expert_ids(
        parsed.expert_ids,
        frozenset(slot.slot_id for slot in candidates),
    )
    return apply_router_ids(question, kept), kept, invalid


async def _raise_hand(
    *,
    prompts: dict[str, str],
    slot: PanelExpertSlot,
    brief: str,
    batch: list[WordDocumentParagraph],
    questions: list[WordReviewQuestion],
    limiter: WordReviewLimiter,
    actor_context: str = "",
) -> tuple[PanelExpertSlot, list[WordReviewQuestion]]:
    identity = _expert_identity(prompts, slot)
    user = render_prompt(
        prompts,
        "expertgranskning.word.expert.raise_hand",
        label=slot.label,
        profile=slot.profile or slot.label,
        batch_text=_batch_text(batch),
        questions=_questions_text(questions),
    )
    parsed = await _llm(
        limiter,
        "raise_hand",
        _messages_with_brief(
            identity=identity,
            brief=brief,
            actor_context=actor_context,
            user=user,
        ),
        WordExpertRaiseHand,
        prompts,
    )
    return slot, selected_review_questions(
        parsed.question_ids,
        questions,
        expert_id=slot.slot_id,
    )


def resolve_comment_anchor(
    question: WordReviewQuestion,
    parsed: WordExpertComment | WordExpertObservation,
    *,
    target_indexes: frozenset[int] | None = None,
) -> int | None:
    """Return the one allowed paragraph for this comment, or None to drop it."""
    allowed = list(question.paragraph_indexes)
    if target_indexes is not None:
        allowed = [index for index in allowed if index in target_indexes]
    raw = parsed.anchor_paragraph_index
    if raw is not None:
        if raw in allowed:
            return raw
        logger.info(
            "Dropped Word comment: anchor %s is not in the question indexes",
            raw,
        )
        return None
    primary = question.primary_anchor_paragraph_index
    if primary is not None and primary in allowed:
        return primary
    if len(allowed) == 1:
        return allowed[0]
    logger.info(
        "Dropped Word comment: multi-paragraph question has no valid anchor"
    )
    return None


async def _comment_question(
    *,
    prompts: dict[str, str],
    slot: PanelExpertSlot,
    brief: str,
    section: WordDocumentSection,
    question: WordReviewQuestion,
    paragraphs: list[WordDocumentParagraph],
    limiter: WordReviewLimiter,
    target_indexes: frozenset[int] | None = None,
    actor_context: str = "",
    actor: ActorContext | None = None,
) -> list[WordExpertCommentRow]:
    identity = _expert_identity(prompts, slot)
    user = render_expert_comment_user_prompt(
        prompts,
        slot=slot,
        section=section,
        question=question,
        paragraphs=paragraphs,
    )
    parsed = await _llm(
        limiter,
        "expert_comment",
        _messages_with_brief(
            identity=identity,
            brief=brief,
            actor_context=actor_context,
            user=user,
        ),
        WordExpertComment,
        prompts,
    )
    atoms = expand_expert_comment(parsed)
    if len(atoms) > 1:
        limiter.timings.record_observations_split(len(atoms))
    rows: list[WordExpertCommentRow] = []
    for atom in atoms:
        draft = draft_from_observation(atom, actor)
        rows.append(
            (
                slot,
                question,
                draft,
                resolve_comment_anchor(
                    question,
                    atom,
                    target_indexes=target_indexes,
                ),
            )
        )
    return rows


def _observations_from_comments(
    comments: list[WordExpertCommentRow],
    by_index: dict[int, WordDocumentParagraph],
    *,
    id_prefix: str = "o",
) -> list[WordObservation]:
    observations: list[WordObservation] = []
    for slot, question, draft, anchor in comments:
        if not draft.has_visible_comment() or anchor is None:
            continue
        paragraph = by_index.get(anchor)
        if paragraph is None:
            logger.info(
                "Dropped Word comment: anchor %s is not in the section",
                anchor,
            )
            continue
        observations.append(
            WordObservation(
                observation_id=f"{id_prefix}{len(observations) + 1}",
                expert_id=slot.slot_id,
                expert_label=slot.label,
                question_id=question.id,
                paragraph_index=paragraph.index,
                paragraph_text=paragraph.text,
                list_string=paragraph.list_string,
                kommentar=draft.kommentar,
                issue=draft.issue,
                analysis=draft.analysis,
                source_perspective=draft.source_perspective,
                target_perspective=draft.target_perspective,
                statement_owner=draft.statement_owner,
                recommendation_recipient=draft.recommendation_recipient,
                consequence=draft.consequence,
                recommended_action=draft.recommended_action,
            )
        )
    return observations


async def _comment_convergence(
    *,
    prompts: dict[str, str],
    section: WordDocumentSection,
    batch: list[WordDocumentParagraph],
    observations: list[WordObservation],
    limiter: WordReviewLimiter,
    review_intent: str = "",
    actor_context: str = "",
) -> WordCommentConvergence:
    user = render_comment_convergence_user_prompt(
        prompts,
        section=section,
        batch=batch,
        observations=observations,
    )
    parsed = await _llm(
        limiter,
        "comment_convergence",
        _messages_with_brief(
            identity="",
            brief=review_intent,
            actor_context=actor_context,
            user=user,
        ),
        WordCommentConvergence,
        prompts,
    )
    return finalize_word_comment_convergence(parsed)


async def _consolidate_observations(
    *,
    prompts: dict[str, str],
    section: WordDocumentSection,
    paragraphs: list[WordDocumentParagraph],
    observations: list[WordObservation],
    limiter: WordReviewLimiter,
    review_intent: str = "",
    actor_context: str = "",
) -> tuple[list[WordConsolidatedComment], list[WordObservation]]:
    collapsed = collapse_intra_expert_duplicates(observations)
    if len(collapsed) < 2:
        return [consolidated_from_observation(item) for item in collapsed], collapsed
    written: list[WordConsolidatedComment] = []
    for chunk in chunk_observations_for_convergence(collapsed):
        if len(chunk) < 2:
            written.extend(consolidated_from_observation(item) for item in chunk)
            continue
        referenced = paragraph_indexes_for_observations(chunk)
        parsed = await _comment_convergence(
            prompts=prompts,
            section=section,
            batch=[
                paragraph
                for paragraph in paragraphs
                if paragraph.index in referenced
            ],
            observations=chunk,
            limiter=limiter,
            review_intent=review_intent,
            actor_context=actor_context,
        )
        written.extend(apply_word_comment_convergence(chunk, parsed))
    return written, collapsed


async def _consolidate_comments(
    *,
    prompts: dict[str, str],
    section: WordDocumentSection,
    paragraphs: list[WordDocumentParagraph],
    comments: list[WordExpertCommentRow],
    by_index: dict[int, WordDocumentParagraph],
    limiter: WordReviewLimiter,
    review_intent: str = "",
    actor_context: str = "",
) -> list[WordConsolidatedComment]:
    raw = _observations_from_comments(comments, by_index)
    written, _ = await _consolidate_observations(
        prompts=prompts,
        section=section,
        paragraphs=paragraphs,
        observations=raw,
        limiter=limiter,
        review_intent=review_intent,
        actor_context=actor_context,
    )
    return written


async def _rewrite_convergence(
    *,
    prompts: dict[str, str],
    section: WordDocumentSection,
    paragraph: WordDocumentParagraph,
    comments: list[tuple[str, str]],
    limiter: WordReviewLimiter,
    review_intent: str = "",
    actor_context: str = "",
) -> WordRewriteSuggestion | None:
    comments_text = "\n".join(
        f"- {name}: {text}" for name, text in comments
    )
    user = render_prompt(
        prompts,
        "expertgranskning.word.rewrite_convergence",
        section_heading=section.heading,
        paragraph_text=paragraph.text,
        comments=comments_text,
    )
    parsed = await _llm(
        limiter,
        "rewrite_convergence",
        _messages_with_brief(
            identity="",
            brief=review_intent,
            actor_context=actor_context,
            user=user,
        ),
        WordRewriteSuggestion,
        prompts,
    )
    return rewrite_suggestion_or_none(parsed)


async def _analyze_batch(
    *,
    batch_index: int,
    batch: list[WordDocumentParagraph],
    section: WordDocumentSection,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    brief: str,
    review_intent: str,
    review_context: str,
    router_context: str,
    target: frozenset[int] | None,
    limiter: WordReviewLimiter,
    actor_context: str = "",
    actor: ActorContext | None = None,
) -> WordBatchAnalysis:
    questions = await _moderate_batch(
        prompts=prompts,
        slots=slots,
        brief=brief,
        review_context=review_context,
        section=section,
        batch=batch,
        limiter=limiter,
        target_indexes=target,
        actor_context=actor_context,
    )
    if not questions:
        return WordBatchAnalysis(
            batch_index=batch_index,
            comments=[],
            rewrites=[],
            paragraphs=[],
            paragraph_reviews=len(batch),
        )
    routed_rows = await asyncio.gather(
        *[
            _route_question(
                prompts=prompts,
                question=question,
                review_context=router_context,
                slots=slots,
                limiter=limiter,
                actor_context=actor_context,
            )
            for question in questions
        ]
    )
    assigned: list[WordReviewQuestion] = []
    for question, expert_ids, invalid in routed_rows:
        record_router_outcome(
            limiter.timings,
            expert_ids=expert_ids,
            invalid_ids=invalid,
        )
        assigned.append(question)
    routed, unresolved = routed_and_unresolved_questions(assigned)
    slots_by_id = {slot.slot_id: slot for slot in slots}
    assignments: list[tuple[PanelExpertSlot, WordReviewQuestion]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for question in routed:
        for expert_id in question.recommended_expert_ids:
            slot = slots_by_id.get(expert_id)
            if slot is not None:
                _append_unique_assignment(assignments, seen_pairs, slot, question)
    if unresolved:
        raised = await asyncio.gather(
            *[
                _raise_hand(
                    prompts=prompts,
                    slot=slot,
                    brief=brief,
                    batch=batch,
                    questions=unresolved,
                    limiter=limiter,
                    actor_context=actor_context,
                )
                for slot in slots
            ]
        )
        for slot, selected in raised:
            for question in selected:
                _append_unique_assignment(assignments, seen_pairs, slot, question)
    by_index = {paragraph.index: paragraph for paragraph in batch}
    comment_tasks = [
        _comment_question(
            prompts=prompts,
            slot=slot,
            brief=brief,
            section=section,
            question=question,
            paragraphs=[
                by_index[index]
                for index in question.paragraph_indexes
                if index in by_index
            ],
            limiter=limiter,
            target_indexes=target,
            actor_context=actor_context,
            actor=actor,
        )
        for slot, question in assignments
    ]
    nested = await asyncio.gather(*comment_tasks) if comment_tasks else []
    comments = [row for rows in nested for row in rows]

    comments_by_index: dict[int, list[tuple[str, str]]] = {}
    section_comments: list[WordExpertCommentRow] = []
    for slot, question, draft, anchor in comments:
        if not draft.has_visible_comment():
            continue
        prefixed = WordReviewQuestion(
            id=f"b{batch_index}:{question.id}",
            paragraph_indexes=question.paragraph_indexes,
            question=question.question,
            why_it_matters=question.why_it_matters,
            primary_anchor_paragraph_index=question.primary_anchor_paragraph_index,
            recommended_expert_ids=question.recommended_expert_ids,
        )
        section_comments.append((slot, prefixed, draft, anchor))
        # One resolved anchor per comment. Spreading across the question
        # scope would qualify unrelated paragraphs for rewrite.
        if anchor is None:
            continue
        paragraph = by_index.get(anchor)
        if paragraph is None:
            continue
        comments_by_index.setdefault(paragraph.index, []).append(
            (slot.label, draft.kommentar)
        )

    rewrite_targets = [
        paragraph
        for paragraph in batch
        if len({name for name, _ in comments_by_index.get(paragraph.index, [])}) >= 2
    ]
    suggestions = (
        await asyncio.gather(
            *[
                _rewrite_convergence(
                    prompts=prompts,
                    section=section,
                    paragraph=paragraph,
                    comments=comments_by_index[paragraph.index],
                    limiter=limiter,
                    review_intent=review_intent,
                    actor_context=actor_context,
                )
                for paragraph in rewrite_targets
            ]
        )
        if rewrite_targets
        else []
    )
    rewrites = [
        (paragraph, suggestion)
        for paragraph, suggestion in zip(rewrite_targets, suggestions, strict=True)
        if suggestion is not None
    ]
    return WordBatchAnalysis(
        batch_index=batch_index,
        comments=section_comments,
        rewrites=rewrites,
        paragraphs=batch,
        paragraph_reviews=len(batch),
    )


def publication_unit_total(
    sections: Sequence[WordDocumentSection],
    target: frozenset[int] | None,
) -> int:
    return sum(
        len(_batches_for_target(section, target))
        + (1 if heading_in_scope(section, target) else 0)
        for section in sections
    )


def _observations_from_batch(analysis: WordBatchAnalysis) -> list[WordObservation]:
    by_index = {paragraph.index: paragraph for paragraph in analysis.paragraphs}
    return _observations_from_comments(
        analysis.comments,
        by_index,
        id_prefix=f"b{analysis.batch_index}o",
    )


async def _analyze_section(
    *,
    section_index: int,
    section: WordDocumentSection,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    brief: str,
    review_intent: str,
    review_context: str,
    router_context: str,
    target: frozenset[int] | None,
    limiter: WordReviewLimiter,
    emit: Callable[[WordPublicationUnit], Awaitable[None]],
    actor_context: str = "",
    actor: ActorContext | None = None,
) -> WordSectionStats:
    batches = _batches_for_target(section, target)
    review_heading = heading_in_scope(section, target)
    last_index = len(batches) - 1
    batch_results: dict[int, WordBatchAnalysis] = {}
    ingested: set[int] = set()
    comment_finalized: set[int] = set()
    published_rewrite_batches: set[int] = set()
    pending_obs: list[WordObservation] = []
    section_by_index: dict[int, WordDocumentParagraph] = {}

    async def emit_early_rewrites(analysis: WordBatchAnalysis) -> None:
        if analysis.batch_index == last_index:
            return
        if not analysis.rewrites or analysis.batch_index in published_rewrite_batches:
            return
        published_rewrite_batches.add(analysis.batch_index)
        await emit(
            WordPublicationUnit(
                section_index=section_index,
                rewrites=analysis.rewrites,
                completes_unit=False,
            )
        )

    async def finalize_ready_comment_windows(
        *, allow_missing_lookahead: bool = False
    ) -> None:
        nonlocal pending_obs
        while True:
            nxt = next(
                (
                    index
                    for index in range(len(batches))
                    if index not in comment_finalized
                ),
                None,
            )
            if nxt is None or nxt not in batch_results:
                return
            is_last = nxt == last_index
            lookahead_idx = None if is_last else nxt + 1
            if lookahead_idx is not None and lookahead_idx not in batch_results:
                if not allow_missing_lookahead:
                    return
                lookahead_idx = None
            if nxt not in ingested:
                pending_obs.extend(_observations_from_batch(batch_results[nxt]))
                ingested.add(nxt)
            if lookahead_idx is not None and lookahead_idx not in ingested:
                pending_obs.extend(
                    _observations_from_batch(batch_results[lookahead_idx])
                )
                ingested.add(lookahead_idx)
            comments, collapsed = await _consolidate_observations(
                prompts=prompts,
                section=section,
                paragraphs=sorted(
                    section_by_index.values(), key=lambda item: item.index
                ),
                observations=pending_obs,
                limiter=limiter,
                review_intent=review_intent,
                actor_context=actor_context,
            )
            if target is not None:
                comments = [
                    item for item in comments if item.paragraph_index in target
                ]
            current = batch_results[nxt]
            owned = batch_owned_indexes(current.paragraphs)
            if is_last:
                to_publish = comments
                pending_obs = []
            else:
                to_publish, consumed = partition_owned_comments(comments, owned)
                pending_obs = leftover_observations(collapsed, consumed)
            rewrites: list[tuple[WordDocumentParagraph, WordRewriteSuggestion]] = []
            if nxt not in published_rewrite_batches:
                rewrites = current.rewrites
                published_rewrite_batches.add(nxt)
            await emit(
                WordPublicationUnit(
                    section_index=section_index,
                    comments=to_publish,
                    rewrites=rewrites,
                    completes_unit=True,
                )
            )
            comment_finalized.add(nxt)

    tasks: dict[asyncio.Task, str] = {}
    for batch_index, batch in enumerate(batches):
        task = asyncio.create_task(
            _analyze_batch(
                batch_index=batch_index,
                batch=batch,
                section=section,
                prompts=prompts,
                slots=slots,
                brief=brief,
                review_intent=review_intent,
                review_context=review_context,
                router_context=router_context,
                target=target,
                limiter=limiter,
                actor_context=actor_context,
                actor=actor,
            )
        )
        tasks[task] = f"batch:{batch_index}"
    if review_heading:
        heading_task = asyncio.create_task(
            _review_heading(
                prompts=prompts,
                slots=slots,
                section=section,
                limiter=limiter,
                review_intent=review_intent,
                actor_context=actor_context,
            )
        )
        tasks[heading_task] = "heading"
    pending_tasks = set(tasks)
    paragraph_reviews = 0

    async def record_completed_task(task: asyncio.Task) -> None:
        nonlocal paragraph_reviews
        kind = tasks[task]
        if kind == "heading":
            heading = task.result()
            await emit(
                WordPublicationUnit(
                    section_index=section_index,
                    heading=heading,
                    completes_unit=True,
                )
            )
            return
        analysis = task.result()
        paragraph_reviews += analysis.paragraph_reviews
        batch_results[analysis.batch_index] = analysis
        for paragraph in analysis.paragraphs:
            section_by_index[paragraph.index] = paragraph
        await emit_early_rewrites(analysis)
        await finalize_ready_comment_windows()

    async def flush_partial_comment_windows() -> None:
        while True:
            before = len(comment_finalized)
            await finalize_ready_comment_windows(allow_missing_lookahead=True)
            if len(comment_finalized) == before:
                break

    try:
        while pending_tasks:
            done, pending_tasks = await asyncio.wait(
                pending_tasks, return_when=asyncio.FIRST_COMPLETED
            )
            failures: list[BaseException] = []
            for task in done:
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None:
                    failures.append(exc)
                    continue
                await record_completed_task(task)
            if failures:
                while pending_tasks:
                    done, pending_tasks = await asyncio.wait(
                        pending_tasks, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in done:
                        if task.cancelled():
                            continue
                        if task.exception() is not None:
                            continue
                        await record_completed_task(task)
                await flush_partial_comment_windows()
                raise failures[0]
    finally:
        for task in pending_tasks:
            if not task.done():
                task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

    return WordSectionStats(
        section_index=section_index,
        paragraph_reviews=paragraph_reviews,
        heading_reviews=1 if review_heading else 0,
    )


async def _persist_publication_unit(
    session: AsyncSession,
    job: Job,
    payload: ExpertgranskningWordJobRequest,
    unit: WordPublicationUnit,
    timings: WordReviewTimings,
    source_ordinal: int,
) -> tuple[int, int]:
    pending: list[ExpertgranskningResult] = []
    ordinal = source_ordinal
    for item in unit.comments:
        if not item.should_materialize:
            continue
        pending.append(
            await _write_result(
                session,
                job_id=job.id,
                customer_id=payload.customer_id,
                section_index=unit.section_index,
                paragraph_index=item.paragraph_index,
                expert_id=item.expert_id,
                expert_namn=item.expert_namn,
                kommentar=item.kommentar,
                is_heading_suggestion=False,
                explanation=item.explanation or None,
                request=job.request,
                source_ordinal=ordinal,
                commit=False,
            )
        )
        timings.record_comment_generated(
            over_soft_length=comment_exceeds_soft_cap(item.kommentar)
        )
        ordinal += 1
    for paragraph, suggestion in unit.rewrites:
        pending.append(
            await _write_result(
                session,
                job_id=job.id,
                customer_id=payload.customer_id,
                section_index=unit.section_index,
                paragraph_index=paragraph.index,
                expert_id="",
                expert_namn="",
                kommentar=suggestion.motivering.strip(),
                is_heading_suggestion=False,
                is_rewrite_suggestion=True,
                foreslagen_text=suggestion.ny_text.strip(),
                request=job.request,
                source_ordinal=ordinal,
                commit=False,
            )
        )
        ordinal += 1
    if unit.heading is not None:
        suggestion = (unit.heading.forslag or "").strip()
        if suggestion:
            pending.append(
                await _write_result(
                    session,
                    job_id=job.id,
                    customer_id=payload.customer_id,
                    section_index=unit.section_index,
                    paragraph_index=payload.sections[
                        unit.section_index
                    ].heading_paragraph_index,
                    expert_id="",
                    expert_namn="",
                    kommentar=suggestion,
                    is_heading_suggestion=True,
                    request=job.request,
                    source_ordinal=ordinal,
                    commit=False,
                )
            )
            ordinal += 1

    if not pending:
        return 0, 0
    await session.commit()
    source_ids = {row.id for row in pending}
    actions = (
        await session.execute(
            select(WordAction).where(
                WordAction.job_id == job.id,
                WordAction.source_id.in_(source_ids),
            )
        )
    ).scalars().all()
    by_source = {action.source_id: action for action in actions}
    ordered = [by_source[row.id] for row in pending if row.id in by_source]
    published = await publish_created_actions(ordered, timings)
    return len(pending), published


async def publish_created_actions(
    actions: list[WordAction],
    timings: WordReviewTimings,
) -> int:
    """Publish actions in persist order and stamp first-action as soon as one lands."""
    published = 0
    for action in actions:
        await publish_action_created(action)
        timings.mark_first_action()
        published += 1
    return published


def log_word_review_call_summary(
    job_id: str,
    snapshot: dict[str, object],
    *,
    outcome: str,
) -> None:
    """Emit one timing + LLM-count summary. Snapshot has counts only."""
    logger.info(
        "Word review timings job_id=%s outcome=%s provider=%s model=%s "
        "reasoning_effort=%s prompt_tokens=%s completion_tokens=%s llm_usage=%s "
        "total_ms=%s time_to_first_action_ms=%s publication_units_completed=%s "
        "actions_published_before_completion=%s moderation_ms=%s "
        "router_ms=%s raise_hand_ms=%s expert_comment_ms=%s "
        "rewrite_convergence_ms=%s comment_convergence_ms=%s heading_ms=%s "
        "actor_context_ms=%s llm_call_count=%s max_observed_llm_concurrency=%s",
        job_id,
        outcome,
        snapshot["llm_provider"],
        snapshot["llm_model"],
        snapshot["llm_reasoning_effort"],
        snapshot["prompt_tokens"],
        snapshot["completion_tokens"],
        format_llm_usage_log(snapshot["llm_usage"]),
        snapshot["total_ms"],
        snapshot["time_to_first_action_ms"],
        snapshot["publication_units_completed"],
        snapshot["actions_published_before_completion"],
        snapshot["moderation_ms"],
        snapshot["router_ms"],
        snapshot["raise_hand_ms"],
        snapshot["expert_comment_ms"],
        snapshot["rewrite_convergence_ms"],
        snapshot["comment_convergence_ms"],
        snapshot["heading_ms"],
        snapshot["actor_context_ms"],
        snapshot["llm_call_count"],
        snapshot["max_observed_llm_concurrency"],
    )
    logger.info(
        "Word review LLM calls job_id=%s outcome=%s total=%s moderation=%s "
        "router=%s raise_hand=%s expert_comment=%s comment_convergence=%s "
        "rewrite_convergence=%s heading=%s structured_retries=%s "
        "actor_context_resolved=%s actor_context_resolver_calls=%s "
        "direct_routed_questions=%s raise_hand_questions=%s "
        "router_assignments=%s router_fallback_count=%s invalid_router_ids=%s "
        "questions_dropped_invalid_anchor=%s publication_units_completed=%s "
        "actions_published_before_completion=%s comments_generated=%s "
        "comments_over_soft_length=%s observations_split=%s "
        "max_observed_llm_concurrency=%s",
        job_id,
        outcome,
        snapshot["llm_call_count"],
        snapshot["moderation_calls"],
        snapshot["router_calls"],
        snapshot["raise_hand_calls"],
        snapshot["expert_comment_calls"],
        snapshot["comment_convergence_calls"],
        snapshot["rewrite_convergence_calls"],
        snapshot["heading_calls"],
        snapshot["structured_retry_count"],
        snapshot["actor_context_resolved"],
        snapshot["actor_context_resolver_calls"],
        snapshot["direct_routed_questions"],
        snapshot["raise_hand_questions"],
        snapshot["router_assignments"],
        snapshot["router_fallback_count"],
        snapshot["invalid_router_ids"],
        snapshot["questions_dropped_invalid_anchor"],
        snapshot["publication_units_completed"],
        snapshot["actions_published_before_completion"],
        snapshot["comments_generated"],
        snapshot["comments_over_soft_length"],
        snapshot["observations_split"],
        snapshot["max_observed_llm_concurrency"],
    )


async def run_word_paragraph_review(
    session: AsyncSession,
    job: Job,
    payload: ExpertgranskningWordJobRequest,
    prompts: dict[str, str],
) -> dict[str, int | None]:
    require_review_panel_task(payload.task)
    target = selection_target_indexes(payload.task)
    slots = await load_expert_slots_from_population(session, payload.panel_id)
    review_context = compose_intent_prefix(
        prompts,
        interview=payload.intent_interview,
        answers=payload.intent_answers,
        review_intent=payload.review_intent,
    )
    review_context_concise = compose_intent_prefix(
        prompts,
        interview=payload.intent_interview,
        answers=payload.intent_answers,
        review_intent=payload.review_intent,
        concise=True,
    )
    brief = compose_expert_review_context(
        prompts,
        brief=_document_brief(payload),
        interview=payload.intent_interview,
        answers=payload.intent_answers,
        review_intent=payload.review_intent,
    )
    review_intent = review_context
    memory = get_expert_memory()
    await memory.add_intent(
        customer_id=payload.customer_id,
        expert_ids=[slot.slot_id for slot in slots],
        text=review_context,
        job_id=job.id,
    )
    timings = WordReviewTimings()
    limiter = WordReviewLimiter(settings.word_review_max_concurrency, timings)
    sections_total = len(payload.sections)
    units_total = publication_unit_total(payload.sections, target)
    queue: asyncio.Queue[
        WordPublicationUnit | WordSectionDone | WordSectionFailed
    ] = asyncio.Queue()
    actor_context = ""
    section_tasks: list[asyncio.Task] = []
    paragraph_reviews = 0
    heading_reviews = 0
    result_count = 0
    actions_created = 0
    sections_completed = 0
    units_completed = 0
    source_ordinal = 0
    logged_summary = False
    failed: BaseException | None = None
    pending_sections = 0

    async def run_section(
        section_index: int, section: WordDocumentSection
    ) -> None:
        try:
            stats = await _analyze_section(
                section_index=section_index,
                section=section,
                prompts=prompts,
                slots=slots,
                brief=brief,
                review_intent=review_intent,
                review_context=review_context,
                router_context=review_context_concise,
                target=target,
                limiter=limiter,
                emit=queue.put,
                actor_context=actor_context,
                actor=actor,
            )
            await queue.put(WordSectionDone(stats))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await queue.put(WordSectionFailed(section_index, exc))

    async def persist_unit(unit: WordPublicationUnit) -> None:
        nonlocal result_count, actions_created, source_ordinal, units_completed
        written, published = await _persist_publication_unit(
            session, job, payload, unit, timings, source_ordinal
        )
        source_ordinal += written
        result_count += written
        actions_created += published
        if unit.completes_unit:
            units_completed += 1
            timings.record_publication_progress(
                units_completed=units_completed,
                units_total=units_total,
                actions_created=actions_created,
            )
        await publish_review_progress(
            job.id,
            sections_completed=sections_completed,
            sections_total=sections_total,
            actions_created=actions_created,
            units_completed=units_completed,
            units_total=units_total,
        )

    async def drain_queue() -> None:
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if isinstance(item, WordPublicationUnit):
                await persist_unit(item)

    try:
        actor = await resolve_actor_context(
            prompts=prompts,
            interview=payload.intent_interview,
            answers=payload.intent_answers,
            review_intent=payload.review_intent,
            limiter=limiter,
            locale=payload.locale,
        )
        actor_context = compose_review_system_context(
            prompts=prompts,
            actor_context=render_actor_context(actor, prompts),
        )
        section_tasks = [
            asyncio.create_task(run_section(section_index, section))
            for section_index, section in enumerate(payload.sections)
        ]
        pending_sections = len(section_tasks)
        while pending_sections:
            item = await queue.get()
            if isinstance(item, WordPublicationUnit):
                await persist_unit(item)
                continue
            if isinstance(item, WordSectionDone):
                pending_sections -= 1
                paragraph_reviews += item.stats.paragraph_reviews
                heading_reviews += item.stats.heading_reviews
                sections_completed += 1
                await publish_review_progress(
                    job.id,
                    sections_completed=sections_completed,
                    sections_total=sections_total,
                    actions_created=actions_created,
                    units_completed=units_completed,
                    units_total=units_total,
                )
                continue
            pending_sections -= 1
            failed = item.error
            for task in section_tasks:
                if not task.done():
                    task.cancel()
            break
        await asyncio.gather(*section_tasks, return_exceptions=True)
        await drain_queue()
        if failed is not None:
            raise failed
        snapshot = timings.snapshot()
        result_rows = (
            await session.execute(
                select(ExpertgranskningResult)
                .where(ExpertgranskningResult.job_id == job.id)
                .order_by(ExpertgranskningResult.id.asc())
            )
        ).scalars().all()
        findings_by_expert: dict[str, list[str]] = {}
        for row in result_rows:
            if not row.expert_id.strip():
                continue
            finding = row.kommentar.strip()
            if row.explanation and row.explanation.strip():
                finding = f"{finding}\nBakgrund: {row.explanation.strip()}"
            findings_by_expert.setdefault(row.expert_id, []).append(finding)
        if payload.doc_id:
            for expert_id, findings in findings_by_expert.items():
                await memory.replace_word_findings(
                    customer_id=payload.customer_id,
                    expert_id=expert_id,
                    doc_id=payload.doc_id,
                    job_id=job.id,
                    findings=findings,
                )
        elif findings_by_expert:
            logger.warning(
                "Skipping word_findings memory for job %s: request has no doc_id",
                job.id,
            )
        logged_summary = True
        log_word_review_call_summary(job.id, snapshot, outcome="success")
        return {
            "paragraph_reviews": paragraph_reviews,
            "heading_reviews": heading_reviews,
            "result_count": result_count,
            **snapshot,
        }
    except BaseException:
        for task in section_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*section_tasks, return_exceptions=True)
        await drain_queue()
        raise
    finally:
        if not logged_summary:
            log_word_review_call_summary(
                job.id, timings.snapshot(), outcome="failed"
            )


async def word_paragraph_review(
    session: AsyncSession,
    panel: PanelSession,
    prompts: dict[str, str],
) -> PanelSession:
    raise ValueError(
        "word_paragraph_review körs via jobbkind expertgranskning_word_review, "
        "inte via panel-session"
    )


async def run_word_paragraph_review_for_job(job_id: str) -> None:
    # Circular: jobs.py owns the worker helpers and imports this runner.
    from app.services.jobs import _succeed, job_session_factory

    factory = job_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        payload = ExpertgranskningWordJobRequest.model_validate(job.request or {})
        require_review_panel_task(payload.task)
        prompts = await require_active_prompts(
            session,
            customer_id=payload.customer_id,
            module="expertgranskning",
            language=payload.locale,
        )
        stats = await run_word_paragraph_review(session, job, payload, prompts)
        await _succeed(
            session,
            job_id,
            {
                "method": "word_paragraph_review",
                "panel_id": payload.panel_id,
                "doc_id": payload.doc_id,
                **stats,
            },
        )
        await publish_expertgranskning_finished(job_id, status="succeeded", stats=stats)
