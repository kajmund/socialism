"""Fast expert router for accepted Word review questions.

Contract: question + concise review_context + panel descriptors -> slot IDs.
A future semantic prefilter can sit in `panel_experts_for_router` when the
library grows. This module does not embed or call SSR.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.services.expertgranskning.schemas import WordReviewQuestion
from app.services.expertgranskning.word_review_timing import WordReviewTimings
from app.services.panel.schemas import PanelExpertSlot
from app.services.prompt_catalog import render_prompt

WORD_REVIEW_MAX_ROUTED_EXPERTS = 2


def panel_experts_for_router(
    slots: Sequence[PanelExpertSlot],
) -> list[PanelExpertSlot]:
    """Pass the full panel for the current small library.

    Keep this as the only candidate-selection seam so a later semantic
    prefilter can sit in front without changing the router prompt contract.
    """
    return list(slots)


def expert_descriptors(slots: Sequence[PanelExpertSlot]) -> str:
    return "\n".join(
        f"- {slot.slot_id} ({slot.label}): {slot.profile or slot.label}"
        for slot in slots
    )


def accepted_router_expert_ids(
    raw_ids: Sequence[str],
    panel_slot_ids: frozenset[str],
    *,
    limit: int = WORD_REVIEW_MAX_ROUTED_EXPERTS,
) -> tuple[list[str], int]:
    """Keep known panel IDs in first-seen order. Return (kept, invalid_count)."""
    kept: list[str] = []
    seen: set[str] = set()
    invalid = 0
    for raw in raw_ids:
        expert_id = raw.strip()
        if not expert_id:
            continue
        if expert_id in seen:
            continue
        if expert_id not in panel_slot_ids:
            invalid += 1
            continue
        seen.add(expert_id)
        kept.append(expert_id)
        if len(kept) >= limit:
            break
    return kept, invalid


def apply_router_ids(
    question: WordReviewQuestion,
    expert_ids: Sequence[str],
) -> WordReviewQuestion:
    return WordReviewQuestion(
        id=question.id,
        paragraph_indexes=question.paragraph_indexes,
        question=question.question,
        why_it_matters=question.why_it_matters,
        primary_anchor_paragraph_index=question.primary_anchor_paragraph_index,
        recommended_expert_ids=list(expert_ids),
    )


def record_router_outcome(
    timings: WordReviewTimings,
    *,
    expert_ids: Sequence[str],
    invalid_ids: int,
) -> None:
    if invalid_ids:
        timings.record_invalid_router_ids(invalid_ids)
    if expert_ids:
        timings.record_direct_routed_questions(1)
        timings.record_router_assignments(len(expert_ids))
        return
    timings.record_raise_hand_questions(1)
    timings.record_router_fallback()


def router_user_prompt(
    *,
    prompts: dict[str, str],
    question: WordReviewQuestion,
    review_context: str,
    slots: Sequence[PanelExpertSlot],
) -> str:
    return render_prompt(
        prompts,
        "expertgranskning.word.expert.router",
        question=question.question,
        why_it_matters=question.why_it_matters,
        review_context=review_context or "(none)",
        expert_list=expert_descriptors(slots),
    )
