"""Opt-in semantic quality evaluation; never part of the production research loop."""

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.llm import complete_structured_retry, invoke_structured_completer
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts
from app.services.research.assessment import ResearchAssessmentDraft
from app.services.research.followup import RuntimeResearchNeed


class Criterion(BaseModel):
    id: str = Field(min_length=1)
    requirement: str = Field(min_length=1)
    source_types: list[str] = Field(min_length=1)


class QuestionReference(BaseModel):
    research_need_id: str
    quote: str = Field(min_length=1)


class CriterionResult(BaseModel):
    criterion_id: str
    status: Literal["covered", "partial", "missing"]
    rationale: str = Field(min_length=1)
    references: list[QuestionReference] = Field(default_factory=list)


class Overlap(BaseModel):
    question_ids: list[str] = Field(min_length=2, max_length=2)
    rationale: str = Field(min_length=1)


class CoverageResult(BaseModel):
    criteria: list[CriterionResult]
    redundant_pairs: list[Overlap] = Field(default_factory=list)
    overbroad_question_ids: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            bool(self.criteria)
            and all(row.status == "covered" for row in self.criteria)
            and not (self.redundant_pairs or self.overbroad_question_ids)
        )


class CoverageEvaluator:
    def __init__(self, prompts: dict[str, str], *, completer: Callable[..., Awaitable[Any]]):
        self.prompts = prompts
        self.completer = completer

    async def evaluate(
        self,
        question: str,
        assessment: ResearchAssessmentDraft,
        questions: Sequence[RuntimeResearchNeed],
        criteria: Sequence[Criterion],
    ) -> CoverageResult:
        payload = {
            "question": question,
            "assessment": asdict(assessment),
            "questions": [asdict(row) for row in questions],
            "rubric": [row.model_dump() for row in criteria],
        }
        messages = [
            {
                "role": "system",
                "content": render_prompt(self.prompts, "research.followup.coverage.system"),
            },
            {
                "role": "user",
                "content": render_prompt(
                    self.prompts,
                    "research.followup.coverage.user",
                    payload_json=json.dumps(payload, ensure_ascii=False),
                ),
            },
        ]
        result = await invoke_structured_completer(
            self.completer, messages, CoverageResult, prompt_key="research.followup.coverage.system"
        )
        validate_coverage(result, questions, criteria)
        return result


def validate_coverage(
    result: CoverageResult,
    questions: Sequence[RuntimeResearchNeed],
    criteria: Sequence[Criterion],
) -> None:
    rubric = {row.id: row for row in criteria}
    ids = [row.criterion_id for row in result.criteria]
    if (
        not rubric
        or len(rubric) != len(criteria)
        or len(ids) != len(set(ids))
        or set(ids) != set(rubric)
    ):
        raise ValueError("Coverage evaluation must assess every rubric criterion exactly once")
    by_id = {row.research_need_id: row for row in questions}
    for row in result.criteria:
        if (row.status == "missing") != (not row.references):
            raise ValueError("Coverage status must agree with question references")
        sources = set()
        for reference in row.references:
            question = by_id.get(reference.research_need_id)
            if question is None or reference.quote not in question.question:
                raise ValueError("Coverage references must quote an actual executable question")
            sources.update(question.source_types)
        if row.status == "covered" and not set(rubric[row.criterion_id].source_types) <= sources:
            raise ValueError("Covered criteria must have all required source types")
    for pair in result.redundant_pairs:
        if len(set(pair.question_ids)) != 2 or not set(pair.question_ids) <= set(by_id):
            raise ValueError("Overlap references must identify two actual questions")
    if not set(result.overbroad_question_ids) <= set(by_id):
        raise ValueError("Broadness references must identify actual questions")


async def build_evaluator(factory, context, *, completer=complete_structured_retry):
    async with factory() as session:
        prompts = await require_active_prompts(
            session,
            customer_id=context.scope.customer_id,
            module=context.scope.module,
            language="sv",
        )
    return CoverageEvaluator(prompts, completer=completer)
