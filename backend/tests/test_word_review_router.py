"""Fast Word expert router: validation, cap, fallback, and panel seam."""

from __future__ import annotations

from app.services.expertgranskning.schemas import WordReviewQuestion
from app.services.expertgranskning.word_review_router import (
    WORD_REVIEW_MAX_ROUTED_EXPERTS,
    accepted_router_expert_ids,
    apply_router_ids,
    expert_descriptors,
    panel_experts_for_router,
    record_router_outcome,
    router_user_prompt,
)
from app.services.expertgranskning.word_review_timing import WordReviewTimings
from app.services.panel.schemas import PanelExpertSlot
from app.services.prompt_catalog import default_prompts


def _slots() -> list[PanelExpertSlot]:
    return [
        PanelExpertSlot(slot_id="jurist", label="Jurist", profile="Avtal"),
        PanelExpertSlot(
            slot_id="finansiell_analytiker",
            label="Finansiell analytiker",
            profile="Siffror",
        ),
        PanelExpertSlot(slot_id="teknik", label="Teknik", profile="IT"),
    ]


def test_router_accepts_one_or_two_ids_and_drops_unknown_duplicates():
    panel = frozenset(slot.slot_id for slot in _slots())
    kept, invalid = accepted_router_expert_ids(
        ["jurist", "ghost", "jurist", "teknik", "finansiell_analytiker"],
        panel,
    )
    assert WORD_REVIEW_MAX_ROUTED_EXPERTS == 2
    assert kept == ["jurist", "teknik"]
    assert invalid == 1
    empty, empty_invalid = accepted_router_expert_ids(["", "unknown"], panel)
    assert empty == []
    assert empty_invalid == 1


def test_router_unusable_result_is_empty_assignment():
    panel = frozenset({"jurist"})
    kept, invalid = accepted_router_expert_ids([], panel)
    assert kept == []
    assert invalid == 0
    kept, invalid = accepted_router_expert_ids(["ghost"], panel)
    assert kept == []
    assert invalid == 1


def test_panel_experts_for_router_passes_the_full_small_panel():
    slots = _slots()
    assert panel_experts_for_router(slots) == slots
    text = expert_descriptors(slots)
    assert "jurist (Jurist): Avtal" in text
    assert "teknik (Teknik): IT" in text


def test_apply_router_ids_sets_question_assignments():
    question = WordReviewQuestion(
        id="q1",
        paragraph_indexes=[1],
        question="Är fristen tydlig?",
        why_it_matters="Tolkningsrisk.",
        primary_anchor_paragraph_index=1,
    )
    routed = apply_router_ids(question, ["jurist", "teknik"])
    assert routed.recommended_expert_ids == ["jurist", "teknik"]
    assert question.recommended_expert_ids == []


def test_record_router_outcome_counts_without_prompt_text():
    timings = WordReviewTimings()
    record_router_outcome(timings, expert_ids=["jurist", "teknik"], invalid_ids=1)
    record_router_outcome(timings, expert_ids=[], invalid_ids=2)
    snapshot = timings.snapshot()
    assert snapshot["direct_routed_questions"] == 1
    assert snapshot["router_assignments"] == 2
    assert snapshot["raise_hand_questions"] == 1
    assert snapshot["router_fallback_count"] == 1
    assert snapshot["invalid_router_ids"] == 3
    dumped = repr(snapshot).replace("'prompt_tokens'", "").replace('"prompt_tokens"', "")
    assert "prompt" not in dumped
    assert "document" not in dumped


def test_router_prompt_has_question_context_and_panel_not_document():
    prompts = default_prompts("sv")
    question = WordReviewQuestion(
        id="q1",
        paragraph_indexes=[4],
        question="Vem bär risken för förseningen?",
        why_it_matters="Fördelning av ansvar.",
        primary_anchor_paragraph_index=4,
    )
    user = router_user_prompt(
        prompts=prompts,
        question=question,
        review_context="We represent the association, not the challenging members",
        slots=_slots(),
    )
    assert "Vem bär risken för förseningen?" in user
    assert "We represent the association" in user
    assert "jurist" in user
    assert "recommended_expert_ids" not in user
    english = default_prompts("en")["expertgranskning.word.expert.router"]
    assert "{review_context}" in english
    assert "{expert_list}" in english
