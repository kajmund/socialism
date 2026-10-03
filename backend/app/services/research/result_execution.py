"""Bind a run to an existing frozen result; never copy its evidence or graph."""

from __future__ import annotations

import logging
import asyncio
from typing import TYPE_CHECKING
from dataclasses import dataclass, field
from types import SimpleNamespace
from time import perf_counter

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExecutionAttempt, ExecutionRun, EvidenceSet
from app.database.workspace_ids import company_workspace_id
from app.services.execution.reuse_reference import REUSE_KEY
from app.observability.events import EVENT_DATASET_RESEARCH, log_event
from app.services.research.models import ResearchEvidence, ResearchNeed, ResearchPlan, utc_now
from app.services.research.plan import research_plan_to_snapshot
from app.services.research.planner import research_objective_to_snapshot
from app.services.research.result_search import ResultSearch, find_completed_research
from app.services.research.result_store import load_saved_answer, requested_context

if TYPE_CHECKING:
    from app.services.research.execution import AttemptResearchResult, ResearchRouterFactory
    from app.services.research.router import ResearchRouter
    from app.services.research.startup import StartInputs

logger = logging.getLogger(__name__)


def _check_lease(inputs: StartInputs) -> None:
    if inputs.lease_lost is not None and inputs.lease_lost.is_set():
        raise asyncio.CancelledError


@dataclass(frozen=True)
class ReuseAttempt:
    result: AttemptResearchResult | None = None
    partial: list[ResearchEvidence] = field(default_factory=list)


def partial_basis(search: ResultSearch, need: ResearchNeed) -> list[ResearchEvidence]:
    from app.services.research.answer_graph import _rebind

    output = {}
    for saved in search.partial:
        fact = SimpleNamespace(id=saved.fact_id, attributes={"answer_status": "sufficient"})
        for item in saved.basis:
            if item.source_type not in {*need.source_types, "derived"}:
                continue
            ref = str(item.metadata.get("reuse", {}).get("evidence_ref") or item.evidence_id)
            output.setdefault(ref, _rebind(item, need, fact, ref=ref, now=utc_now()))
    return list(output.values())


def resolve_router(
    session: AsyncSession,
    router: ResearchRouter | None,
    router_factory: ResearchRouterFactory | None,
) -> tuple[ResearchRouter | None, ResearchRouterFactory | None]:
    from app.services.research.composition import resolve_injected_research_router
    from app.services.research.execution import ResearchExecutionError

    if router is None and (injected := resolve_injected_research_router(session)) is not None:
        router, router_factory = injected, None
    if router is None and router_factory is None:
        raise ResearchExecutionError("ResearchRouter is required")
    return router, router_factory


