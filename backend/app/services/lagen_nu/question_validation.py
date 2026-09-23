"""Legal ResearchNeed validation. Domain-owned; does not retrieve."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from app.services.research.followup import FollowUpNeedDraft, RuntimeResearchNeed
from app.services.research.knowledge_question import research_question_key
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.plan import validate_research_plan
from app.services.research.planner import (
    ResearchNeedDraft,
    assign_initial_need_id,
)

LEGAL_RESEARCH_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "swedish_law",
        "swedish_case_law",
        "swedish_preparatory_works",
    }
)

LegalQuestionAction = Literal["keep", "rewrite", "split"]
LegalTrack = Literal["market_law", "civil_law", "mixed", "other", "unknown"]

MIXED_MD_AVTL_QUESTION = (
    "Vilka avgöranden från Marknadsdomstolen eller Konsumentombudsmannen finns "
    "där avtalsvillkor i konsumentförhållanden har lämnats utan avseende eller "
    "jämkats med stöd av 36 § avtalslagen?"
)
CIVIL_COURT_AVTL_QUESTION = (
    "Vilka allmänna domstolsavgöranden har tillämpat 36 § AvtL, tillsammans med "
    "de särskilda konsumentreglerna i AVLK där de är tillämpliga, på oskäliga "
    "villkor i konsumentavtal, och vilka villkor har jämkats eller lämnats utan "
    "avseende?"
)
MARKET_COURT_AVLK_QUESTION = (
    "Vilka avgöranden från Marknadsdomstolen/Patent- och marknadsdomstolen "
    "enligt 3 § AVLK belyser när standardvillkor i konsumentförhållanden bedömts "
    "som oskäliga, och vilka faktorer har varit avgörande?"
)
COMMERCIAL_AVTL_QUESTION = (
    "Vilka faktorer väger tyngst vid oskälighetsbedömningen enligt 36 § "
    "avtalslagen i kommersiella avtal?"
)

MARKET_AVLK_SPLIT_QUESTION = MARKET_COURT_AVLK_QUESTION
CIVIL_AVTL_SPLIT_QUESTION = CIVIL_COURT_AVTL_QUESTION


@dataclass(frozen=True)
class LegalQuestionVerdict:
    is_coherent: bool
    issue_type: str
    legal_track: LegalTrack
    institutions: tuple[str, ...]
    provisions: tuple[str, ...]
    remedy: str
    problems: tuple[str, ...]
    action: LegalQuestionAction
    rewritten_question: str = ""
    split_questions: tuple[str, ...] = ()
    rationale: str = ""


class LegalQuestionValidator(Protocol):
    async def validate(
        self,
        *,
        question: str,
        why_needed: str,
        source_types: Sequence[str],
    ) -> LegalQuestionVerdict: ...


class LegalQuestionValidationError(ValueError):
    """Structured legal validation failed. Not a retrieval outcome."""


class KeepLegalQuestionValidator:
    """Deterministic keep. Tests that must not invoke a model."""

    async def validate(
        self,
        *,
        question: str,
        why_needed: str,
        source_types: Sequence[str],
    ) -> LegalQuestionVerdict:
        _ = why_needed, source_types
        return keep_verdict(question)


class ScriptedLegalQuestionValidator:
    """Map exact questions to verdicts. Never infers legal semantics."""

    def __init__(
        self,
        verdicts: dict[str, LegalQuestionVerdict] | None = None,
        *,
        default: LegalQuestionVerdict | None = None,
    ) -> None:
        self.verdicts = dict(verdicts or {})
        self.default = default
        self.calls: list[str] = []

    async def validate(
        self,
        *,
        question: str,
        why_needed: str,
        source_types: Sequence[str],
    ) -> LegalQuestionVerdict:
        _ = why_needed, source_types
        self.calls.append(question)
        if question in self.verdicts:
            return self.verdicts[question]
        if self.default is not None:
            return self.default
        raise LegalQuestionValidationError(f"no scripted verdict for question: {question}")


def is_legal_research_need(source_types: Sequence[str]) -> bool:
    return any(item in LEGAL_RESEARCH_SOURCE_TYPES for item in source_types)


def forbidden_retrieval_questions(questions: Sequence[str]) -> list[str]:
    """The mixed MD/KO + 36 § AvtL example must never be retrieved as-is."""
    return [question for question in questions if question == MIXED_MD_AVTL_QUESTION]


def keep_verdict(question: str, *, legal_track: LegalTrack = "other") -> LegalQuestionVerdict:
    return LegalQuestionVerdict(
        is_coherent=True,
        issue_type="legal_question",
        legal_track=legal_track,
        institutions=(),
        provisions=(),
        remedy="",
        problems=(),
        action="keep",
        rationale="Question is legally coherent.",
    )


def origin_need_id(*, proposed_id: str, question: str) -> str:
    candidate = proposed_id.strip()
    if candidate:
        return candidate
    return f"normalized:{research_question_key(question)}"


def apply_legal_verdict_to_draft(
    draft: ResearchNeedDraft,
    verdict: LegalQuestionVerdict,
) -> list[ResearchNeedDraft]:
    origin = origin_need_id(proposed_id=draft.proposed_id, question=draft.question)
    if verdict.action == "keep":
        return [
            replace(
                draft,
                generated_from=draft.generated_from,
                original_need_id=draft.original_need_id,
                original_question=draft.original_question,
                normalization_reason=verdict.rationale,
                already_normalized=True,
            )
        ]
    if verdict.action == "rewrite":
        rewritten = verdict.rewritten_question.strip()
        if not rewritten:
            raise LegalQuestionValidationError("rewrite is missing rewritten_question")
        return [
            replace(
                draft,
                question=rewritten,
                proposed_id="",
                generated_from=origin,
                original_need_id=origin,
                original_question=draft.question,
                normalization_reason=verdict.rationale,
                already_normalized=True,
            )
        ]
    if verdict.action == "split":
        questions = [item.strip() for item in verdict.split_questions if item.strip()]
        if len(questions) < 2:
            raise LegalQuestionValidationError("split requires at least two questions")
        return [
            replace(
                draft,
                question=question,
                proposed_id="",
                generated_from=origin,
                original_need_id=origin,
                original_question=draft.question,
                normalization_reason=verdict.rationale,
                already_normalized=True,
            )
            for question in questions
        ]
    raise LegalQuestionValidationError(f"unknown legal validation action: {verdict.action}")


def apply_legal_verdict_to_follow_up(
    draft: FollowUpNeedDraft,
    verdict: LegalQuestionVerdict,
) -> list[FollowUpNeedDraft]:
    origin = origin_need_id(proposed_id=draft.proposed_id, question=draft.question)
    if verdict.action == "keep":
        return [
            replace(
                draft,
                generated_from=draft.generated_from,
                original_need_id=draft.original_need_id,
                original_question=draft.original_question,
                normalization_reason=verdict.rationale,
                already_normalized=True,
            )
        ]
    if verdict.action == "rewrite":
        rewritten = verdict.rewritten_question.strip()
        if not rewritten:
            raise LegalQuestionValidationError("rewrite is missing rewritten_question")
        return [
            replace(
                draft,
                question=rewritten,
                proposed_id="",
                generated_from=origin,
                original_need_id=origin,
                original_question=draft.question,
                normalization_reason=verdict.rationale,
                already_normalized=True,
            )
        ]
    if verdict.action == "split":
        questions = [item.strip() for item in verdict.split_questions if item.strip()]
        if len(questions) < 2:
            raise LegalQuestionValidationError("split requires at least two questions")
        return [
            replace(
                draft,
                question=question,
                proposed_id="",
                generated_from=origin,
                original_need_id=origin,
                original_question=draft.question,
                normalization_reason=verdict.rationale,
                already_normalized=True,
            )
            for question in questions
        ]
    raise LegalQuestionValidationError(f"unknown legal validation action: {verdict.action}")


def apply_legal_verdict_to_need(
    need: ResearchNeed,
    verdict: LegalQuestionVerdict,
) -> list[ResearchNeed]:
    origin = origin_need_id(proposed_id=need.id, question=need.question)
    if verdict.action == "keep":
        return [
            replace(
                need,
                normalization_reason=verdict.rationale,
                already_normalized=True,
            )
        ]
    if verdict.action == "rewrite":
        rewritten = verdict.rewritten_question.strip()
        if not rewritten:
            raise LegalQuestionValidationError("rewrite is missing rewritten_question")
        return [
            replace(
                need,
                question=rewritten,
                generated_from=origin,
                original_need_id=origin,
                original_question=need.question,
                normalization_reason=verdict.rationale,
                already_normalized=True,
            )
        ]
    if verdict.action == "split":
        questions = [item.strip() for item in verdict.split_questions if item.strip()]
        if len(questions) < 2:
            raise LegalQuestionValidationError("split requires at least two questions")
        return [
            replace(
                need,
                id="",
                question=question,
                generated_from=origin,
                original_need_id=origin,
                original_question=need.question,
                normalization_reason=verdict.rationale,
                already_normalized=True,
            )
            for question in questions
        ]
    raise LegalQuestionValidationError(f"unknown legal validation action: {verdict.action}")


class LegalNeedNormalizer:
    """Planner-adapter seam. Validates legal needs; leaves other domains untouched."""

    def __init__(self, validator: LegalQuestionValidator) -> None:
        self._validator = validator

    async def normalize_drafts(
        self, drafts: Sequence[ResearchNeedDraft]
    ) -> list[ResearchNeedDraft]:
        expanded: list[ResearchNeedDraft] = []
        for draft in drafts:
            expanded.extend(await self._normalize_draft(draft))
        return expanded

    async def normalize_follow_up_drafts(
        self, drafts: Sequence[FollowUpNeedDraft]
    ) -> list[FollowUpNeedDraft]:
        expanded: list[FollowUpNeedDraft] = []
        for draft in drafts:
            expanded.extend(await self._normalize_follow_up(draft))
        return expanded

    async def normalize_plan(self, plan: ResearchPlan) -> ResearchPlan:
        needs: list[ResearchNeed] = []
        existing_ids = {need.id for need in plan.needs if need.id.strip()}
        for index, need in enumerate(plan.needs, start=1):
            replacements = await self._normalize_need(need)
            if len(replacements) == 1 and replacements[0].id.strip():
                needs.append(replacements[0])
                existing_ids.add(replacements[0].id)
                continue
            for child in replacements:
                child_id = child.id.strip() or assign_initial_need_id(
                    index=index,
                    existing_ids=existing_ids,
                )
                existing_ids.add(child_id)
                needs.append(replace(child, id=child_id))
        return validate_research_plan(ResearchPlan(needs=needs))

    async def _normalize_draft(self, draft: ResearchNeedDraft) -> list[ResearchNeedDraft]:
        if draft.already_normalized or not is_legal_research_need(draft.source_types):
            return [replace(draft, already_normalized=True) if not draft.already_normalized else draft]
        verdict = await self._validator.validate(
            question=draft.question,
            why_needed=draft.why_needed,
            source_types=draft.source_types,
        )
        return apply_legal_verdict_to_draft(draft, verdict)

    async def _normalize_follow_up(self, draft: FollowUpNeedDraft) -> list[FollowUpNeedDraft]:
        if draft.already_normalized or not is_legal_research_need(draft.source_types):
            return [replace(draft, already_normalized=True) if not draft.already_normalized else draft]
        verdict = await self._validator.validate(
            question=draft.question,
            why_needed=draft.why_needed,
            source_types=draft.source_types,
        )
        return apply_legal_verdict_to_follow_up(draft, verdict)

    async def _normalize_need(self, need: ResearchNeed) -> list[ResearchNeed]:
        if need.already_normalized or not is_legal_research_need(need.source_types):
            return [replace(need, already_normalized=True) if not need.already_normalized else need]
        verdict = await self._validator.validate(
            question=need.question,
            why_needed=need.why_needed,
            source_types=need.source_types,
        )
        return apply_legal_verdict_to_need(need, verdict)


class LegalResearchPlannerAdapter:
    """Legal post-plan adapter. Generic planner stays domain-neutral."""

    def __init__(self, inner, normalizer: LegalNeedNormalizer) -> None:
        self._inner = inner
        self._normalizer = normalizer

    async def plan_research(
        self,
        *,
        objective,
        available_source_types: Sequence[str] | None = None,
    ) -> Sequence[ResearchNeedDraft]:
        drafts = await self._inner.plan_research(
            objective=objective,
            available_source_types=available_source_types,
        )
        return await self._normalizer.normalize_drafts(drafts)


class LegalFollowUpPlannerAdapter:
    """Legal post-follow-up adapter. Generic follow-up planner stays domain-neutral."""

    def __init__(self, inner, normalizer: LegalNeedNormalizer) -> None:
        self._inner = inner
        self._normalizer = normalizer

    async def plan_follow_ups(
        self,
        *,
        plan: ResearchPlan,
        assessment,
        evidence,
        previous_needs: Sequence[RuntimeResearchNeed],
        available_source_types: Sequence[str] | None = None,
    ) -> Sequence[FollowUpNeedDraft]:
        drafts = await self._inner.plan_follow_ups(
            plan=plan,
            assessment=assessment,
            evidence=evidence,
            previous_needs=previous_needs,
            available_source_types=available_source_types,
        )
        return await self._normalizer.normalize_follow_up_drafts(drafts)


def mixed_md_avtl_verdict() -> LegalQuestionVerdict:
    return LegalQuestionVerdict(
        is_coherent=False,
        issue_type="unfair_contract_terms",
        legal_track="mixed",
        institutions=("Marknadsdomstolen", "Konsumentombudsmannen"),
        provisions=("36 § AvtL",),
        remedy="jämkning eller lämnas utan avseende",
        problems=(
            "Marknadsdomstolen/KO tillämpar inte 36 § AvtL; konsumentvillkor "
            "kontrolleras marknadsrättsligt enligt 3 § AVLK.",
        ),
        action="split",
        split_questions=(MARKET_AVLK_SPLIT_QUESTION, CIVIL_AVTL_SPLIT_QUESTION),
        rationale=(
            "Frågan blandar det marknadsrättsliga AVLK-spåret med det "
            "civilrättsliga 36 § AvtL-spåret."
        ),
    )


def coherent_civil_avtl_verdict() -> LegalQuestionVerdict:
    return LegalQuestionVerdict(
        is_coherent=True,
        issue_type="unfair_contract_terms",
        legal_track="civil_law",
        institutions=("allmän domstol",),
        provisions=("36 § AvtL", "AVLK"),
        remedy="jämkning eller lämnas utan avseende",
        problems=(),
        action="keep",
        rationale="Allmän domstol och 36 § AvtL hör till samma civilrättsliga spår.",
    )


def coherent_market_avlk_verdict() -> LegalQuestionVerdict:
    return LegalQuestionVerdict(
        is_coherent=True,
        issue_type="unfair_contract_terms",
        legal_track="market_law",
        institutions=("Marknadsdomstolen", "Patent- och marknadsdomstolen"),
        provisions=("3 § AVLK",),
        remedy="förbud mot oskäliga villkor",
        problems=(),
        action="keep",
        rationale="MD/PMD och 3 § AVLK hör till samma marknadsrättsliga spår.",
    )


def coherent_commercial_avtl_verdict() -> LegalQuestionVerdict:
    return LegalQuestionVerdict(
        is_coherent=True,
        issue_type="unfair_contract_terms",
        legal_track="civil_law",
        institutions=("allmän domstol",),
        provisions=("36 § AvtL",),
        remedy="jämkning",
        problems=(),
        action="keep",
        rationale="Kommersiell 36 §-praxis ska inte dras in i AVLK.",
    )


def canonical_legal_question_verdicts() -> dict[str, LegalQuestionVerdict]:
    return {
        MIXED_MD_AVTL_QUESTION: mixed_md_avtl_verdict(),
        CIVIL_COURT_AVTL_QUESTION: coherent_civil_avtl_verdict(),
        MARKET_COURT_AVLK_QUESTION: coherent_market_avlk_verdict(),
        COMMERCIAL_AVTL_QUESTION: coherent_commercial_avtl_verdict(),
    }


def runtime_need_from_normalized(
    need: ResearchNeed,
    *,
    origin: str = "initial",
    wave_number: int = 0,
    parent_research_need_id: str | None = None,
    source_gap: str = "",
) -> RuntimeResearchNeed:
    return RuntimeResearchNeed(
        research_need_id=need.id,
        question=need.question,
        why_needed=need.why_needed,
        requested_by=list(need.requested_by),
        source_types=list(need.source_types),
        domains=list(need.domains),
        modalities=list(need.modalities),
        capabilities=list(need.capabilities),
        origin=origin,  # type: ignore[arg-type]
        wave_number=wave_number,
        parent_research_need_id=parent_research_need_id,
        source_gap=source_gap,
        generated_from=need.generated_from,
        original_need_id=need.original_need_id,
        original_question=need.original_question,
        normalization_reason=need.normalization_reason,
        already_normalized=need.already_normalized,
    )
