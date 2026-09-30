"""Replay only the real legal interpreter against fixed model configurations."""

import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.llm import bind_usage_recorder, reset_usage_recorder
from app.llm.legal_research import LegalDomainExtractionError, LlmLegalInterpreter
from app.llm.runtime_override import (
    PromptLlmAssignmentView,
    cached_configurations,
    default_configuration,
    set_runtime_selection_cache,
)
from tests.research_reuse.live import workload
from tests.research_reuse.legal_quality import LegalBenchmarkInput, check_legal_quality


async def interpret_case(interpreter, case, context) -> dict:
    row = {"input": case.id, "source_digest": case.raw_text_sha256, "llm_calls": []}
    token = bind_usage_recorder(lambda stats: row["llm_calls"].append(asdict(stats)))
    started = perf_counter()
    try:
        result = await interpreter.interpret(
            source=case.source,
            question=case.question,
            raw_text=case.raw_text,
            truncated=case.truncated,
            context=context,
        )
        checks = check_legal_quality(result, case)
        row.update(
            status="success",
            checks=checks,
            passed=all(checks.values()),
            result=result.model_dump(mode="json"),
        )
    except (LegalDomainExtractionError, ValueError) as exc:
        row.update(status="error", passed=False, error_type=type(exc).__name__, error=str(exc))
    finally:
        reset_usage_recorder(token)
        row["seconds"] = perf_counter() - started
    return row


async def run(args) -> dict:
    path = Path(args.output)
    if path.exists():
        raise FileExistsError("Choose a new output file to preserve previous benchmarks")
    cases = TypeAdapter(list[LegalBenchmarkInput]).validate_json(Path(args.inputs).read_text())
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("Benchmark inputs must be nonempty and have unique IDs")
    engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    output = {"mode": "fixed_configuration_legal_replay", "runs": []}
    try:
        _need, context, _metadata = await workload(factory, args.attempt_id, None)
        configs = cached_configurations()
        default = default_configuration()
        if default is None or not set(args.configuration_ids) <= set(configs):
            raise ValueError("Every explicitly selected model configuration must exist")
        interpreter = LlmLegalInterpreter(session_factory=factory)
        for configuration_id in args.configuration_ids:
            set_runtime_selection_cache(
                assignments={
                    "research.lagen_nu.domain.v3.system": PromptLlmAssignmentView(
                        mode="fixed", configuration_id=configuration_id
                    )
                },
                configurations=configs,
                default_configuration_id=default.id,
            )
            for _iteration in range(args.repeat):
                for case in cases:
                    row = await interpret_case(interpreter, case, context)
                    row.update(configuration_id=configuration_id, iteration=_iteration + 1)
                    output["runs"].append(row)
                    path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
                    print(
                        json.dumps(
                            {
                                key: row[key]
                                for key in ("input", "configuration_id", "seconds", "passed")
                            }
                        ),
                        flush=True,
                    )
    finally:
        await engine.dispose()
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    return output