async def reuse_completed_result(
    session: AsyncSession, attempt: ExecutionAttempt, inputs: StartInputs
) -> ReuseAttempt:
    from app.services.research.startup import main_need
    from app.services.research.knowledge_question import normalize_research_question
    from app.services.research.plan import validate_research_plan

    _check_lease(inputs)
    if attempt.status != "created" or attempt.evidence_set_id or inputs.objective is None:
        return ReuseAttempt()
    if inputs.plan is not None and len(inputs.plan.needs) != 1:
        return ReuseAttempt()
    need = (
        validate_research_plan(inputs.plan).needs[0]
        if inputs.plan
        else main_need(inputs.objective, inputs.allowed_source_types)
    )
    if normalize_research_question(need.question) != normalize_research_question(
        inputs.objective.objective
    ):
        return ReuseAttempt()
    started = perf_counter()
    async with inputs.factory() as reader:
        run = await reader.get(ExecutionRun, attempt.run_id)
        context = await requested_context(reader, inputs.objective, run)
    search = await find_completed_research(inputs.factory, need, inputs.context, context)
    _check_lease(inputs)
    if search.answer is None:
        return ReuseAttempt(partial=partial_basis(search, need))
    # Recheck temporal dependencies after external decisions and before binding.
    async with inputs.factory.begin() as writer:
        saved = await load_saved_answer(
            writer, search.answer.fact_id, inputs.context, now=utc_now()
        )
        if saved is None or saved.context != search.answer.context:
            return ReuseAttempt()
        reference = {
            "answer_fact_id": saved.fact_id,
            "source_attempt_id": saved.source_attempt_id,
            "evidence_set_id": saved.evidence_set_id,
            "match": search.match,
            "need_id": need.id,
            "question": need.question,
            "why_needed": need.why_needed,
            "knowledge_question_id": need.knowledge_question_id
            or inputs.objective.context.get("knowledge_question_id")
            or saved.question_id,
            "source_types": need.source_types,
            "coverage": None
            if search.coverage is None
            else {
                "outcome": search.coverage.outcome,
                "confidence": search.coverage.confidence,
                "model": search.coverage.model,
            },
        }
        bound = await writer.scalar(
            update(ExecutionAttempt)
            .where(
                ExecutionAttempt.id == attempt.id,
                ExecutionAttempt.status == "created",
                ExecutionAttempt.evidence_set_id.is_(None),
            )
            .values(
                evidence_set_id=saved.evidence_set_id,
                status="ready",
                research_stop_reason="sufficient",
                research_objective_snapshot=research_objective_to_snapshot(inputs.objective),
                research_plan_snapshot=research_plan_to_snapshot(ResearchPlan(needs=[need])),
                input_snapshot={**attempt.input_snapshot, REUSE_KEY: reference},
            )
            .returning(ExecutionAttempt.id)
        )
        if bound is None:
            raise RuntimeError("Research attempt changed while binding a reused result")
        _check_lease(inputs)
    await session.refresh(attempt)
    log_event(
        logger,
        "research.result.reused",
        dataset=EVENT_DATASET_RESEARCH,
        outcome="success",
        fields={
            "attempt": {"id": attempt.id},
            "research": {
                **reference,
                "elapsed_ms": (perf_counter() - started) * 1000,
                "timings": search.timings,
                "visited_edges": search.visited_edges,
            },
        },
    )
    from app.services.research.execution import _result_from_attempt

    return ReuseAttempt(result=await _result_from_attempt(session, attempt))


async def may_attach_reused_set(
    session: AsyncSession, attempt: ExecutionAttempt, evidence_set: EvidenceSet
) -> bool:
    """Cross-run sharing retains customer, workspace, case and frozen selection."""
    reference = attempt.input_snapshot.get(REUSE_KEY)
    if not reference or reference.get("evidence_set_id") != evidence_set.id:
        return False
    runs = {
        run.id: run
        for run in await session.scalars(
            select(ExecutionRun).where(
                ExecutionRun.id.in_((attempt.run_id, evidence_set.run_id)),
            )
        )
    }
    owned, source = runs[attempt.run_id], runs[evidence_set.run_id]
    return (
        owned.customer_id == source.customer_id
        and owned.module == source.module
        and (owned.context.get("case_id") == source.context.get("case_id"))
        and _same_workspace_basis(owned, source)
        and evidence_set.status == "frozen"
    )


def _same_workspace_basis(owned: ExecutionRun, source: ExecutionRun) -> bool:
    owned_id, source_id = owned.context.get("workspace_id"), source.context.get("workspace_id")
    normalized_owned = company_workspace_id(owned.customer_id) if owned_id is None else owned_id
    normalized_source = company_workspace_id(source.customer_id) if source_id is None else source_id
    if normalized_owned != normalized_source:
        return False
    if owned_id is None and source_id is None:
        return True
    owned_manifest = owned.context.get("document_manifest")
    source_manifest = source.context.get("document_manifest")
    return (
        isinstance(owned_manifest, list)
        and isinstance(source_manifest, list)
        and owned_manifest == source_manifest
    )
