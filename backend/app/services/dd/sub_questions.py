"""DD panel sub-question seed data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubQuestionDefault:
    """Seed row for PanelSubQuestion — no expert_label (raise-hand owns ownership)."""

    key: str
    label: str
    sort_order: int = 0


@dataclass(frozen=True)
class SubQuestionRef:
    """Runtime sub-question reference (id == PanelSubQuestion.key)."""

    id: str
    label: str


DD_SUB_QUESTION_DEFAULTS: tuple[SubQuestionDefault, ...] = (
    SubQuestionDefault(key="finansiell_halsa", label="Finansiell hälsa", sort_order=0),
    SubQuestionDefault(key="legal_risk", label="Legal risk", sort_order=1),
    SubQuestionDefault(key="marknadsposition", label="Marknadsposition", sort_order=2),
    SubQuestionDefault(key="integrationsrisk", label="Integrationsrisk", sort_order=3),
)
