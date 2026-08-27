"""DD panel sub-questions and expert-role mapping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DdSubQuestion:
    id: str
    label: str
    expert_label: str


DD_SUB_QUESTIONS: tuple[DdSubQuestion, ...] = (
    DdSubQuestion(
        id="finansiell_halsa",
        label="Finansiell hälsa",
        expert_label="Finansiell analytiker",
    ),
    DdSubQuestion(
        id="legal_risk",
        label="Legal risk",
        expert_label="Jurist",
    ),
    DdSubQuestion(
        id="marknadsposition",
        label="Marknadsposition",
        expert_label="Marknadsanalytiker",
    ),
    DdSubQuestion(
        id="integrationsrisk",
        label="Integrationsrisk",
        expert_label="Integrationsriskbedömare",
    ),
)


def sub_question_by_id(question_id: str) -> DdSubQuestion:
    for row in DD_SUB_QUESTIONS:
        if row.id == question_id:
            return row
    raise KeyError(f"Unknown DD sub-question: {question_id}")
