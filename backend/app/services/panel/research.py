"""Research-plan phase for generic_panel — identify needs and consolidate.

Need / source-type taxonomy comes from ``app.services.research``. This module
only owns panel draft, proposal, and consolidation types. No search, MCP, or
evidence execution lives here.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field, field_validator, model_validator

from app.llm import complete_structured
from app.services.panel.competency import ExpertCompetency
from app.services.panel.review_intent import session_brief_for_llm
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig
from app.services.prompt_catalog import render_prompt
from app.services.research import (
    RESEARCH_SOURCE_TYPES,
    InvalidResearchPlanError,
    ResearchNeed,
    ResearchSourceType,
)

MISSING_EXPERTISE_SIGNAL = "Saknar domänkompetens. Kräver domänexpert."

_SOURCE_TYPE_BY_VALUE: dict[str, ResearchSourceType] = {
    item: item for item in RESEARCH_SOURCE_TYPES
}


def normalize_source_types(values: Sequence[str]) -> list[ResearchSourceType]:
    seen: set[str] = set()
    out: list[ResearchSourceType] = []
    for raw in values:
        known = _SOURCE_TYPE_BY_VALUE.get(str(raw).strip())
        if known is None or known in seen:
            continue
        seen.add(known)
        out.append(known)
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
    def keep_known_source_types(cls, value: list[str]) -> list[ResearchSourceType]:
        return normalize_source_types(value)


class ResearchPlan(BaseModel):
    """Persisted session plan — needs use the shared ``ResearchNeed`` dataclass."""

    needs: list[ResearchNeed] = Field(default_factory=list)


class ExpertResearchNeeds(ExpertCompetency):
    """Research-need draft. Competence is decided by ``ExpertCompetency``."""

    has_domain_competence: bool = True
    needs: list[ResearchNeedDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def drop_needs_without_competence(self) -> "ExpertResearchNeeds":
        if not self.has_domain_competence:
            self.needs = []
        return self


class ResearchProposal(BaseModel):
    """Temporary expert draft with a code-assigned proposal id."""

    proposal_id: str
    slot_id: str
    label: str = ""
    question: str
    why_needed: str
    source_types: list[str] = Field(default_factory=list)


class ConsolidatedResearchNeed(BaseModel):
    """Moderator grouping only. Code owns provenance and source types.

    ``source_types`` is accepted for LLM schema compatibility and ignored
    when the final ``ResearchNeed`` is built.
    """

    question: str
    why_needed: str
    proposal_ids: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)

    @field_validator("question", "why_needed", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> str:
        return _strip_text(value)

    @field_validator("proposal_ids")
    @classmethod
    def keep_unique_proposal_ids(cls, value: list[str]) -> list[str]:
        return _unique_ids(value)

    @field_validator("source_types")
    @classmethod
    def keep_known_source_types(cls, value: list[str]) -> list[ResearchSourceType]:
        return normalize_source_types(value)


class ModeratorResearchPlan(BaseModel):
    needs: list[ConsolidatedResearchNeed] = Field(default_factory=list)


def assign_proposal_ids(
    proposals: Sequence[tuple[PanelExpertSlot, ExpertResearchNeeds]],
) -> tuple[list[ResearchProposal], list[PanelExpertSlot]]:
    """Temporary proposal IDs are assigned in code — the LLM does not own them.

    Empty or whitespace-only questions are not real needs and get no id.
    A real need without an allowed source type fails closed; code does
    not invent a fallback source type.
    """
    numbered: list[ResearchProposal] = []
    empty_slots: list[PanelExpertSlot] = []
    index = 1
    for slot, bundle in proposals:
        if not bundle.has_domain_competence:
            empty_slots.append(slot)
            continue
        slot_proposals: list[ResearchProposal] = []
        for draft in bundle.needs:
            if not draft.question:
                continue
            if not draft.source_types:
                raise InvalidResearchPlanError(
                    "Research need must have at least one allowed source_type"
                )
            slot_proposals.append(
                ResearchProposal(
                    proposal_id=f"proposal_{index}",
                    slot_id=slot.slot_id,
                    label=slot.label,
                    question=draft.question,
                    why_needed=draft.why_needed,
                    source_types=list(draft.source_types),
                )
            )
            index += 1
        if not slot_proposals:
            empty_slots.append(slot)
            continue
        numbered.extend(slot_proposals)
    return numbered, empty_slots


def requested_by_from_proposals(
    proposal_ids: Sequence[str],
    proposals: Sequence[ResearchProposal],
) -> list[str]:
    by_id = {item.proposal_id: item.slot_id for item in proposals}
    return _unique_ids(
        by_id[proposal_id]
        for proposal_id in _unique_ids(proposal_ids)
        if proposal_id in by_id
    )


def source_types_from_proposals(
    proposal_ids: Sequence[str],
    proposals: Sequence[ResearchProposal],
) -> list[ResearchSourceType]:
    """Deterministic union of source types from included proposals."""
    by_id = {item.proposal_id: item for item in proposals}
    collected: set[str] = set()
    for proposal_id in _unique_ids(proposal_ids):
        proposal = by_id.get(proposal_id)
        if proposal is None:
            continue
        collected.update(proposal.source_types)
    return [item for item in RESEARCH_SOURCE_TYPES if item in collected]


def assign_research_need_ids(needs: Sequence[ResearchNeed]) -> ResearchPlan:
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


def format_expert_research_need_turn(
    drafts: Sequence[ResearchNeedDraft] | ExpertResearchNeeds,
    *,
    has_domain_competence: bool = True,
    competence_reason: str = "",
) -> str:
    if isinstance(drafts, ExpertResearchNeeds):
        bundle = drafts
        has_domain_competence = bundle.has_domain_competence
        competence_reason = bundle.competence_reason
        drafts = bundle.needs
    if not has_domain_competence:
        reason = competence_reason.strip()
        if reason:
            return f"{MISSING_EXPERTISE_SIGNAL}\n{reason}"
        return MISSING_EXPERTISE_SIGNAL
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
    proposals: Sequence[ResearchProposal],
    empty_slots: Sequence[PanelExpertSlot] = (),
) -> str:
    blocks: list[str] = []
    for item in proposals:
        types = ", ".join(item.source_types) if item.source_types else "—"
        label = f" {item.label}" if item.label else ""
        lines = [
            f"[{item.proposal_id}] slot_id={item.slot_id}{label}",
            f"- question: {item.question}",
            f"  why_needed: {item.why_needed}",
            f"  source_types: {types}",
        ]
        blocks.append("\n".join(lines))
    for slot in empty_slots:
        blocks.append(f"[inga förslag] slot_id={slot.slot_id} {slot.label}\n- (inga behov)")
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


def _session_brief(config: PanelSessionConfig, prompts: dict[str, str]) -> str:
    return session_brief_for_llm(config, prompts)


async def collect_expert_research_needs(
    slot: PanelExpertSlot,
    config: PanelSessionConfig,
    opening: str,
    prompts: dict[str, str],
) -> ExpertResearchNeeds:
    brief = _session_brief(config, prompts)
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
    proposals: Sequence[ResearchProposal],
    empty_slots: Sequence[PanelExpertSlot],
    prompts: dict[str, str],
    *,
    repair_error: str | None = None,
) -> ModeratorResearchPlan:
    brief = _session_brief(config, prompts)
    formatted = format_expert_proposals(proposals, empty_slots)
    messages = _messages_with_brief(
        identity=render_prompt(prompts, "panel.moderator.system"),
        brief=brief,
        user_content=render_prompt(
            prompts,
            "panel.moderator.research_plan",
            topic=config.topic,
            brief=brief or config.topic,
            opening=opening,
            expert_proposals=formatted,
            source_types=source_types_prompt(),
        ),
    )
    if repair_error:
        messages.append(
            {
                "role": "user",
                "content": render_prompt(
                    prompts,
                    "panel.moderator.research_plan_repair",
                    error=repair_error,
                    expert_proposals=formatted,
                ),
            }
        )
    return await complete_structured(messages, ModeratorResearchPlan)


def plan_from_moderator_draft(
    draft: ModeratorResearchPlan,
    proposals: Sequence[ResearchProposal],
) -> ResearchPlan:
    """Build a plan from moderator grouping. Code owns structural integrity.

    The LLM may formulate ``question`` / ``why_needed`` and group
    ``proposal_ids``. Provenance, source types, and consumption of every
    valid proposal are enforced here and fail closed.
    """
    known = {item.proposal_id for item in proposals}
    consumed: set[str] = set()
    kept: list[ResearchNeed] = []
    for need in draft.needs:
        proposal_ids = list(need.proposal_ids)
        if not proposal_ids:
            raise InvalidResearchPlanError(
                "Canonical research need must be anchored in at least one real proposal"
            )
        unknown = [item for item in proposal_ids if item not in known]
        if unknown:
            raise InvalidResearchPlanError(
                "Unknown proposal IDs cannot create a research need: "
                + ", ".join(unknown)
            )
        reused = [item for item in proposal_ids if item in consumed]
        if reused:
            raise InvalidResearchPlanError(
                "Proposal IDs consumed by multiple canonical needs: "
                + ", ".join(reused)
            )
        if not need.question:
            raise InvalidResearchPlanError(
                "Canonical research need question is required"
            )
        source_types = source_types_from_proposals(proposal_ids, proposals)
        if not source_types:
            raise InvalidResearchPlanError(
                "Canonical research need must have at least one source_type"
            )
        consumed.update(proposal_ids)
        kept.append(
            ResearchNeed(
                id="",
                question=need.question,
                why_needed=need.why_needed,
                requested_by=requested_by_from_proposals(proposal_ids, proposals),
                source_types=source_types,
            )
        )
    omitted = [
        item.proposal_id for item in proposals if item.proposal_id not in consumed
    ]
    if omitted:
        raise InvalidResearchPlanError(
            "Valid research proposals were omitted: " + ", ".join(omitted)
        )
    return assign_research_need_ids(kept)


async def build_research_plan(
    config: PanelSessionConfig,
    opening: str,
    proposals: Sequence[tuple[PanelExpertSlot, ExpertResearchNeeds]],
    prompts: dict[str, str],
) -> ResearchPlan:
    numbered, empty_slots = assign_proposal_ids(proposals)
    if not numbered:
        return ResearchPlan()
    draft = await consolidate_research_plan(
        config, opening, numbered, empty_slots, prompts
    )
    try:
        return plan_from_moderator_draft(draft, numbered)
    except InvalidResearchPlanError as exc:
        draft = await consolidate_research_plan(
            config,
            opening,
            numbered,
            empty_slots,
            prompts,
            repair_error=str(exc),
        )
        return plan_from_moderator_draft(draft, numbered)
