"""Paired counterfactual orchestration for the benchmark."""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import OpenAIError

from app.config import settings
from app.services.document_qa.tenants import set_tenant_catalogs
from app.services.prompt_catalog import default_prompts, render_prompt
from app.services.workspace_chat_tools import workspace_openai_tools, workspace_turn_text
from app.services.workspace_task_context import workspace_task_context
from scripts.document_presentation_benchmark.cases import (
    build_gold_cases,
    state_for_case,
)
from scripts.document_presentation_benchmark.continuation import (
    copy_counts,
    run_counterfactual_arm,
)
from scripts.document_presentation_benchmark.environment import (
    create_environment,
    production_runner,
)
from scripts.document_presentation_benchmark.report import summarize_results
from scripts.document_presentation_benchmark.types import (
    Arm,
    BenchmarkEnvironment,
    CallCounts,
    CaseResult,
    CompleteTools,
    ContinuationInput,
    ExposeTools,
    FindRunner,
    GoldCase,
    SharedCaseExecution,
)
from scripts.document_presentation_benchmark.validation import (
    EXPERIMENT_INSTRUCTION,
    experimental_find_spec,
    production_find_arguments,
)


async def run_benchmark(
    *,
    expose_tools: ExposeTools,
    complete_tools: CompleteTools,
) -> dict[str, Any]:
    cases = build_gold_cases()
    with tempfile.TemporaryDirectory(prefix="document-presentation-") as temp:
        environment, engine = await create_environment(Path(temp))
        try:
            find_runner = production_runner(environment)
            rows: list[CaseResult] = []
            for case in cases:
                baseline, treatment = await run_paired_case(
                    case,
                    environment=environment,
                    find_runner=find_runner,
                    expose_tools=expose_tools,
                    complete_tools=complete_tools,
                )
                rows.extend((baseline, treatment))
        finally:
            await engine.dispose()
            environment.registry.close()
            set_tenant_catalogs(None)
    return {
        "experiment": "document-presentation-paired-counterfactual-v2",
        "created_at": datetime.now(UTC).isoformat(),
        "case_count": len(cases),
        "arms": ["baseline", "treatment"],
        "summary": summarize_results(rows),
        "cases": [asdict(row) for row in rows],
    }


async def run_paired_case(
    case: GoldCase,
    *,
    environment: BenchmarkEnvironment,
    find_runner: FindRunner,
    expose_tools: ExposeTools,
    complete_tools: CompleteTools,
) -> tuple[CaseResult, CaseResult]:
    shared = await _run_shared_case(
        case,
        find_runner=find_runner,
        expose_tools=expose_tools,
        complete_tools=complete_tools,
    )
    if isinstance(shared, CaseResult):
        return (
            shared,
            _missing_find_result(
                case,
                "treatment",
                copy_counts(shared.calls),
                latency_ms=shared.latency_ms,
            ),
        )
    baseline = await run_counterfactual_arm(
        shared,
        arm="baseline",
        environment=environment,
        expose_tools=expose_tools,
        complete_tools=complete_tools,
    )
    treatment = await run_counterfactual_arm(
        shared,
        arm="treatment",
        environment=environment,
        expose_tools=expose_tools,
        complete_tools=complete_tools,
    )
    return baseline, treatment


async def _run_shared_case(
    case: GoldCase,
    *,
    find_runner: FindRunner,
    expose_tools: ExposeTools,
    complete_tools: CompleteTools,
) -> SharedCaseExecution | CaseResult:
    started = time.perf_counter()
    counts = CallCounts()
    prompts = default_prompts("sv")
    state = state_for_case(case)
    production_specs = workspace_openai_tools(prompts)
    specs = _specs_for_arm(production_specs, "treatment")
    exposed, route = await expose_tools(
        prompts=prompts,
        specs=specs,
        message=case.message,
        workspace_state=state,
    )
    counts.jev += 1
    relevant = (
        name
        for name in route.ranking
        if route.scores.get(name, 0.0) >= settings.document_tool_relevance_floor
    )
    extra = "\n\n".join(
        (workspace_turn_text(prompts, state), workspace_task_context(prompts, relevant))
    )
    messages = _messages(
        case.message,
        prompts,
        f"{extra}\n\n{EXPERIMENT_INSTRUCTION}",
    )
    counts.llm += 1
    try:
        first = await complete_tools(
            messages,
            exposed,
            prompt_key="chat.mode.in_character",
            tool_choice="auto",
        )
    except OpenAIError:
        return _missing_find_result(
            case,
            "baseline",
            counts,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
    arguments = _find_arguments(first)
    if arguments is None:
        return _missing_find_result(
            case,
            "baseline",
            counts,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
    search_arguments = production_find_arguments(arguments)
    result = await find_runner(search_arguments, state)
    counts.embedding += int(result.get("counters", {}).get("embedding_calls", 0))
    return SharedCaseExecution(
        continuation=ContinuationInput(
            case=case,
            prompts=prompts,
            specs=production_specs,
            state=state,
            messages=messages,
            first=first,
            result=result,
        ),
        first_arguments=arguments,
        search_arguments=search_arguments,
        result=result,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        calls=counts,
    )


def _specs_for_arm(specs: list[dict[str, Any]], arm: Arm) -> list[dict[str, Any]]:
    if arm == "baseline":
        return specs
    return [
        experimental_find_spec(spec) if spec["function"]["name"] == "find_documents" else spec
        for spec in specs
    ]


def _messages(
    message: str,
    prompts: dict[str, str],
    extra_system: str,
) -> list[dict[str, Any]]:
    system = "\n".join(
        (
            render_prompt(prompts, "chat.mode.in_character"),
            render_prompt(prompts, "chat.role_lock.in_character", name="Anna"),
            "",
            "Profil för Anna — du är den här experten:",
            "Namn: Anna\nKompetensområde: Avtalsjuridik",
            "",
            extra_system.strip(),
        )
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": message},
    ]


def _find_arguments(reply: Any) -> dict[str, Any] | None:
    calls = reply.tool_calls or []
    find_call = next(
        (call for call in calls if call.function.name == "find_documents"),
        None,
    )
    if find_call is None:
        return None
    try:
        parsed = json.loads(find_call.function.arguments)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _missing_find_result(
    case: GoldCase,
    arm: Arm,
    counts: CallCounts,
    *,
    latency_ms: float,
) -> CaseResult:
    return CaseResult(
        case_id=case.case_id,
        arm=arm,
        intent=case.intent,
        mode=case.mode,
        latency_ms=latency_ms,
        shared_initial_latency_ms=latency_ms,
        continuation_latency_ms=0.0,
        calls=counts,
        first_tool_called=False,
        first_arguments=None,
        search_arguments=None,
        source_ids=[],
        document_selection_correct=False,
        gallery_presented=False,
        presentation_decision_correct=not case.expected_gallery,
        continuation="none",
        validation_reason="find_documents_not_called",
    )


