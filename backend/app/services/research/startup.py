"""Main-question reuse precedes decomposition; persist the resulting tree atomically."""

from dataclasses import dataclass, field, replace
import json
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ExecutionAttempt
from app.services.execution.service import (
    add_evidence_items,
    complete_need_execution,
    get_need_execution,
    seed_need_executions,
)
from app.services.research.assessment import ResearchAssessor, ResearchAssessmentDraft
from app.services.research.followup import (
    FollowUpResearchPlanner,
)
from app.services.research.graph_lookup import lookup_question
from app.services.research.gap_planning import plan_question_gaps
from app.services.research.models import (
    ResearchContext,
    ResearchEvidence,
    ResearchNeed,
    ResearchPlan,
    InvalidResearchPlanError,
)
from app.services.research.need_normalization import ResearchNeedNormalizer
from app.services.research.planner import (
    ResearchObjective,
    ResearchPlanner,
    ResearchPlannerError,
    InvalidResearchObjectiveError,
    plan_from_planner_drafts,
)
from app.services.research.plan import validate_research_plan, research_plan_from_snapshot
from app.services.research.question_graph import QuestionEvidenceGraph
from app.services.research.question_prepare import prepare_graph_questions
from app.services.research.reuse_gate import (
    answer_is_sufficient,
    assess_reuse,
    fresh_evidence,
)

MAIN_NEED_ID = "research-main"


def main_need(objective: ResearchObjective, source_types: Sequence[str]) -> ResearchNeed:
    return ResearchNeed(
        id=MAIN_NEED_ID,
        question=objective.objective,
        why_needed=json.dumps(
            {"objective": objective.objective, "context": objective.context},
            ensure_ascii=False,
            sort_keys=True,
        ),
        source_types=list(source_types),
    )


@dataclass(frozen=True)
class StartInputs:
    factory: async_sessionmaker[AsyncSession]
    objective: ResearchObjective | None
    plan: ResearchPlan | None
    initial_planner: ResearchPlanner | None
    followup_planner: FollowUpResearchPlanner
    assessor: ResearchAssessor
    graph: QuestionEvidenceGraph
    context: ResearchContext
    allowed_source_types: tuple[str, ...]
    need_limit: int
    normalizer: ResearchNeedNormalizer | None


@dataclass(frozen=True)
class ResearchStart:
    plan: ResearchPlan
    main_evidence: list[ResearchEvidence] = field(default_factory=list)
    main_prepared: bool = False
    main_assessment: ResearchAssessmentDraft | None = None
    objective: ResearchObjective | None = None


async def resolve_start(
    session: AsyncSession, attempt: ExecutionAttempt, inputs: StartInputs
) -> ResearchStart:
    from app.services.research.execution import _persist_start_snapshots, ResearchExecutionError

    if attempt.research_plan_snapshot is not None:
        plan = research_plan_from_snapshot(attempt.research_plan_snapshot)
        _budget(plan, inputs.need_limit)
        await prepare_graph_questions(
            inputs.factory, inputs.graph, inputs.context, [need.question for need in plan.needs]
        )
        return ResearchStart(plan)
    if attempt.status == "researching" and inputs.plan is None:
        raise ResearchExecutionError("Cannot resume research without its persisted plan")
    if inputs.plan is not None:
        plan = validate_research_plan(inputs.plan)
        if inputs.normalizer is not None:
            plan = await inputs.normalizer.normalize_plan(plan)
        start = ResearchStart(plan)
    else:
        start = await _main_first(inputs)
    await prepare_graph_questions(
        inputs.factory, inputs.graph, inputs.context, [need.question for need in start.plan.needs]
    )
    start = await _bind_initial(inputs, start)
    _budget(start.plan, inputs.need_limit)
    await _persist_start_snapshots(
        session, attempt=attempt, objective=inputs.objective, plan=start.plan
    )
    return start


async def _main_first(inputs: StartInputs) -> ResearchStart:
    if inputs.objective is None:
        raise InvalidResearchObjectiveError(
            "research_objective is required when no ResearchPlan is supplied"
        )
    if not inputs.allowed_source_types:
        raise ResearchPlannerError("no executable research source types are available")
    root = main_need(inputs.objective, inputs.allowed_source_types)
    await prepare_graph_questions(inputs.factory, inputs.graph, inputs.context, [root.question])
    from app.services.research.question_iteration import resolve_or_create_knowledge_question
    from app.services.research.knowledge_question import tenant_question_scope

    async with inputs.factory.begin() as session:
        canonical = await resolve_or_create_knowledge_question(
            session,
            graph=inputs.graph,
            question=root.question,
            scope=tenant_question_scope(inputs.context.scope.customer_id),
        )
    root = replace(root, knowledge_question_id=canonical.id)
    evidence = fresh_evidence(await lookup_question(inputs.factory, root, inputs.context))
    assessment = await assess_reuse(inputs.assessor, root, evidence)
    if answer_is_sufficient(assessment):
        return ResearchStart(
            ResearchPlan(needs=[root]), evidence, True, assessment, inputs.objective
        )
    children = await _initial_gaps(inputs, root, evidence, assessment)
    return ResearchStart(ResearchPlan(needs=[root, *children]), evidence, True)


