"""Repeat step 3 with a bound human-authored rubric and preserve every result."""

import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.llm import bind_usage_recorder, reset_usage_recorder
from tests.research_reuse.live import workload
from tests.research_reuse.coverage import Criterion, build_evaluator
from tests.research_reuse.probes import gaps
from tests.research_reuse.snapshots import ASSESSMENT, EVIDENCE, GAPS, digest, read


async def run(args) -> dict:
    output = {"runs": [], "rubric": args.rubric}
    directory = Path(args.workspace)
    report = directory / args.output
    if report.exists():
        raise FileExistsError("Choose a new output filename to preserve earlier quality results")
    engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        need, context, _metadata = await workload(factory, args.attempt_id, args.need_id)
        identity = {"attempt_id": args.attempt_id, "need": asdict(need), "context": asdict(context)}
        first = read(directory / "step_1.json", target=identity, stage=1)
        second = read(
            directory / "step_2.json", target=identity, stage=2, parent=digest(first["payload"])
        )
        rubric = json.loads(Path(args.rubric).read_text())
        if rubric["question"] != need.question or rubric["assessment_digest"] != digest(
            second["payload"]
        ):
            raise ValueError("Rubric must match this question and saved assessment")
        criteria = TypeAdapter(list[Criterion]).validate_python(rubric["criteria"])
        assessment = ASSESSMENT.validate_python(second["payload"])
        items = EVIDENCE.validate_python(first["payload"])
        evaluator = await build_evaluator(factory, context)
        output.update(
            question=need.question,
            assessment_digest=rubric["assessment_digest"],
            criteria=rubric["criteria"],
        )
        for iteration in range(args.repeat):
            row = {"iteration": iteration + 1, "timings": {}, "llm_calls": []}
            output["runs"].append(row)
            token = bind_usage_recorder(lambda stats: row["llm_calls"].append(asdict(stats)))
            try:
                started = perf_counter()
                questions = await gaps(
                    factory, need, items, assessment, context=context, timings=row["timings"]
                )
                row["planning_seconds"] = perf_counter() - started
                row["questions"] = GAPS.dump_python(questions, mode="json")
                started = perf_counter()
                result = await evaluator.evaluate(need.question, assessment, questions, criteria)
                row["evaluation_seconds"] = perf_counter() - started
                row["evaluation"] = result.model_dump()
                row["passed"] = result.passed
            finally:
                reset_usage_recorder(token)
    finally:
        await engine.dispose()
        report.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    return output
