"""word_paragraph_review — batch raise-hand + comment, then heading.

Each expert sees the full document plus disposition. Paragraphs are batched
(~4, clause-aware). An expert comments only on paragraphs they raised for.
Batches within a section run in parallel; sections stay sequential so heading
assessment still runs after the last body paragraph.
"""

from __future__ import annotations

import asyncio
import re
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExpertgranskningResult, Job, PanelSession
from app.llm import complete_structured
from app.serializers import utcnow
from app.services.expertgranskning.disposition import (
    batch_reviewable_paragraphs,
    build_disposition,
    document_text_from_sections,
    flatten_paragraphs,
    format_batch_paragraphs,
)
from app.services.expertgranskning.schemas import (
    ExpertgranskningWordJobRequest,
    WordDocumentParagraph,
    WordDocumentSection,
    WordExpertBatchComments,
    WordHeadingAssessment,
    WordParagraphComments,
    WordRaiseHand,
    WordRewriteAssessment,
    WordRewriteSuggestion,
)
from app.services.expertgranskning.watch import (
    publish_expertgranskning_finished,
    publish_result_created,
)
from app.services.panel.expert_slots import load_expert_slots_from_population
from app.services.panel.schemas import PanelExpertSlot
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts

_HEADING_1_TO_3 = re.compile(
    r"^(heading|rubrik)\s*[123]$",
    re.IGNORECASE,
)


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
    await session.commit()
    await session.refresh(row)
    await publish_result_created(row, request=request)
    return row


def rewrite_suggestion_or_none(
    parsed: WordParagraphComments,
) -> WordRewriteSuggestion | None:
    suggestion = parsed.omskrivning_forslag
    if suggestion is None:
        return None
    if not suggestion.ny_text.strip():
        return None
    if "\n" in suggestion.ny_text.replace("\r\n", "\n").replace("\r", "\n"):
        return None
    return suggestion


def _in_batch_indexes(raised: list[int], batch: list[WordDocumentParagraph]) -> list[int]:
    allowed = {paragraph.index for paragraph in batch}
    seen: set[int] = set()
    kept: list[int] = []
    for index in raised:
        if index not in allowed or index in seen:
            continue
        seen.add(index)
        kept.append(index)
    return kept


async def _raise_hand(
    *,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    slot: PanelExpertSlot,
    document_text: str,
    disposition: str,
    batch: list[WordDocumentParagraph],
) -> list[int]:
    user = render_prompt(
        prompts,
        "expertgranskning.word.raise_hand",
        expert_list=_expert_list(slots),
        expert_id=slot.slot_id,
        document_text=document_text,
        disposition=disposition,
        batch=format_batch_paragraphs(batch),
    )
    parsed = await complete_structured(
        [{"role": "user", "content": user}],
        WordRaiseHand,
    )
    return _in_batch_indexes(parsed.paragraph_indexes, batch)


async def _comment_raised(
    *,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    slot: PanelExpertSlot,
    document_text: str,
    disposition: str,
    batch: list[WordDocumentParagraph],
    raised: list[int],
) -> list[tuple[int, str]]:
    if not raised:
        return []
    raised_set = set(raised)
    user = render_prompt(
        prompts,
        "expertgranskning.word.comment",
        expert_list=_expert_list(slots),
        expert_id=slot.slot_id,
        document_text=document_text,
        disposition=disposition,
        batch=format_batch_paragraphs(batch),
        raised_indexes=", ".join(str(index) for index in raised),
    )
    parsed = await complete_structured(
        [{"role": "user", "content": user}],
        WordExpertBatchComments,
    )
    written: list[tuple[int, str]] = []
    for comment in parsed.comments:
        text = comment.kommentar.strip()
        if not text or comment.paragraph_index not in raised_set:
            continue
        written.append((comment.paragraph_index, text))
    return written


async def _rewrite_if_converged(
    *,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    document_text: str,
    disposition: str,
    paragraph: WordDocumentParagraph,
    comments: list[tuple[str, str]],
) -> WordRewriteSuggestion | None:
    if len(comments) < 2:
        return None
    comment_block = "\n".join(f"- {name}: {text}" for name, text in comments)
    user = render_prompt(
        prompts,
        "expertgranskning.word.rewrite",
        expert_list=_expert_list(slots),
        document_text=document_text,
        disposition=disposition,
        paragraph_text=paragraph.text,
        comments=comment_block,
    )
    parsed = await complete_structured(
        [{"role": "user", "content": user}],
        WordRewriteAssessment,
    )
    return rewrite_suggestion_or_none(
        WordParagraphComments(comments=[], omskrivning_forslag=parsed.omskrivning_forslag)
    )