async def _initial_gaps(inputs, root, evidence, assessment) -> list[ResearchNeed]:
    if evidence:
        accepted = await plan_question_gaps(
            inputs.followup_planner,
            root,
            assessment,
            evidence,
            normalizer=inputs.normalizer,
            available_source_types=inputs.allowed_source_types,
        )
        return [row.as_need() for row in accepted]
    if inputs.initial_planner is None:
        raise ResearchPlannerError("ResearchPlanner is required")
    try:
        drafts = await inputs.initial_planner.plan_research(
            objective=inputs.objective,
            available_source_types=inputs.allowed_source_types,
        )
    except ResearchPlannerError:
        raise
    except Exception as exc:
        raise ResearchPlannerError("Initial research planning failed") from exc
    if inputs.normalizer is not None:
        drafts = await inputs.normalizer.normalize_drafts(drafts)
    plan = plan_from_planner_drafts(drafts, allowed_source_types=inputs.allowed_source_types)
    if any(need.id == MAIN_NEED_ID for need in plan.needs):
        raise InvalidResearchPlanError("Planner used the reserved main-question ID")
    return list(plan.needs)


def _budget(plan: ResearchPlan, limit: int) -> None:
    if len(plan.needs) > limit:
        raise InvalidResearchPlanError(
            f"ResearchPlan has {len(plan.needs)} needs; research_max_needs_per_attempt={limit}"
        )


async def persist_main_lookup(
    session: AsyncSession, *, attempt_id: str, set_id: str, start: ResearchStart
) -> None:
    if not start.main_prepared:
        return
    from app.services.research.progress import emit_evidence_item, emit_need_completed

    stored = await add_evidence_items(session, evidence_set_id=set_id, items=start.main_evidence)
    for item in stored:
        await emit_evidence_item(session, attempt_id=attempt_id, item=item)
    rows = await seed_need_executions(session, attempt_id=attempt_id, need_ids=[MAIN_NEED_ID])
    row = await get_need_execution(
        session, next(row.id for row in rows if row.research_need_id == MAIN_NEED_ID)
    )
    if row.status == "pending":
        row = await complete_need_execution(session, row.id)
        await emit_need_completed(session, execution=row)
    if start.main_assessment is not None:
        await _persist_main_sufficiency(session, attempt_id, set_id, start)


async def _persist_main_sufficiency(
    session: AsyncSession, attempt_id: str, set_id: str, start: ResearchStart
) -> None:
    """The sole need is the original objective, including its context, already assessed."""
    from app.services.execution.service import (
        list_evidence_items,
        list_runtime_needs,
        persist_research_assessment,
        persist_research_completeness,
        runtime_need_from_row,
    )
    from app.services.research.assessment import evidence_fingerprint
    from app.services.research.completeness import ResearchCompletenessDraft, question_fingerprint
    from app.services.research.execution import assessable_from_item
    from app.services.research.progress import emit_assessment_persisted, emit_completeness_persisted

    evidence = [assessable_from_item(item) for item in await list_evidence_items(session, set_id)]
    runtime = [runtime_need_from_row(row) for row in await list_runtime_needs(session, attempt_id)]
    fingerprint = evidence_fingerprint(evidence)
    assessment = await persist_research_assessment(
        session,
        attempt_id=attempt_id,
        evidence_set_id=set_id,
        draft=start.main_assessment,
        evidence_fingerprint=fingerprint,
    )
    await emit_assessment_persisted(session, assessment=assessment)
    completeness = await persist_research_completeness(
        session,
        attempt_id=attempt_id,
        evidence_set_id=set_id,
        draft=ResearchCompletenessDraft(
            result="complete",
            rationale=start.main_assessment.rationale,
            considered_evidence_ids=[item.evidence_id for item in evidence],
            considered_question_keys=[row.question_key for row in runtime],
            model_provider=start.main_assessment.model_provider,
            model_name=start.main_assessment.model_name,
            model_version=start.main_assessment.model_version,
        ),
        evidence_fingerprint=fingerprint,
        question_fingerprint=question_fingerprint(runtime, start.objective),
    )
    await emit_completeness_persisted(session, completeness=completeness)


async def _bind_initial(inputs: StartInputs, start: ResearchStart) -> ResearchStart:
    from app.services.research.question_iteration import resolve_or_create_knowledge_question
    from app.services.research.knowledge_question import tenant_question_scope

    scope = tenant_question_scope(inputs.context.scope.customer_id)
    seen = {}
    needs = []
    duplicate_main = False
    async with inputs.factory.begin() as session:
        for need in start.plan.needs:
            question = await resolve_or_create_knowledge_question(
                session,
                graph=inputs.graph,
                question=need.question,
                scope=scope,
            )
            if question.id in seen:
                index = seen[question.id]
                if needs[index].id == MAIN_NEED_ID:
                    duplicate_main = True
                needs[index] = _merge_requirements(needs[index], need)
                continue
            seen[question.id] = len(needs)
            needs.append(replace(need, knowledge_question_id=question.id))
    prepared = start.main_prepared and not duplicate_main
    return replace(start, plan=ResearchPlan(needs=needs), main_prepared=prepared)


def _merge_requirements(first: ResearchNeed, second: ResearchNeed) -> ResearchNeed:
    """Execute one canonical question without dropping either request's source constraints."""
    return replace(
        first,
        source_types=list(dict.fromkeys([*first.source_types, *second.source_types])),
        requested_by=list(dict.fromkeys([*first.requested_by, *second.requested_by])),
        domains=list(dict.fromkeys([*first.domains, *second.domains])),
        modalities=list(dict.fromkeys([*first.modalities, *second.modalities])),
        capabilities=list(dict.fromkeys([*first.capabilities, *second.capabilities])),
    )
