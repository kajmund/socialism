"""Deterministic planner/query anchoring for legal research (task-13).

The live diagnostic showed model-generated needs can be English and lose the
Swedish law citation. These tests pin the deterministic guard that carries the
objective's citation into planner/follow-up drafts and the source-level fallback
that refuses to send non-citations to `resolve_citation`.
"""

from __future__ import annotations

import pytest

from app.services.lagen_nu.question_validation import (
    KeepLegalQuestionValidator,
    LegalFollowUpPlannerAdapter,
    LegalNeedNormalizer,
    LegalResearchPlannerAdapter,
)
from app.services.lagen_nu.research_source import (
    _normalise_citation_text,
    _resolution_query,
    select_lagen_nu_flow,
)
from app.services.research.followup import FollowUpNeedDraft
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.planner import ResearchNeedDraft, ResearchObjective

SWEDISH_OBJECTIVE = (
    "Vilka typer av avtalsvillkor har faktiskt jämkats med stöd av "
    "36 § avtalslagen i svensk rättspraxis?"
)
SWEDISH_OBJECTIVE_NBSP = (
    "Vilka typer av avtalsvillkor har faktiskt jämkats med stöd av "
    "§\u202f36 avtalslagen i svensk rättspraxis?"
)
ENGLISH_NEED = (
    "What is the exact wording of §\u202f36 of the Swedish Contracts Act and "
    "what legislative intent regarding contract-term adjustment is expressed "
    "in the preparatory works?"
)


def _normalizer() -> LegalNeedNormalizer:
    return LegalNeedNormalizer(KeepLegalQuestionValidator())


class _EnglishPlanner:
    def __init__(self, question: str = ENGLISH_NEED) -> None:
        self.question = question

    async def plan_research(
        self,
        *,
        objective: ResearchObjective,
        available_source_types: list[str] | None = None,
    ) -> list[ResearchNeedDraft]:
        del objective, available_source_types
        return [
            ResearchNeedDraft(
                question=self.question,
                why_needed="diagnostic",
                source_types=["swedish_law"],
            )
        ]


class _EnglishFollowUpPlanner:
    async def plan_follow_ups(self, **_kwargs: object) -> list[FollowUpNeedDraft]:
        return [
            FollowUpNeedDraft(
                question=ENGLISH_NEED,
                why_needed="diagnostic gap",
                source_types=["swedish_preparatory_works"],
            )
        ]


@pytest.mark.asyncio
async def test_planner_adapter_anchors_english_need_to_swedish_objective() -> None:
    adapter = LegalResearchPlannerAdapter(_EnglishPlanner(), _normalizer())
    drafts = await adapter.plan_research(
        objective=ResearchObjective(objective=SWEDISH_OBJECTIVE)
    )

    assert len(drafts) == 1
    assert drafts[0].question == "Vad säger 36 § avtalslagen?"


@pytest.mark.asyncio
async def test_planner_adapter_handles_nbsp_in_objective() -> None:
    adapter = LegalResearchPlannerAdapter(_EnglishPlanner(), _normalizer())
    drafts = await adapter.plan_research(
        objective=ResearchObjective(objective=SWEDISH_OBJECTIVE_NBSP)
    )

    assert drafts[0].question == "Vad säger 36 § avtalslagen?"


@pytest.mark.asyncio
async def test_planner_adapter_leaves_anchored_swedish_need_unchanged() -> None:
    anchored = "Vilka avgöranden har tillämpat 36 § avtalslagen?"
    adapter = LegalResearchPlannerAdapter(_EnglishPlanner(anchored), _normalizer())
    drafts = await adapter.plan_research(
        objective=ResearchObjective(objective=SWEDISH_OBJECTIVE)
    )

    assert drafts[0].question == anchored
    assert drafts[0].normalization_reason != "objective_citation_anchor"


@pytest.mark.asyncio
async def test_follow_up_adapter_anchors_english_need_from_main_need() -> None:
    adapter = LegalFollowUpPlannerAdapter(
        _EnglishFollowUpPlanner(), _normalizer()
    )
    plan = ResearchPlan(
        needs=[
            ResearchNeed(
                id="research-main",
                question=SWEDISH_OBJECTIVE,
                why_needed="objective",
                source_types=["swedish_case_law"],
            )
        ]
    )
    drafts = await adapter.plan_follow_ups(
        plan=plan,
        assessment=None,
        evidence=[],
        previous_needs=[],
    )

    assert drafts[0].question == "Vad säger förarbetena till 36 § avtalslagen?"


def _need(question: str, source_type: str = "swedish_case_law") -> ResearchNeed:
    return ResearchNeed(
        id="citation",
        question=question,
        why_needed="citation",
        source_types=[source_type],  # type: ignore[list-item]
    )


def test_resolution_query_accepts_both_section_orders_and_nbsp() -> None:
    assert (
        _resolution_query(
            _need("Vilka avgöranden har tillämpat 36 § avtalslagen?"),
            "swedish_case_law",
        )
        == "36 § avtalslagen"
    )
    assert (
        _resolution_query(
            _need("Vilka avgöranden har tillämpat §\u202f36 avtalslagen?"),
            "swedish_case_law",
        )
        == "§ 36 avtalslagen"
    )


def test_resolution_query_returns_none_instead_of_the_whole_question() -> None:
    need = _need("Vilka rättsliga kriterier har domstolar använt enligt § 36?")
    assert _resolution_query(need, "swedish_case_law") is None


def test_select_flow_falls_back_to_search_without_a_valid_citation() -> None:
    assert select_lagen_nu_flow(_need("Vilka avgöranden enligt § 36?")) == "search"
    assert (
        select_lagen_nu_flow(
            _need("Vilka avgöranden har tillämpat 36 § avtalslagen?")
        )
        == "resolve"
    )


def test_citation_text_normalises_nbsp_and_non_breaking_hyphen() -> None:
    assert _normalise_citation_text("36\u202f§\u00a0avtalslagen") == "36 § avtalslagen"
    assert _normalise_citation_text("contract\u2011term") == "contract-term"
