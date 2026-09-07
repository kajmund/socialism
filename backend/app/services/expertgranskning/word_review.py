"""word_paragraph_review — sequential per-paragraph Word review.

Not generic_panel: one moderator call per kept paragraph, then one heading
assessment per section. Results are committed before the next LLM call.
"""

from __future__ import annotations

import re
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExpertgranskningResult, Job, PanelSession
from app.llm import complete_structured
from app.serializers import utcnow
from app.services.expertgranskning.schemas import (
    ExpertgranskningWordJobRequest,
    WordDocumentParagraph,
    WordDocumentSection,
    WordHeadingAssessment,
    WordParagraphComments,
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
        comment_id=None,
        status="pending",
        created_at=utcnow(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _review_paragraph(
    *,
    prompts: dict[str, str],
    slots: list[PanelExpertSlot],
    section: WordDocumentSection,
    paragraph: WordDocumentParagraph,
) -> WordParagraphComments:
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


async def run_word_paragraph_review(
    session: AsyncSession,
    job: Job,
    payload: ExpertgranskningWordJobRequest,
    prompts: dict[str, str],
) -> dict[str, int]:
    slots = await load_expert_slots_from_population(session, payload.panel_id)
    paragraph_reviews = 0
    heading_reviews = 0
    result_count = 0

    for section_index, section in enumerate(payload.sections):
        for paragraph in section.paragraphs:
            if not should_review_paragraph(paragraph):
                continue
            reviewed = await _review_paragraph(
                prompts=prompts,
                slots=slots,
                section=section,
                paragraph=paragraph,
            )
            paragraph_reviews += 1
            for comment in reviewed.comments:
                text = comment.kommentar.strip()
                if not text:
                    continue
                slot = next(
                    (
                        row
                        for row in slots
                        if row.slot_id == comment.expert_id.strip()
                    ),
                    None,
                )
                if slot is None:
                    continue
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
                )
                result_count += 1

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
