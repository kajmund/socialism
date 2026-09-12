"""word_paragraph_review — moderator-led batched Word review.

A moderator filters each batch and writes review questions. Experts raise
a hand per question and comment only on questions they opted into. After
expert replies, overlapping observations are consolidated at section
scope before Word comments are written, so nearby duplicates can collapse
across batch boundaries. Rewrite suggestions remain a separate step when
at least two experts comment on the same paragraph.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExpertgranskningResult, Job, PanelSession, WordAction
from app.serializers import utcnow
from app.services.expertgranskning.comment_convergence import (
    WordConsolidatedComment,
    WordObservation,
    apply_word_comment_convergence,
    collapse_intra_expert_duplicates,
    consolidated_from_observation,
    format_observations_for_prompt,
)
from app.services.expertgranskning.schemas import (
    ExpertgranskningWordJobRequest,
    WordBatchModeration,
    WordCommentConvergence,
    WordDocumentParagraph,
    WordDocumentSection,
    WordExpertComment,
    WordExpertRaiseHand,
    WordHeadingAssessment,
    WordParagraphComments,
    WordReviewQuestion,
    WordRewriteSuggestion,
)
from app.services.expertgranskning.watch import (
    publish_action_created,
    publish_expertgranskning_finished,
)
from app.services.expertgranskning.word_structured import complete_word_structured
from app.services.word.materialize import materialize_word_action
from app.services.panel.expert_slots import load_expert_slots_from_population
from app.services.panel.review_intent import (
    compose_brief_with_review_intent,
    render_review_intent_message,
)
from app.services.panel.schemas import PanelExpertSlot
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts

logger = logging.getLogger(__name__)

_HEADING_1_TO_3 = re.compile(
    r"^(heading|rubrik)\s*[123]$",
    re.IGNORECASE,
)

WORD_BATCH_MAX_SIZE = 4

# Output contract. Not part of the editable customer prompt.
_WORD_COMMENT_ANCHOR_SUFFIX = (
    "Allowed anchors: {indexes}. "
    "Return exactly one anchor_paragraph_index from this set."
)


def word_comment_anchor_suffix(paragraph_indexes: Sequence[int]) -> str:
    indexes = ", ".join(str(index) for index in paragraph_indexes)
    return _WORD_COMMENT_ANCHOR_SUFFIX.format(indexes=indexes)


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


def _messages_with_brief(*, identity: str, brief: str, user: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if identity.strip():
        messages.append({"role": "system", "content": identity})
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


def accepted_review_questions(
    parsed: WordBatchModeration,
    batch: list[WordDocumentParagraph],
) -> list[WordReviewQuestion]:
    """Keep in-batch questions; drop a batch that does not need review."""
    if not parsed.needs_review:
        return []
    allowed = {paragraph.index for paragraph in batch}
    kept: list[WordReviewQuestion] = []
    seen_ids: set[str] = set()
    for question in parsed.questions:
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
        seen_ids.add(question_id)
        kept.append(
            WordReviewQuestion(
                id=question_id,
                paragraph_indexes=indexes,
                question=question.question.strip(),
                why_it_matters=question.why_it_matters.strip(),
            )
        )
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
    request: dict | None = None,
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
        created_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    action = await materialize_word_action(session, row, request=request)
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
    review_intent: str = "",
) -> WordHeadingAssessment:
    user = render_prompt(
        prompts,
        "expertgranskning.word.heading",
        expert_list=_expert_list(slots),
        heading=section.heading,
        section_text=_section_body(section),
    )
    return await complete_word_structured(
        _messages_with_brief(identity="", brief=review_intent, user=user),
        WordHeadingAssessment,
        prompts=prompts,
    )


async def _moderate_batch(
    *,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    brief: str,
    section: WordDocumentSection,
    batch: list[WordDocumentParagraph],
) -> list[WordReviewQuestion]:
    user = render_prompt(
        prompts,
        "expertgranskning.word.moderator.batch",
        expert_list=_expert_list(slots),
        section_heading=section.heading,
        batch_text=_batch_text(batch),
    )
    parsed = await complete_word_structured(
        _messages_with_brief(identity="", brief=brief, user=user),
        WordBatchModeration,
        prompts=prompts,
    )
    return accepted_review_questions(parsed, batch)


async def _raise_hand(
    *,
    prompts: dict[str, str],
    slot: PanelExpertSlot,
    brief: str,
    batch: list[WordDocumentParagraph],
    questions: list[WordReviewQuestion],
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
    parsed = await complete_word_structured(
        _messages_with_brief(identity=identity, brief=brief, user=user),
        WordExpertRaiseHand,
        prompts=prompts,
    )
    return slot, selected_review_questions(
        parsed.question_ids,
        questions,
        expert_id=slot.slot_id,
    )


def resolve_comment_anchor(
    question: WordReviewQuestion,
    parsed: WordExpertComment,
) -> int | None:
    """Return the one allowed paragraph for this comment, or None to drop it."""
    allowed = question.paragraph_indexes
    raw = parsed.anchor_paragraph_index
    if raw is not None:
        if raw in allowed:
            return raw
        logger.info(
            "Dropped Word comment: anchor %s is not in the question indexes",
            raw,
        )
        return None
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
) -> tuple[PanelExpertSlot, WordReviewQuestion, str, int | None]:
    identity = _expert_identity(prompts, slot)
    user = render_expert_comment_user_prompt(
        prompts,
        slot=slot,
        section=section,
        question=question,
        paragraphs=paragraphs,
    )
    parsed = await complete_word_structured(
        _messages_with_brief(identity=identity, brief=brief, user=user),
        WordExpertComment,
        prompts=prompts,
    )
    return slot, question, parsed.kommentar.strip(), resolve_comment_anchor(question, parsed)


def _observations_from_comments(
    comments: list[tuple[PanelExpertSlot, WordReviewQuestion, str, int | None]],
    by_index: dict[int, WordDocumentParagraph],
) -> list[WordObservation]:
    observations: list[WordObservation] = []
    for slot, question, text, anchor in comments:
        if not text or anchor is None:
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
                observation_id=f"o{len(observations) + 1}",
                expert_id=slot.slot_id,
                expert_label=slot.label,
                question_id=question.id,
                paragraph_index=paragraph.index,
                paragraph_text=paragraph.text,
                list_string=paragraph.list_string,
                kommentar=text,
            )
        )
    return observations


async def _comment_convergence(
    *,
    prompts: dict[str, str],
    section: WordDocumentSection,
    batch: list[WordDocumentParagraph],
    observations: list[WordObservation],
    review_intent: str = "",
) -> WordCommentConvergence:
    user = render_prompt(
        prompts,
        "expertgranskning.word.comment_convergence",
        section_heading=section.heading,
        batch_text=_batch_text(batch),
        observations=format_observations_for_prompt(observations),
    )
    return await complete_word_structured(
        _messages_with_brief(identity="", brief=review_intent, user=user),
        WordCommentConvergence,
        prompts=prompts,
    )


async def _consolidate_comments(
    *,
    prompts: dict[str, str],
    section: WordDocumentSection,
    paragraphs: list[WordDocumentParagraph],
    comments: list[tuple[PanelExpertSlot, WordReviewQuestion, str, int | None]],
    by_index: dict[int, WordDocumentParagraph],
    review_intent: str = "",
) -> list[WordConsolidatedComment]:
    raw = _observations_from_comments(comments, by_index)
    collapsed = collapse_intra_expert_duplicates(raw)
    if len(collapsed) < 2:
        return [consolidated_from_observation(item) for item in collapsed]
    parsed = await _comment_convergence(
        prompts=prompts,
        section=section,
        batch=paragraphs,
        observations=collapsed,
        review_intent=review_intent,
    )
    return apply_word_comment_convergence(collapsed, parsed)


async def _rewrite_convergence(
    *,
    prompts: dict[str, str],
    section: WordDocumentSection,
    paragraph: WordDocumentParagraph,
    comments: list[tuple[str, str]],
    review_intent: str = "",
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
    parsed = await complete_word_structured(
        _messages_with_brief(identity="", brief=review_intent, user=user),
        WordRewriteSuggestion,
        prompts=prompts,
    )
    return rewrite_suggestion_or_none(parsed)


async def run_word_paragraph_review(
    session: AsyncSession,
    job: Job,
    payload: ExpertgranskningWordJobRequest,
    prompts: dict[str, str],
) -> dict[str, int]:
    slots = await load_expert_slots_from_population(session, payload.panel_id)
    brief = compose_brief_with_review_intent(
        prompts,
        brief=_document_brief(payload),
        review_intent=payload.review_intent,
    )
    review_intent = render_review_intent_message(prompts, payload.review_intent)
    paragraph_reviews = 0
    heading_reviews = 0
    result_count = 0

    for section_index, section in enumerate(payload.sections):
        section_comments: list[
            tuple[PanelExpertSlot, WordReviewQuestion, str, int | None]
        ] = []
        section_by_index: dict[int, WordDocumentParagraph] = {}
        section_rewrites: list[tuple[WordDocumentParagraph, WordRewriteSuggestion]] = []

        for batch_index, batch in enumerate(build_batches(section)):
            paragraph_reviews += len(batch)
            questions = await _moderate_batch(
                prompts=prompts,
                slots=slots,
                brief=brief,
                section=section,
                batch=batch,
            )
            if not questions:
                continue
            raised = await asyncio.gather(
                *[
                    _raise_hand(
                        prompts=prompts,
                        slot=slot,
                        brief=brief,
                        batch=batch,
                        questions=questions,
                    )
                    for slot in slots
                ]
            )
            by_index = {paragraph.index: paragraph for paragraph in batch}
            section_by_index.update(by_index)
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
                )
                for slot, selected in raised
                for question in selected
            ]
            comments = (
                await asyncio.gather(*comment_tasks) if comment_tasks else []
            )

            comments_by_index: dict[int, list[tuple[str, str]]] = {}
            for slot, question, text, anchor in comments:
                if not text:
                    continue
                prefixed = WordReviewQuestion(
                    id=f"b{batch_index}:{question.id}",
                    paragraph_indexes=question.paragraph_indexes,
                    question=question.question,
                    why_it_matters=question.why_it_matters,
                )
                section_comments.append((slot, prefixed, text, anchor))
                for index in question.paragraph_indexes:
                    paragraph = by_index.get(index)
                    if paragraph is None:
                        continue
                    comments_by_index.setdefault(paragraph.index, []).append(
                        (slot.label, text)
                    )

            rewrite_targets = [
                paragraph
                for paragraph in batch
                if len({name for name, _ in comments_by_index.get(paragraph.index, [])})
                >= 2
            ]
            suggestions = (
                await asyncio.gather(
                    *[
                        _rewrite_convergence(
                            prompts=prompts,
                            section=section,
                            paragraph=paragraph,
                            comments=comments_by_index[paragraph.index],
                            review_intent=review_intent,
                        )
                        for paragraph in rewrite_targets
                    ]
                )
                if rewrite_targets
                else []
            )
            for paragraph, suggestion in zip(rewrite_targets, suggestions, strict=True):
                if suggestion is None:
                    continue
                section_rewrites.append((paragraph, suggestion))

        written = await _consolidate_comments(
            prompts=prompts,
            section=section,
            paragraphs=sorted(section_by_index.values(), key=lambda item: item.index),
            comments=section_comments,
            by_index=section_by_index,
            review_intent=review_intent,
        )

        pending: list[ExpertgranskningResult] = []
        for item in written:
            pending.append(
                await _write_result(
                    session,
                    job_id=job.id,
                    customer_id=payload.customer_id,
                    section_index=section_index,
                    paragraph_index=item.paragraph_index,
                    expert_id=item.expert_id,
                    expert_namn=item.expert_namn,
                    kommentar=item.kommentar,
                    is_heading_suggestion=False,
                    request=job.request,
                    commit=False,
                )
            )
            result_count += 1

        for paragraph, suggestion in section_rewrites:
            pending.append(
                await _write_result(
                    session,
                    job_id=job.id,
                    customer_id=payload.customer_id,
                    section_index=section_index,
                    paragraph_index=paragraph.index,
                    expert_id="",
                    expert_namn="",
                    kommentar=suggestion.motivering.strip(),
                    is_heading_suggestion=False,
                    is_rewrite_suggestion=True,
                    foreslagen_text=suggestion.ny_text.strip(),
                    request=job.request,
                    commit=False,
                )
            )
            result_count += 1

        if pending:
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
            for row in pending:
                action = by_source.get(row.id)
                if action is None:
                    continue
                await publish_action_created(action)

        heading = await _review_heading(
            prompts=prompts,
            slots=slots,
            section=section,
            review_intent=review_intent,
        )
        heading_reviews += 1
        suggestion = (heading.forslag or "").strip()
        if suggestion:
            await _write_result(
                session,
                job_id=job.id,
                customer_id=payload.customer_id,
                section_index=section_index,
                paragraph_index=section.heading_paragraph_index,
                expert_id="",
                expert_namn="",
                kommentar=suggestion,
                is_heading_suggestion=True,
                request=job.request,
            )
            result_count += 1

    return {
        "paragraph_reviews": paragraph_reviews,
        "heading_reviews": heading_reviews,
        "result_count": result_count,
    }


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
