"""word_paragraph_review — moderator-led batched Word review.

A moderator filters each batch and writes review questions. Experts raise
a hand per question and comment only on questions they opted into. Rewrite
suggestions are a separate step when at least two experts comment on the
same paragraph.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExpertgranskningResult, Job, PanelSession
from app.llm import complete_structured
from app.serializers import utcnow
from app.services.expertgranskning.schemas import (
    ExpertgranskningWordJobRequest,
    WordBatchModeration,
    WordDocumentParagraph,
    WordDocumentSection,
    WordExpertComment,
    WordExpertRaiseHand,
    WordHeadingAssessment,
    WordParagraphComments,
    WordRewriteSuggestion,
    WordReviewQuestion,
)
from app.services.expertgranskning.watch import (
    publish_expertgranskning_finished,
    publish_result_created,
)
from app.services.panel.expert_slots import load_expert_slots_from_population
from app.services.panel.schemas import PanelExpertSlot
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts

logger = logging.getLogger(__name__)

_HEADING_1_TO_3 = re.compile(
    r"^(heading|rubrik)\s*[123]$",
    re.IGNORECASE,
)

WORD_BATCH_MAX_SIZE = 4


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
        comment_id=None,
        status="pending",
        created_at=utcnow(),
    )
    session.add(row)
    if commit:
        await session.commit()
        await session.refresh(row)
        await publish_result_created(row, request=request)
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
    return await complete_structured(
        [{"role": "user", "content": user}],
        WordParagraphComments,
    )


async def _review_heading(
    *,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    section: WordDocumentSection,
) -> WordHeadingAssessment:
    user = render_prompt(
        prompts,
        "expertgranskning.word.heading",
        expert_list=_expert_list(slots),
        heading=section.heading,
        section_text=_section_body(section),
    )
    return await complete_structured(
        [{"role": "user", "content": user}],
        WordHeadingAssessment,
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
    parsed = await complete_structured(
        _messages_with_brief(identity="", brief=brief, user=user),
        WordBatchModeration,
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
    parsed = await complete_structured(
        _messages_with_brief(identity=identity, brief=brief, user=user),
        WordExpertRaiseHand,
    )
    return slot, selected_review_questions(
        parsed.question_ids,
        questions,
        expert_id=slot.slot_id,
    )


async def _comment_question(
    *,
    prompts: dict[str, str],
    slot: PanelExpertSlot,
    brief: str,
    section: WordDocumentSection,
    question: WordReviewQuestion,
    paragraphs: list[WordDocumentParagraph],
) -> tuple[PanelExpertSlot, WordReviewQuestion, str]:
    identity = _expert_identity(prompts, slot)
    user = render_prompt(
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
    )
    parsed = await complete_structured(
        _messages_with_brief(identity=identity, brief=brief, user=user),
        WordExpertComment,
    )
    return slot, question, parsed.kommentar.strip()


async def _rewrite_convergence(
    *,
    prompts: dict[str, str],
    section: WordDocumentSection,
    paragraph: WordDocumentParagraph,
    comments: list[tuple[str, str]],
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
    parsed = await complete_structured(
        [{"role": "user", "content": user}],
        WordRewriteSuggestion,
    )
    return rewrite_suggestion_or_none(parsed)


async def run_word_paragraph_review(
    session: AsyncSession,
    job: Job,
    payload: ExpertgranskningWordJobRequest,
    prompts: dict[str, str],
) -> dict[str, int]:
    slots = await load_expert_slots_from_population(session, payload.panel_id)
    brief = _document_brief(payload)
    paragraph_reviews = 0
    heading_reviews = 0
    result_count = 0

    for section_index, section in enumerate(payload.sections):
        for batch in build_batches(section):
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

            pending: list[ExpertgranskningResult] = []
            comments_by_index: dict[int, list[tuple[str, str]]] = {}
            written: list[tuple[PanelExpertSlot, WordDocumentParagraph, str]] = []
            for slot, question, text in comments:
                if not text:
                    continue
                for index in question.paragraph_indexes:
                    paragraph = by_index.get(index)
                    if paragraph is None:
                        continue
                    comments_by_index.setdefault(paragraph.index, []).append(
                        (slot.label, text)
                    )
                    written.append((slot, paragraph, text))

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
                        )
                        for paragraph in rewrite_targets
                    ]
                )
                if rewrite_targets
                else []
            )

            for slot, paragraph, text in written:
                pending.append(
                    await _write_result(
                        session,
                        job_id=job.id,
                        customer_id=payload.customer_id,
                        section_index=section_index,
                        paragraph_index=paragraph.index,
                        expert_id=slot.slot_id,
                        expert_namn=slot.label,
                        kommentar=text,
                        is_heading_suggestion=False,
                        request=job.request,
                        commit=False,
                    )
                )
                result_count += 1

            for paragraph, suggestion in zip(rewrite_targets, suggestions, strict=True):
                if suggestion is None:
                    continue
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

            await session.commit()
            for row in pending:
                await session.refresh(row)
                await publish_result_created(row, request=job.request)

        heading = await _review_heading(prompts=prompts, slots=slots, section=section)
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
