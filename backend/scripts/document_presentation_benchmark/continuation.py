"""Independent baseline and treatment continuations over one shared find."""

from __future__ import annotations

import json
import time
from typing import Any

from openai import OpenAIError

from app.llm.tool_messages import assistant_message_dict
from scripts.document_presentation_benchmark.types import (
    Arm,
    BenchmarkEnvironment,
    CallCounts,
    CaseResult,
    CompleteTools,
    ContinuationInput,
    ExposeTools,
    PresentationDecision,
    SharedCaseExecution,
)
from scripts.document_presentation_benchmark.validation import (
    validate_gallery_continuation,
)


async def run_counterfactual_arm(
    shared: SharedCaseExecution,
    *,
    arm: Arm,
    environment: BenchmarkEnvironment,
    expose_tools: ExposeTools,
    complete_tools: CompleteTools,
) -> CaseResult:
    continuation_started = time.perf_counter()
    case = shared.continuation.case
    counts = copy_counts(shared.calls)
    decision = PresentationDecision(False, "baseline")
    show_call: dict[str, Any] | None = None
    continuation = "baseline"
    if arm == "treatment":
        decision = validate_gallery_continuation(
            shared.first_arguments,
            shared.result,
            allowed_source_ids=environment.inventory,
        )
        if decision.accepted:
            show_call = decision.call
            continuation = "deterministic"
    if show_call is None:
        try:
            show_call = await _baseline_continuation(
                shared.continuation,
                counts=counts,
                expose_tools=expose_tools,
                complete_tools=complete_tools,
            )
        except OpenAIError as exc:
            continuation = "model_error"
            decision = PresentationDecision(
                False,
                f"continuation_model_error:{type(exc).__name__}",
            )
    continuation_ms = (time.perf_counter() - continuation_started) * 1000
    source_ids = list(shared.result.get("source_ids") or [])
    gallery_presented = show_call is not None
    return CaseResult(
        case_id=case.case_id,
        arm=arm,
        intent=case.intent,
        mode=case.mode,
        latency_ms=shared.elapsed_ms + continuation_ms,
        shared_initial_latency_ms=shared.elapsed_ms,
        continuation_latency_ms=continuation_ms,
        calls=counts,
        first_tool_called=True,
        first_arguments=shared.first_arguments,
        search_arguments=shared.search_arguments,
        source_ids=source_ids,
        document_selection_correct=set(source_ids) == set(case.expected_source_ids),
        gallery_presented=gallery_presented,
        presentation_decision_correct=gallery_presented == case.expected_gallery,
        continuation=continuation,
        validation_reason=(
            None if decision.reason == "baseline" else decision.reason
        ),
    )


async def _baseline_continuation(
    continuation: ContinuationInput,
    *,
    counts: CallCounts,
    expose_tools: ExposeTools,
    complete_tools: CompleteTools,
) -> dict[str, Any] | None:
    result_json = json.dumps(continuation.result, ensure_ascii=False)
    rerouted, route = await expose_tools(
        prompts=continuation.prompts,
        specs=continuation.specs,
        message=continuation.case.message,
        workspace_state=continuation.state,
        tool_result=result_json,
        reroute=True,
    )
    counts.jev += 1
    continuation_messages = [
        *continuation.messages,
        assistant_message_dict(continuation.first),
    ]
    tool_call = continuation.first.tool_calls[0]
    continuation_messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": "find_documents",
            "content": result_json,
        }
    )
    counts.llm += 1
    second = await complete_tools(
        continuation_messages,
        rerouted,
        prompt_key="chat.mode.in_character",
        tool_choice="required" if route.require_tool else "auto",
    )
    return _show_call(second)


def copy_counts(counts: CallCounts) -> CallCounts:
    return CallCounts(
        llm=counts.llm,
        jev=counts.jev,
        embedding=counts.embedding,
    )


def _show_call(reply: Any) -> dict[str, Any] | None:
    calls = reply.tool_calls or []
    call = next(
        (item for item in calls if item.function.name == "show_document_set"),
        None,
    )
    if call is None:
        return None
    try:
        arguments = json.loads(call.function.arguments)
    except json.JSONDecodeError:
        return None
    return {"name": "show_document_set", "arguments": arguments}