async def _review_heading(
    *,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    section: WordDocumentSection,
    document_text: str,
    disposition: str,
) -> WordHeadingAssessment:
    user = render_prompt(
        prompts,
        "expertgranskning.word.heading",
        expert_list=_expert_list(slots),
        heading=section.heading,
        section_text=_section_body(section),
        document_text=document_text,
        disposition=disposition,
    )
    return await complete_structured(
        [{"role": "user", "content": user}],
        WordHeadingAssessment,
    )


async def _persist_result(
    write_lock: asyncio.Lock,
    *,
    job_id: str,
    customer_id: int,
    section_index: int,
    paragraph_index: int,
    expert_id: str,
    expert_namn: str,
    kommentar: str,
    is_heading_suggestion: bool,
    request: dict | None,
    is_rewrite_suggestion: bool = False,
    foreslagen_text: str | None = None,
) -> None:
    from app.services.jobs import job_session_factory

    factory = job_session_factory()
    async with write_lock:
        async with factory() as session:
            await _write_result(
                session,
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
                request=request,
            )


async def _review_batch(
    *,
    write_lock: asyncio.Lock,
    job_id: str,
    request: dict,
    payload: ExpertgranskningWordJobRequest,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    section_index: int,
    batch: list[WordDocumentParagraph],
    document_text: str,
    disposition: str,
) -> int:
    comments_by_index: dict[int, list[tuple[str, str]]] = {paragraph.index: [] for paragraph in batch}
    written = 0

    for slot in slots:
        raised = await _raise_hand(
            prompts=prompts,
            slots=slots,
            slot=slot,
            document_text=document_text,
            disposition=disposition,
            batch=batch,
        )
        comments = await _comment_raised(
            prompts=prompts,
            slots=slots,
            slot=slot,
            document_text=document_text,
            disposition=disposition,
            batch=batch,
            raised=raised,
        )
        for paragraph_index, text in comments:
            await _persist_result(
                write_lock,
                job_id=job_id,
                customer_id=payload.customer_id,
                section_index=section_index,
                paragraph_index=paragraph_index,
                expert_id=slot.slot_id,
                expert_namn=slot.label,
                kommentar=text,
                is_heading_suggestion=False,
                request=request,
            )
            written += 1
            comments_by_index[paragraph_index].append((slot.label, text))

    for paragraph in batch:
        suggestion = await _rewrite_if_converged(
            prompts=prompts,
            slots=slots,
            document_text=document_text,
            disposition=disposition,
            paragraph=paragraph,
            comments=comments_by_index[paragraph.index],
        )
        if suggestion is None:
            continue
        await _persist_result(
            write_lock,
            job_id=job_id,
            customer_id=payload.customer_id,
            section_index=section_index,
            paragraph_index=paragraph.index,
            expert_id="",
            expert_namn="",
            kommentar=suggestion.motivering.strip(),
            is_heading_suggestion=False,
            is_rewrite_suggestion=True,
            foreslagen_text=suggestion.ny_text.strip(),
            request=request,
        )
        written += 1
    return written


async def run_word_paragraph_review(
    session: AsyncSession,
    job: Job,
    payload: ExpertgranskningWordJobRequest,
    prompts: dict[str, str],
) -> dict[str, int]:
    slots = await load_expert_slots_from_population(session, payload.panel_id)
    document_text = document_text_from_sections(payload.sections)
    disposition = build_disposition(flatten_paragraphs(payload.sections))
    write_lock = asyncio.Lock()
    paragraph_reviews = 0
    heading_reviews = 0
    result_count = 0

    for section_index, section in enumerate(payload.sections):
        reviewable = [paragraph for paragraph in section.paragraphs if should_review_paragraph(paragraph)]
        batches = batch_reviewable_paragraphs(reviewable)
        paragraph_reviews += len(reviewable)
        if batches:
            written = await asyncio.gather(
                *[
                    _review_batch(
                        write_lock=write_lock,
                        job_id=job.id,
                        request=job.request or {},
                        payload=payload,
                        prompts=prompts,
                        slots=slots,
                        section_index=section_index,
                        batch=batch,
                        document_text=document_text,
                        disposition=disposition,
                    )
                    for batch in batches
                ]
            )
            result_count += sum(written)

        heading = await _review_heading(
            prompts=prompts,
            slots=slots,
            section=section,
            document_text=document_text,
            disposition=disposition,
        )
        heading_reviews += 1
        suggestion = (heading.forslag or "").strip()
        if suggestion:
            await _persist_result(
                write_lock,
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


word_paragraph_review.protocol = "word_paragraph_review"


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
