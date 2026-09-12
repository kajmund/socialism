"""Authoritative per-execution domain-competence decisions.

Competency is profile-versus-question. It is not research planning and not
raise-hand. Frozen evidence must never manufacture expertise.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field, field_validator, model_validator

from app.llm import complete_structured
from app.services.panel.raise_hand import has_competence_disclaimer
from app.services.panel.review_intent import session_brief_for_llm
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig
from app.services.prompt_catalog import render_prompt


def _strip_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


class ExpertCompetency(BaseModel):
    """Structured LLM decision for one expert. Fail closed when omitted."""

    has_domain_competence: bool = False
    competence_reason: str = ""

    @field_validator("competence_reason", mode="before")
    @classmethod
    def strip_competence_reason(cls, value: object) -> str:
        return _strip_text(value)

    @model_validator(mode="after")
    def apply_competence_disclaimer(self) -> "ExpertCompetency":
        if has_competence_disclaimer(self.competence_reason) or not self.has_domain_competence:
            self.has_domain_competence = False
        return self


class SlotCompetency(BaseModel):
    """Persisted / downstream record for one expert slot."""

    slot_id: str
    label: str
    competent: bool
    reason: str = ""


class CompetencyState(BaseModel):
    """One authoritative competency decision per expert for this execution."""

    slots: list[SlotCompetency] = Field(default_factory=list)

    def competent_slot_ids(self) -> frozenset[str]:
        return frozenset(row.slot_id for row in self.slots if row.competent)

    def has_relevant_expert(self) -> bool:
        return bool(self.competent_slot_ids())

    def is_competent(self, slot_id: str) -> bool:
        return slot_id in self.competent_slot_ids()


def slot_competency(slot: PanelExpertSlot, decision: ExpertCompetency) -> SlotCompetency:
    return SlotCompetency(
        slot_id=slot.slot_id,
        label=slot.label,
        competent=decision.has_domain_competence,
        reason=decision.competence_reason,
    )


def competency_state_from_decisions(
    pairs: Sequence[tuple[PanelExpertSlot, ExpertCompetency]],
) -> CompetencyState:
    return CompetencyState(slots=[slot_competency(slot, decision) for slot, decision in pairs])


def _session_brief(config: PanelSessionConfig, prompts: dict[str, str]) -> str:
    return session_brief_for_llm(config, prompts)


async def assess_expert_competency(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    prompts: dict[str, str],
) -> ExpertCompetency:
    """Decide competence from role + question only. Never receives evidence."""
    brief = _session_brief(config, prompts)
    messages = [
        {
            "role": "system",
            "content": render_prompt(
                prompts, "panel.expert.system", label=slot.label, profile=slot.profile
            ),
        }
    ]
    if brief:
        messages.append({"role": "system", "content": brief})
    messages.append(
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "panel.expert.competency",
                topic=config.topic,
                brief=brief or config.topic,
                profile=slot.profile or slot.label,
            ),
        }
    )
    return await complete_structured(messages, ExpertCompetency)


async def assess_panel_competency(
    config: PanelSessionConfig,
    prompts: dict[str, str],
) -> CompetencyState:
    """Authoritative competency pass — no research plan, tools, or evidence."""
    decisions: list[tuple[PanelExpertSlot, ExpertCompetency]] = []
    for slot in config.expert_slots:
        decisions.append((slot, await assess_expert_competency(slot, config, prompts)))
    return competency_state_from_decisions(decisions)
