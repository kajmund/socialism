"""generic_panel research-plan phase — needs, consolidation, empty plan."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.llm import set_structured_completer, set_text_completer, set_tools_completer
from app.services import research as shared_research
from app.services.panel.engine import run_generic_panel
from app.services.panel.research import (
    RESEARCH_SOURCE_TYPES,
    ConsolidatedResearchNeed,
    ExpertResearchNeeds,
    ModeratorResearchPlan,
    ResearchNeed,
    ResearchNeedDraft,
    ResearchPlan,
    ResearchProposal,
    assign_proposal_ids,
    assign_research_need_ids,
    build_research_plan,
    collect_expert_research_needs,
    empty_research_structured,
    format_expert_proposals,
    plan_from_moderator_draft,
    requested_by_from_proposals,
    source_types_from_proposals,
)
from app.services.panel.schemas import (
    PanelExpertSlot,
    PanelSessionConfig,
    PanelSessionCreate,
    PanelTurn,
)
from app.services.panel.sessions import create_panel_session, get_panel_session
from app.services.panel.synthesis import GenericPanelSynthesis, public_transcript_text
from app.services.prompt_catalog import default_prompts, render_prompt
from app.services.research import InvalidResearchPlanError

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_researchplan_migrations_are_linear_after_word_head():
    script = ScriptDirectory.from_config(Config(str(_BACKEND_ROOT / "alembic.ini")))
    assert script.get_heads() == ["069_word_actions"]
    actions = script.get_revision("069_word_actions")
    assert actions.down_revision == "068_word_application_lifecycle"
    lifecycle = script.get_revision("068_word_application_lifecycle")
    assert lifecycle.down_revision == "067_researchplan_valid_proposals"
    repair = script.get_revision("067_researchplan_valid_proposals")
    assert repair.down_revision == "066_researchplan_convergence"
    convergence = script.get_revision("066_researchplan_convergence")
    assert convergence.down_revision == "065_word_comment_anchor_retry"


def _config() -> PanelSessionConfig:
    return PanelSessionConfig(
        protocol="generic_panel",
        topic="Hävning av fastighetsavtal",
        brief="Avtalet finns i underlaget. Parterna tvistar om hävning.",
        max_rounds=1,
        expert_slots=[
            PanelExpertSlot(slot_id="legal", label="Jurist", profile="Avtalsrätt"),
            PanelExpertSlot(slot_id="property", label="Fastighet", profile="Fastigheter"),
        ],
    )


def _turn(turn_id: str, speaker: str, phase: str, content: str, *, slot_id: str | None = None) -> PanelTurn:
    return PanelTurn(
        turn_id=turn_id,
        speaker=speaker,
        phase=phase,  # type: ignore[arg-type]
        content=content,
        slot_id=slot_id,
    )


def _draft(
    question: str = "Vilka avtalsbestämmelser reglerar hävning?",
    why_needed: str = "Avgör vilka avtalsenliga förutsättningar som gäller.",
    source_types: list[str] | None = None,
) -> ResearchNeedDraft:
    return ResearchNeedDraft(
        question=question,
        why_needed=why_needed,
        source_types=["case_knowledge"] if source_types is None else source_types,
    )


def _install_research_llm(
    *,
    expert_needs: dict[str, ExpertResearchNeeds] | ExpertResearchNeeds,
    plan: ModeratorResearchPlan | None = None,
    captured: list[tuple[type, list[dict]]] | None = None,
    synthesis: GenericPanelSynthesis | None = None,
):
    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        if "JA eller NEJ" in user or "YES or NO" in user:
            return "JA"
        if "privata anteckningar" in user or "private notes" in user.lower():
            return "Pad"
        if "offentliga inlägg" in user or "public contribution" in user.lower():
            return "Bedömning: hävning kräver väsentligt avtalsbrott."
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Fri analys."
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen. Hur ska hävningen bedömas?"
        return "Svar"

    async def _tools(messages, tools=None):
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    async def _structured(messages, response_model):
        if captured is not None:
            captured.append((response_model, [dict(item) for item in messages]))
        if response_model is ExpertResearchNeeds:
            if isinstance(expert_needs, ExpertResearchNeeds):
                return expert_needs
            identity = ""
            for item in messages:
                if item.get("role") == "system":
                    identity += item["content"]
            for key, bundle in expert_needs.items():
                if f"som {key} i en expertpanel" in identity:
                    return bundle
            return ExpertResearchNeeds()
        if response_model is ModeratorResearchPlan:
            if plan is None:
                return ModeratorResearchPlan()
            return plan
        if response_model is GenericPanelSynthesis:
            return synthesis or GenericPanelSynthesis(
                summary="Strukturerad slutsats.",
                claims=[],
            )
        empty = empty_research_structured(response_model)
        if empty is not None:
            return empty
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_text_completer(_complete)
    set_tools_completer(_tools)
    set_structured_completer(_structured)


def _turns_by_phase(transcript: list[dict], phase: str) -> list[dict]:
    return [row for row in transcript if row["phase"] == phase]


async def _run_panel(factory, config: PanelSessionConfig):
    prompts = default_prompts("sv")
    async with factory() as db:
        created = await create_panel_session(db, PanelSessionCreate(config=config))
        row = await get_panel_session(db, created.id)
        assert row is not None
        await run_generic_panel(db, row, prompts)
        await db.commit()
        return row


def test_panel_reuses_shared_research_need_and_source_types():
    assert ResearchNeed is shared_research.ResearchNeed
    assert RESEARCH_SOURCE_TYPES is shared_research.RESEARCH_SOURCE_TYPES


def test_source_types_include_case_law_and_web():
    assert "case_knowledge" in RESEARCH_SOURCE_TYPES
    assert "swedish_law" in RESEARCH_SOURCE_TYPES
    assert "swedish_preparatory_works" in RESEARCH_SOURCE_TYPES
    assert "web" in RESEARCH_SOURCE_TYPES
    assert ResearchNeedDraft(
        question="Q",
        why_needed="W",
        source_types=["case_knowledge"],
    ).source_types == ["case_knowledge"]
    assert ResearchNeedDraft(
        question="Q",
        why_needed="W",
        source_types=["swedish_law"],
    ).source_types == ["swedish_law"]
    assert ResearchNeedDraft(
        question="Q",
        why_needed="W",
        source_types=["swedish_preparatory_works"],
    ).source_types == ["swedish_preparatory_works"]
    web = ResearchNeed(
        id="research_1",
        question="Q",
        why_needed="W",
        source_types=["web"],
    )
    assert web.source_types == ["web"]
    default_draft = ResearchNeedDraft(question="Q", why_needed="W")
    assert default_draft.source_types == []
    assert "web" not in default_draft.source_types
    default_need = ResearchNeed(id="research_1", question="Q", why_needed="W")
    assert default_need.source_types == []


def test_ids_are_assigned_in_code_not_by_llm():
    plan = assign_research_need_ids(
        [
            ResearchNeed(
                id="llm_should_not_win",
                question="Vilka avtalsbestämmelser reglerar hävning?",
                why_needed="Avtalsförutsättningar.",
                requested_by=["legal"],
                source_types=["case_knowledge"],
            ),
            ResearchNeed(
                id="also_ignored",
                question="Hur har svensk praxis behandlat väsentlighetskravet?",
                why_needed="Rättslig bedömning.",
                requested_by=["legal"],
                source_types=["swedish_law"],
            ),
        ]
    )
    assert [need.id for need in plan.needs] == ["research_1", "research_2"]


def _proposal(
    proposal_id: str,
    slot_id: str,
    *,
    question: str = "Vilka avtalsbestämmelser reglerar hävning?",
    why_needed: str = "Avgör vilka avtalsenliga förutsättningar som gäller.",
    source_types: list[str] | None = None,
    label: str = "",
) -> ResearchProposal:
    return ResearchProposal(
        proposal_id=proposal_id,
        slot_id=slot_id,
        label=label,
        question=question,
        why_needed=why_needed,
        source_types=["case_knowledge"] if source_types is None else source_types,
    )


def _need(
    *proposal_ids: str,
    question: str = "Vilka avtalsbestämmelser reglerar hävning?",
    why_needed: str = "Behövs för att fastställa avtalsförutsättningarna.",
    source_types: list[str] | None = None,
) -> ConsolidatedResearchNeed:
    return ConsolidatedResearchNeed(
        question=question,
        why_needed=why_needed,
        proposal_ids=list(proposal_ids),
        source_types=source_types or [],
    )


def _proposals_legal_property():
    numbered, empty = assign_proposal_ids(
        [
            (
                PanelExpertSlot(slot_id="legal", label="Jurist"),
                ExpertResearchNeeds(needs=[_draft()]),
            ),
            (
                PanelExpertSlot(slot_id="property", label="Fastighet"),
                ExpertResearchNeeds(needs=[_draft(question="Samma hävningsfråga")]),
            ),
        ]
    )
    assert [item.proposal_id for item in numbered] == ["proposal_1", "proposal_2"]
    assert empty == []
    return numbered


def test_requested_by_is_derived_from_proposal_ids():
    numbered = _proposals_legal_property()
    assert requested_by_from_proposals(
        ["proposal_2", "proposal_1", "proposal_99"], numbered
    ) == ["property", "legal"]
    plan = plan_from_moderator_draft(
        ModeratorResearchPlan(
            needs=[
                _need(
                    "proposal_1",
                    "proposal_2",
                    source_types=["case_knowledge"],
                )
            ]
        ),
        numbered,
    )
    assert plan.needs[0].id == "research_1"
    assert plan.needs[0].requested_by == ["legal", "property"]
    assert plan.needs[0].source_types == ["case_knowledge"]


def test_moderator_cannot_reassign_or_invent_requested_by():
    numbered = _proposals_legal_property()
    with pytest.raises(InvalidResearchPlanError, match="omitted"):
        plan_from_moderator_draft(
            ModeratorResearchPlan(needs=[_need("proposal_1")]),
            numbered,
        )
    with pytest.raises(InvalidResearchPlanError, match="Unknown proposal"):
        plan_from_moderator_draft(
            ModeratorResearchPlan(
                needs=[
                    _need(
                        "proposal_99",
                        question="Påhittat behov",
                        why_needed="Saknar förslag.",
                        source_types=["web"],
                    )
                ]
            ),
            numbered,
        )
    schema = ConsolidatedResearchNeed.model_json_schema()
    assert "requested_by" not in schema.get("properties", {})


def test_three_equivalent_proposals_become_one_need_with_all_requesters():
    proposals = [
        _proposal("proposal_1", "legal"),
        _proposal("proposal_2", "property", question="Samma hävningsfråga"),
        _proposal("proposal_3", "fin", question="Samma hävningsfråga igen"),
    ]
    plan = plan_from_moderator_draft(
        ModeratorResearchPlan(
            needs=[_need("proposal_1", "proposal_2", "proposal_3")]
        ),
        proposals,
    )
    assert len(plan.needs) == 1
    assert plan.needs[0].id == "research_1"
    assert plan.needs[0].requested_by == ["legal", "property", "fin"]


def test_merged_need_unions_source_types_from_proposals():
    proposals = [
        _proposal("proposal_1", "legal", source_types=["swedish_law"]),
        _proposal("proposal_2", "property", source_types=["case_knowledge"]),
    ]
    plan = plan_from_moderator_draft(
        ModeratorResearchPlan(needs=[_need("proposal_1", "proposal_2")]),
        proposals,
    )
    assert plan.needs[0].source_types == ["case_knowledge", "swedish_law"]
    assert source_types_from_proposals(
        ["proposal_1", "proposal_2"], proposals
    ) == ["case_knowledge", "swedish_law"]


def test_moderator_omitted_source_type_still_keeps_proposal_union():
    proposals = [
        _proposal("proposal_1", "legal", source_types=["swedish_law"]),
        _proposal("proposal_2", "property", source_types=["case_knowledge"]),
    ]
    plan = plan_from_moderator_draft(
        ModeratorResearchPlan(
            needs=[
                _need(
                    "proposal_1",
                    "proposal_2",
                    source_types=["case_knowledge"],
                )
            ]
        ),
        proposals,
    )
    assert plan.needs[0].source_types == ["case_knowledge", "swedish_law"]


def test_moderator_invented_source_type_is_ignored():
    proposals = [
        _proposal("proposal_1", "legal", source_types=["swedish_law"]),
        _proposal("proposal_2", "property", source_types=["case_knowledge"]),
    ]
    plan = plan_from_moderator_draft(
        ModeratorResearchPlan(
            needs=[
                _need(
                    "proposal_1",
                    "proposal_2",
                    source_types=["swedish_law", "case_knowledge", "web"],
                )
            ]
        ),
        proposals,
    )
    assert "web" not in plan.needs[0].source_types
    assert plan.needs[0].source_types == ["case_knowledge", "swedish_law"]


def test_omitted_valid_proposal_fails_closed():
    proposals = [
        _proposal("proposal_1", "legal"),
        _proposal("proposal_2", "property"),
        _proposal("proposal_3", "fin"),
    ]
    with pytest.raises(InvalidResearchPlanError, match="proposal_3"):
        plan_from_moderator_draft(
            ModeratorResearchPlan(needs=[_need("proposal_1", "proposal_2")]),
            proposals,
        )


def test_same_proposal_in_two_needs_fails_closed():
    proposals = [
        _proposal("proposal_1", "legal"),
        _proposal("proposal_2", "property"),
    ]
    with pytest.raises(InvalidResearchPlanError, match="multiple canonical needs"):
        plan_from_moderator_draft(
            ModeratorResearchPlan(
                needs=[
                    _need("proposal_1", "proposal_2"),
                    _need(
                        "proposal_1",
                        question="Andra formuleringen",
                        why_needed="Samma förslag igen.",
                    ),
                ]
            ),
            proposals,
        )


def test_unknown_proposal_cannot_create_need_or_provenance():
    proposals = [_proposal("proposal_1", "legal")]
    with pytest.raises(InvalidResearchPlanError, match="proposal_99"):
        plan_from_moderator_draft(
            ModeratorResearchPlan(
                needs=[
                    _need(
                        "proposal_99",
                        question="Påhittat behov",
                        why_needed="Okänt id.",
                        source_types=["web"],
                    )
                ]
            ),
            proposals,
        )


def test_canonical_need_without_real_proposal_fails_closed():
    proposals = [_proposal("proposal_1", "legal")]
    with pytest.raises(InvalidResearchPlanError, match="anchored"):
        plan_from_moderator_draft(
            ModeratorResearchPlan(
                needs=[
                    _need(
                        question="Påhittat behov",
                        why_needed="Inget förslag.",
                    )
                ]
            ),
            proposals,
        )


def test_distinct_groups_stay_separate_with_own_provenance():
    proposals = [
        _proposal(
            "proposal_1",
            "legal",
            question="Vad säger lagen om hävning?",
            source_types=["swedish_law"],
        ),
        _proposal(
            "proposal_2",
            "property",
            question="Vad säger avtalet om hävning?",
            source_types=["case_knowledge"],
        ),
    ]
    plan = plan_from_moderator_draft(
        ModeratorResearchPlan(
            needs=[
                _need(
                    "proposal_1",
                    question="Vad säger lagen om hävning?",
                    why_needed="Lagstöd.",
                ),
                _need(
                    "proposal_2",
                    question="Vad säger avtalet om hävning?",
                    why_needed="Avtalsstöd.",
                ),
            ]
        ),
        proposals,
    )
    assert [need.id for need in plan.needs] == ["research_1", "research_2"]
    assert plan.needs[0].requested_by == ["legal"]
    assert plan.needs[0].source_types == ["swedish_law"]
    assert plan.needs[1].requested_by == ["property"]
    assert plan.needs[1].source_types == ["case_knowledge"]


def test_empty_moderator_draft_with_no_proposals_stays_empty():
    plan = plan_from_moderator_draft(ModeratorResearchPlan(), [])
    assert plan == ResearchPlan(needs=[])


def test_explicit_empty_source_types_cannot_become_a_proposal():
    with pytest.raises(InvalidResearchPlanError, match="source_type"):
        assign_proposal_ids(
            [
                (
                    PanelExpertSlot(slot_id="legal", label="Jurist"),
                    ExpertResearchNeeds(needs=[_draft(source_types=[])]),
                )
            ]
        )


def test_empty_source_types_cannot_become_an_executable_canonical_need():
    proposals = [
        ResearchProposal(
            proposal_id="proposal_1",
            slot_id="legal",
            question="Vilka avtalsbestämmelser reglerar hävning?",
            why_needed="Avtalsförutsättningar.",
            source_types=[],
        )
    ]
    with pytest.raises(InvalidResearchPlanError, match="source_type"):
        plan_from_moderator_draft(
            ModeratorResearchPlan(needs=[_need("proposal_1")]),
            proposals,
        )


def test_empty_or_whitespace_question_is_not_assigned_a_proposal_id():
    numbered, empty = assign_proposal_ids(
        [
            (
                PanelExpertSlot(slot_id="legal", label="Jurist"),
                ExpertResearchNeeds(
                    needs=[
                        _draft(question=""),
                        _draft(question="   "),
                    ]
                ),
            )
        ]
    )
    assert numbered == []
    assert [slot.slot_id for slot in empty] == ["legal"]


@pytest.mark.asyncio
async def test_moderator_retry_repairs_omitted_proposal():
    captured: list[tuple[type, list[dict]]] = []
    plans = [
        ModeratorResearchPlan(needs=[_need("proposal_1")]),
        ModeratorResearchPlan(needs=[_need("proposal_1", "proposal_2")]),
    ]

    async def _structured(messages, response_model):
        captured.append((response_model, [dict(item) for item in messages]))
        if response_model is ModeratorResearchPlan:
            return plans.pop(0)
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_structured_completer(_structured)
    plan = await build_research_plan(
        _config(),
        "Öppning",
        [
            (
                PanelExpertSlot(slot_id="legal", label="Jurist"),
                ExpertResearchNeeds(needs=[_draft()]),
            ),
            (
                PanelExpertSlot(slot_id="property", label="Fastighet"),
                ExpertResearchNeeds(needs=[_draft(question="Samma hävningsfråga")]),
            ),
        ],
        default_prompts("sv"),
    )
    assert [model for model, _messages in captured] == [
        ModeratorResearchPlan,
        ModeratorResearchPlan,
    ]
    repair = captured[1][1][-1]["content"]
    assert "proposal_2" in repair
    assert "omitted" in repair
    assert plan.needs[0].requested_by == ["legal", "property"]
    assert plan.needs[0].source_types == ["case_knowledge"]


@pytest.mark.asyncio
async def test_moderator_retry_repairs_duplicated_proposal():
    captured: list[tuple[type, list[dict]]] = []
    plans = [
        ModeratorResearchPlan(
            needs=[
                _need("proposal_1", "proposal_2"),
                _need(
                    "proposal_1",
                    question="Andra formuleringen",
                    why_needed="Samma förslag igen.",
                ),
            ]
        ),
        ModeratorResearchPlan(needs=[_need("proposal_1", "proposal_2")]),
    ]

    async def _structured(messages, response_model):
        captured.append((response_model, [dict(item) for item in messages]))
        if response_model is ModeratorResearchPlan:
            return plans.pop(0)
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_structured_completer(_structured)
    plan = await build_research_plan(
        _config(),
        "Öppning",
        [
            (
                PanelExpertSlot(slot_id="legal", label="Jurist"),
                ExpertResearchNeeds(needs=[_draft()]),
            ),
            (
                PanelExpertSlot(slot_id="property", label="Fastighet"),
                ExpertResearchNeeds(needs=[_draft(question="Samma hävningsfråga")]),
            ),
        ],
        default_prompts("sv"),
    )
    repair = captured[1][1][-1]["content"]
    assert "multiple canonical needs" in repair
    assert plan.needs[0].requested_by == ["legal", "property"]


@pytest.mark.asyncio
async def test_moderator_second_invalid_output_still_fails_closed():
    async def _structured(messages, response_model):
        if response_model is ModeratorResearchPlan:
            return ModeratorResearchPlan(needs=[_need("proposal_1")])
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_structured_completer(_structured)
    with pytest.raises(InvalidResearchPlanError, match="proposal_2"):
        await build_research_plan(
            _config(),
            "Öppning",
            [
                (
                    PanelExpertSlot(slot_id="legal", label="Jurist"),
                    ExpertResearchNeeds(needs=[_draft()]),
                ),
                (
                    PanelExpertSlot(slot_id="property", label="Fastighet"),
                    ExpertResearchNeeds(needs=[_draft(question="Samma hävningsfråga")]),
                ),
            ],
            default_prompts("sv"),
        )


@pytest.mark.asyncio
async def test_expert_can_return_zero_needs():
    captured: list[tuple[type, list[dict]]] = []

    async def _structured(messages, response_model):
        captured.append((response_model, [dict(item) for item in messages]))
        if response_model is ExpertResearchNeeds:
            return ExpertResearchNeeds(needs=[])
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_structured_completer(_structured)
    bundle = await collect_expert_research_needs(
        _config().expert_slots[0],
        _config(),
        "Hur ska hävningen bedömas?",
        default_prompts("sv"),
    )
    assert bundle.needs == []
    assert captured[0][0] is ExpertResearchNeeds
    user = captured[0][1][-1]["content"]
    assert "slutbedömningen" in user or "final assessment" in user.lower()
    assert "nice-to-know" in user


@pytest.mark.asyncio
async def test_empty_expert_proposals_skip_moderator_and_stay_empty():
    moderator_called = False

    async def _structured(messages, response_model):
        nonlocal moderator_called
        if response_model is ModeratorResearchPlan:
            moderator_called = True
            return ModeratorResearchPlan(
                needs=[
                    ConsolidatedResearchNeed(
                        question="Påhittat behov",
                        why_needed="Ska inte skapas.",
                        proposal_ids=["proposal_1"],
                        source_types=["web"],
                    )
                ]
            )
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_structured_completer(_structured)
    plan = await build_research_plan(
        _config(),
        "Öppning",
        [
            (_config().expert_slots[0], ExpertResearchNeeds()),
            (_config().expert_slots[1], ExpertResearchNeeds()),
        ],
        default_prompts("sv"),
    )
    assert plan == ResearchPlan(needs=[])
    assert moderator_called is False


@pytest.mark.asyncio
async def test_research_collect_does_not_call_tools_or_mcp():
    async def _tools(*_args, **_kwargs):
        raise RuntimeError("tools should not be called during research")

    async def _structured(messages, response_model):
        if response_model is ExpertResearchNeeds:
            return ExpertResearchNeeds()
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_tools_completer(_tools)
    set_structured_completer(_structured)
    bundle = await collect_expert_research_needs(
        _config().expert_slots[0],
        _config(),
        "Öppning",
        default_prompts("sv"),
    )
    assert bundle.needs == []


def test_research_module_does_not_import_search_or_mcp():
    path = _BACKEND_ROOT / "app" / "services" / "panel" / "research.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert "app.services.dd.company_mcp" not in imported
    assert "app.services.expert_tools" not in imported
    assert "complete_text_with_company_tools" not in source


def test_word_and_structured_scoring_do_not_import_research():
    paths = [
        _BACKEND_ROOT / "app" / "services" / "expertgranskning" / "word_review.py",
        _BACKEND_ROOT / "app" / "services" / "panel" / "structured_scoring.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert "app.services.panel.research" not in imported, path


def test_research_prompts_render_and_forbid_service_names():
    prompts = default_prompts("sv")
    expert = render_prompt(
        prompts,
        "panel.expert.research_need",
        topic="Hävning",
        brief="Avtal",
        opening="Öppning",
        profile="Jurist",
        source_types="- case_knowledge\n- web",
    )
    moderator = render_prompt(
        prompts,
        "panel.moderator.research_plan",
        topic="Hävning",
        brief="Avtal",
        opening="Öppning",
        expert_proposals="[legal] Jurist",
        source_types="- case_knowledge\n- web",
    )
    assert "nice-to-know" in expert
    assert "källtyp" in expert
    assert "has_domain_competence" in expert
    assert "missing expertise" in expert
    assert "web är tillåten men inte default" in expert
    assert "inte lagen.nu" in expert
    repair = render_prompt(
        prompts,
        "panel.moderator.research_plan_repair",
        error="Valid research proposals were omitted: proposal_2",
        expert_proposals="[proposal_1] slot_id=legal",
    )
    assert "proposal_ids" in moderator
    assert "Sätt inte requested_by" in moderator
    assert "källtyper härleds i kod" in moderator
    assert "exakt en gång" in moderator
    assert "minst en tillåten källtyp" in expert
    assert "Hitta inte på en källtyp" in expert
    assert "exakt en gång" in repair
    assert "proposal_2" in repair


def test_public_transcript_excludes_research_phases():
    text = public_transcript_text(
        [
            _turn("1", "moderator", "opening", "Hur ska hävningen bedömas?"),
            _turn("2", "Jurist", "research_need", "Behov: avtalsklausuler", slot_id="legal"),
            _turn("3", "moderator", "research_plan", "Researchplan: research_1"),
            _turn("4", "Jurist", "raise_hand", "JA", slot_id="legal"),
            _turn("5", "Jurist", "expert", "Hävning kräver väsentligt avtalsbrott.", slot_id="legal"),
        ]
    )
    assert "Hur ska hävningen bedömas?" in text
    assert "Hävning kräver väsentligt avtalsbrott." in text
    assert "Behov: avtalsklausuler" not in text
    assert "Researchplan" not in text


@pytest.mark.asyncio
async def test_one_expert_need_lands_in_persisted_plan(client_db):
    _client, factory = client_db
    captured: list[tuple[type, list[dict]]] = []
    _install_research_llm(
        expert_needs={
            "Jurist": ExpertResearchNeeds(needs=[_draft()]),
            "Fastighet": ExpertResearchNeeds(),
        },
        plan=ModeratorResearchPlan(
            needs=[
                ConsolidatedResearchNeed(
                    question="Vilka avtalsbestämmelser reglerar hävning?",
                    why_needed="Behövs för att fastställa avtalsförutsättningarna.",
                    proposal_ids=["proposal_1"],
                    source_types=["case_knowledge"],
                )
            ]
        ),
        captured=captured,
    )
    row = await _run_panel(factory, _config())
    plan = ResearchPlan.model_validate(row.research_plan)
    assert len(plan.needs) == 1
    assert plan.needs[0].id == "research_1"
    assert plan.needs[0].question == "Vilka avtalsbestämmelser reglerar hävning?"
    assert plan.needs[0].requested_by == ["legal"]
    assert plan.needs[0].source_types == ["case_knowledge"]
    moderator_prompt = next(
        messages[-1]["content"]
        for model, messages in captured
        if model is ModeratorResearchPlan
    )
    assert "[proposal_1] slot_id=legal" in moderator_prompt
    assert "Sätt inte requested_by" in moderator_prompt
    assert [turn["phase"] for turn in row.transcript[:4]] == [
        "opening",
        "research_need",
        "research_need",
        "research_plan",
    ]
    assert _turns_by_phase(row.transcript, "research_need")[0]["slot_id"] == "legal"
    assert "hävning" in _turns_by_phase(row.transcript, "research_plan")[0]["content"]
    assert _turns_by_phase(row.transcript, "raise_hand")
    assert row.result["protocol"] == "generic_panel"


@pytest.mark.asyncio
async def test_three_overlapping_expert_needs_become_one(client_db):
    _client, factory = client_db
    config = PanelSessionConfig(
        protocol="generic_panel",
        topic="Hävning av fastighetsavtal",
        brief="Avtalet finns i underlaget.",
        max_rounds=1,
        expert_slots=[
            PanelExpertSlot(slot_id="legal", label="Jurist", profile="Avtalsrätt"),
            PanelExpertSlot(slot_id="property", label="Fastighet", profile="Fastigheter"),
            PanelExpertSlot(slot_id="fin", label="Finans", profile="Siffror"),
        ],
    )
    overlapping = ExpertResearchNeeds(
        needs=[
            _draft(
                question="Vilka klausuler styr hävning?",
                why_needed="Behövs för avtalsläget.",
            )
        ]
    )
    _install_research_llm(
        expert_needs=overlapping,
        plan=ModeratorResearchPlan(
            needs=[
                ConsolidatedResearchNeed(
                    question="Vilka avtalsbestämmelser reglerar hävning?",
                    why_needed="Behövs för att fastställa avtalsförutsättningarna.",
                    proposal_ids=["proposal_1", "proposal_2", "proposal_3"],
                    source_types=["case_knowledge"],
                )
            ]
        ),
    )
    row = await _run_panel(factory, config)
    plan = ResearchPlan.model_validate(row.research_plan)
    assert len(plan.needs) == 1
    assert plan.needs[0].id == "research_1"
    assert plan.needs[0].requested_by == ["legal", "property", "fin"]


@pytest.mark.asyncio
async def test_all_experts_zero_needs_empty_plan_continues_to_raise_hand(client_db):
    _client, factory = client_db
    captured: list[tuple[type, list[dict]]] = []
    _install_research_llm(
        expert_needs=ExpertResearchNeeds(),
        plan=ModeratorResearchPlan(
            needs=[
                ConsolidatedResearchNeed(
                    question="Ska inte skapas",
                    why_needed="Tom plan.",
                    proposal_ids=["proposal_1"],
                    source_types=["web"],
                )
            ]
        ),
        captured=captured,
    )
    row = await _run_panel(factory, _config())
    assert row.research_plan == {"needs": []}
    assert row.status == "succeeded"
    assert _turns_by_phase(row.transcript, "research_plan")[0]["content"] == "Inga researchbehov."
    raise_hands = _turns_by_phase(row.transcript, "raise_hand")
    assert [turn["content"] for turn in raise_hands] == ["JA", "JA"]
    assert _turns_by_phase(row.transcript, "expert")
    assert row.result["protocol"] == "generic_panel"
    assert not any(model is ModeratorResearchPlan for model, _messages in captured)


@pytest.mark.asyncio
async def test_research_uses_brief_and_opening_without_tools(client_db):
    _client, factory = client_db
    captured: list[tuple[type, list[dict]]] = []
    tools_calls: list[object] = []

    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        if "JA eller NEJ" in user or "YES or NO" in user:
            return "NEJ"
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen. Hur ska hävningen bedömas?"
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Fri analys."
        return "Svar"

    async def _tools(messages, tools=None):
        tools_calls.append(tools)
        return SimpleNamespace(content="ska inte anropas i research", tool_calls=None)

    async def _structured(messages, response_model):
        captured.append((response_model, [dict(item) for item in messages]))
        empty = empty_research_structured(response_model)
        if empty is not None:
            return empty
        if response_model is GenericPanelSynthesis:
            return GenericPanelSynthesis(summary="Tom.", claims=[])
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_text_completer(_complete)
    set_tools_completer(_tools)
    set_structured_completer(_structured)
    row = await _run_panel(factory, _config())
    expert_calls = [messages for model, messages in captured if model is ExpertResearchNeeds]
    assert len(expert_calls) == 2
    brief = _config().brief
    opening = "Välkommen. Hur ska hävningen bedömas?"
    for messages in expert_calls:
        system_texts = [item["content"] for item in messages if item["role"] == "system"]
        user = messages[-1]["content"]
        assert brief in system_texts
        assert opening in user
        assert "case_knowledge" in user
        assert "swedish_law" in user
    assert tools_calls == []
    assert row.research_plan == {"needs": []}


def test_format_expert_proposals_uses_code_assigned_proposal_ids():
    numbered, empty = assign_proposal_ids(
        [
            (
                PanelExpertSlot(slot_id="legal", label="Jurist"),
                ExpertResearchNeeds(needs=[_draft()]),
            ),
            (
                PanelExpertSlot(slot_id="property", label="Fastighet"),
                ExpertResearchNeeds(),
            ),
        ]
    )
    text = format_expert_proposals(numbered, empty)
    assert "[proposal_1] slot_id=legal Jurist" in text
    assert "slot_id=property Fastighet" in text
    assert "inga behov" in text
    assert "[proposal_2]" not in text
