"""Strict isolated check of saved-answer lookup, reassessment and the no-gap gate."""

from dataclasses import asdict, replace
from time import perf_counter

from app.llm import bind_usage_recorder, reset_usage_recorder
from tests.research_reuse.live import workload

from app.services.research.composition import standard_available_source_types
from app.services.research.planner import ResearchObjective
from app.services.research.reuse_gate import answer_is_sufficient, fresh_evidence
from app.services.research.startup import main_need
from tests.research_reuse import probes
from tests.research_reuse.snapshots import ASSESSMENT, EVIDENCE


async def selected_workload(factory, attempt_id, need_id, *, as_main=False):
    need, context, metadata = await workload(factory, attempt_id, need_id)
    if as_main:
        need = replace(
            main_need(ResearchObjective(need.question), standard_available_source_types()),
            knowledge_question_id=need.knowledge_question_id,
        )
    return need, context, metadata


async def measure(factory, need, context, embeddings):
    started = perf_counter()
    timings = {}
    items = fresh_evidence(await probes.lookup(
        factory, need, context, embeddings, timings=timings,
    ))
    saved = [item for item in items if item.metadata.get("answer_fact_id")]
    checks = {"fresh_saved_answer": bool(saved), "sufficient": False, "no_gaps": False}
    output = {
        "checks": checks,
        "evidence": EVIDENCE.dump_python(items, mode="json"),
        "answer_fact_ids": sorted({item.metadata["answer_fact_id"] for item in saved}),
        "source_retrieval": "not_run",
        "timings": timings,
    }
    if saved:
        assessment = await probes.assess(factory, need, items, context, timings=timings)
        output["assessment"] = ASSESSMENT.dump_python(assessment, mode="json")
        checks["sufficient"] = answer_is_sufficient(assessment)
        if checks["sufficient"]:
            gaps = await probes.gaps(
                factory, need, items, assessment, context=context, timings=timings,
            )
            checks["no_gaps"] = not gaps
    output.update(contract_passed=all(checks.values()), seconds=perf_counter() - started)
    return output


async def repeat(factory, need, context, embeddings, *, count):
    results = []
    for _iteration in range(count):
        calls = []
        token = bind_usage_recorder(lambda stats: calls.append(asdict(stats)))
        try:
            row = await measure(factory, need, context, embeddings)
        finally:
            reset_usage_recorder(token)
        row["llm_calls"] = calls
        results.append(row)
    return results
