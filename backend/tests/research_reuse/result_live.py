"""Isolated production result lookup against configured DB/embeddings/Jev."""

import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.services.execution.service import get_attempt, get_run
from app.services.research.execution import research_context_from_run
from app.services.research.plan import research_plan_from_snapshot
from app.services.research.planner import ResearchObjective, research_objective_from_snapshot
from app.services.research.result_search import find_completed_research
from app.services.research.result_store import requested_context
from app.services.research.startup import main_need


async def probe_input(factory, args):
    async with factory() as session:
        attempt = await get_attempt(session, args.attempt_id)
        run = await get_run(session, attempt.run_id)
        objective = research_objective_from_snapshot(attempt.research_objective_snapshot)
        plan = research_plan_from_snapshot(attempt.research_plan_snapshot)
        selected = (
            next((need for need in plan.needs if need.id == args.need_id), None)
            if args.need_id
            else None
        )
        question = args.question or (selected.question if selected else objective.objective)
        objective = ResearchObjective(question, objective.context)
        need = (
            replace(selected, question=question)
            if selected
            else main_need(
                objective, tuple({kind for need in plan.needs for kind in need.source_types})
            )
        )
        materialized = await requested_context(session, objective, run)
        scope = research_context_from_run(run)
    return need, scope, materialized


async def run(args, *, factory=None):
    engine = None
    if factory is None:
        engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0)
        factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        need, scope, context = await probe_input(factory, args)
        measurements = []
        for iteration in range(args.repeat):
            started = perf_counter()
            result = await find_completed_research(factory, need, scope, context)
            measurements.append(
                {
                    "iteration": iteration + 1,
                    "elapsed_ms": (perf_counter() - started) * 1000,
                    "match": result.match,
                    "answer_fact_id": result.answer.fact_id if result.answer else None,
                    "evidence_set_id": result.answer.evidence_set_id if result.answer else None,
                    "evidence_count": len(result.answer.basis) if result.answer else 0,
                    "coverage": result.coverage.outcome if result.coverage else None,
                    "confidence": result.coverage.confidence if result.coverage else None,
                    "partial_answer_ids": [saved.fact_id for saved in result.partial],
                    "visited_edges": result.visited_edges,
                    "timings": result.timings,
                }
            )
        output = {"question": need.question, "mode": "lookup_only", "measurements": measurements}
        if args.output:
            Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2))
        return output
    finally:
        if engine is not None:
            await engine.dispose()
