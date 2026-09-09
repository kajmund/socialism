"""Research-plan phase for generic_panel — identify needs and consolidate.

No search, MCP, or evidence execution lives here. A later router consumes
the persisted ``ResearchPlan``.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field, field_validator

from app.llm import complete_structured
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig
from app.services.prompt_catalog import render_prompt

RESEARCH_SOURCE_TYPES = (
    "case_knowledge",
    "customer_knowledge",
    "domain_knowledge",
    "swedish_law",
    "swedish_preparatory_works",
    "web",
)

_ALLOWED_SOURCE_TYPES = frozenset(RESEARCH_SOURCE_TYPES)


def normalize_source_types(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        item = str(raw).strip()
        if item not in _ALLOWED_SOURCE_TYPES or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _strip_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _unique_ids(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        item = str(raw).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


class ResearchNeedDraft(BaseModel):
    question: str
    why_needed: str
    source_types: list[str] = Field(default_factory=list)

    @field_validator("question", "why_needed", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> str:
        return _strip_text(value)

    @field_validator("source_types")
    @classmethod
    def keep_known_source_types(cls, value: list[str]) -> list[str]:
        return normalize_source_types(value)


class ResearchNeed(BaseModel):
    id: str
    question: str
    why_needed: str
    requested_by: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)

    @field_validator("id", "question", "why_needed", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> str:
        return _strip_text(value)

    @field_validator("requested_by")
    @classmethod
    def keep_unique_requesters(cls, value: list[str]) -> list[str]:
        return _unique_ids(value)

    @field_validator("source_types")
    @classmethod
    def keep_known_source_types(cls, value: list[str]) -> list[str]:
        return normalize_source_types(value)


class ResearchPlan(BaseModel):
    needs: list[ResearchNeed] = Field(default_factory=list)


class ExpertResearchNeeds(BaseModel):
    needs: list[ResearchNeedDraft] = Field(default_factory=list)


class ConsolidatedResearchNeed(BaseModel):
    question: str
    why_needed: str
    requested_by: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)

    @field_validator("question", "why_needed", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> str:
        return _strip_text(value)

    @field_validator("requested_by")
    @classmethod
    def keep_unique_requesters(cls, value: list[str]) -> list[str]:
        return _unique_ids(value)

    @field_validator("source_types")
    @classmethod
    def keep_known_source_types(cls, value: list[str]) -> list[str]:
        return normalize_source_types(value)


class ModeratorResearchPlan(BaseModel):
    needs: list[ConsolidatedResearchNeed] = Field(default_factory=list)


def assign_research_need_ids(
    needs: Sequence[ConsolidatedResearchNeed | ResearchNeed],
) -> ResearchPlan:
    """Permanent IDs are assigned in code — the LLM does not own them."""
    assigned: list[ResearchNeed] = []
    for index, need in enumerate(needs, start=1):
        assigned.append(
            ResearchNeed(
                id=f"research_{index}",
                question=need.question,
                why_needed=need.why_needed,
                requested_by=list(need.requested_by),
                source_types=list(need.source_types),
            )
        )
    return ResearchPlan(needs=assigned)


def research_plan_from_stored(raw: object) -> ResearchPlan:
    if raw is None:
        return ResearchPlan()
    return ResearchPlan.model_validate(raw)


def empty_research_structured(response_model: type) -> object | None:
    """Empty structured replies for tests — never invents research needs."""
    if response_model is ExpertResearchNeeds:
        return ExpertResearchNeeds()
    if response_model is ModeratorResearchPlan:
        return ModeratorResearchPlan()
    return None


def format_expert_research_need_turn(drafts: Sequence[ResearchNeedDraft]) -> str:
    if not drafts:
        return "Inga researchbehov."
    lines = ["Behov:"]
    for draft in drafts:
        types = ", ".join(draft.source_types) if draft.source_types else "—"
        lines.append(f"- {draft.question} [{types}]")
        if draft.why_needed:
            lines.append(f"  {draft.why_needed}")
    return "\n".join(lines)


def format_research_plan_turn(plan: ResearchPlan) -> str:
    if not plan.needs:
        return "Inga researchbehov."
    lines = ["Researchplan:"]
    for need in plan.needs:
        types = ", ".join(need.source_types) if need.source_types else "—"
        requested = ", ".join(need.requested_by) if need.requested_by else "—"
        lines.append(f"- {need.id}: {need.question} [{types}] (requested_by: {requested})")
        if need.why_needed:
            lines.append(f"  {need.why_needed}")
    return "\n".join(lines)


def source_types_prompt() -> str:
    return "\n".join(f"- {item}" for item in RESEARCH_SOURCE_TYPES)


def format_expert_proposals(
    proposals: Sequence[tuple[PanelExpertSlot, ExpertResearchNeeds]],
) -> str:
    blocks: list[str] = []
    for slot, bundle in proposals:
        if not bundle.needs:
            blocks.append(f"[{slot.slot_id}] {slot.label}\n- (inga behov)")
            continue
        lines = [f"[{slot.slot_id}] {slot.label}"]
        for draft in bundle.needs:
            types = ", ".join(draft.source_types) if draft.source_types else "—"
            lines.append(f"- question: {draft.question}")
            lines.append(f"  why_needed: {draft.why_needed}")
            lines.append(f"  source_types: {types}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _messages_with_brief(
    *,
    identity: str,
    brief: str,
    user_content: str,
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": identity}]
    if brief:
        messages.append({"role": "system", "content": brief})
    messages.append({"role": "user", "content": user_content})
    return messages


def _session_brief(config: PanelSessionConfig) -> str:
    return (config.brief or "").strip()


def _known_slot_ids(config: PanelSessionConfig) -> set[str]:
    return {slot.slot_id for slot in config.expert_slots}


def _filter_requested_by(requested_by: Sequence[str], known: set[str]) -> list[str]:
    return [item for item in _unique_ids(requested_by) if item in known]


async def collect_expert_research_needs(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    opening: str,
    prompts: dict[str, str],
) -> ExpertResearchNeeds:
    brief = _session_brief(config)
    messages = _messages_with_brief(
        identity=render_prompt(
            prompts, "panel.expert.system", label=slot.label, profile=slot.profile
        ),
        brief=brief,
        user_content=render_prompt(
            prompts,
            "panel.expert.research_need",
            topic=config.topic,
            brief=brief or config.topic,
            opening=opening,
            profile=slot.profile or slot.label,
            source_types=source_types_prompt(),
        ),
    )
    return await complete_structured(messages, ExpertResearchNeeds)


async def consolidate_research_plan(
    config: PanelSessionConfig,
    opening: str,
    proposals: Sequence[tuple[PanelExpertSlot, ExpertResearchNeeds]],
    prompts: dict[str, str],
) -> ModeratorResearchPlan:
    brief = _session_brief(config)
    messages = _messages_with_brief(
        identity=render_prompt(prompts, "panel.moderator.system"),
        brief=brief,
        user_content=render_prompt(
            prompts,
            "panel.moderator.research_plan",
            topic=config.topic,
            brief=brief or config.topic,
            opening=opening,
            expert_proposals=format_expert_proposals(proposals),
            source_types=source_types_prompt(),
        ),
    )
    return await complete_structured(messages, ModeratorResearchPlan)


def plan_from_moderator_draft(
    draft: ModeratorResearchPlan,
    config: PanelSessionConfig,
) -> ResearchPlan:
    known = _known_slot_ids(config)
    kept: list[ConsolidatedResearchNeed] = []
    for need in draft.needs:
        if not need.question:
            continue
        kept.append(
            ConsolidatedResearchNeed(
                question=need.question,
                why_needed=need.why_needed,
                requested_by=_filter_requested_by(need.requested_by, known),
                source_types=need.source_types,
            )
        )
    return assign_research_need_ids(kept)


async def build_research_plan(
    config: PanelSessionConfig,
    opening: str,
    proposals: Sequence[tuple[PanelExpertSlot, ExpertResearchNeeds]],
    prompts: dict[str, str],
) -> ResearchPlan:
    if not any(bundle.needs for _slot, bundle in proposals):
        return ResearchPlan()
    draft = await consolidate_research_plan(config, opening, proposals, prompts)
    return plan_from_moderator_draft(draft, config)
