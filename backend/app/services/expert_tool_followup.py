"""Continue an expert tool episode on the same transcript, and open a requested document."""

import json
import time

from app.config import settings
from app.database.models import Persona
from app.llm import complete_text
from app.llm.runtime_override import SelectionRole
from app.services.expert_async_tools import (
    LibraryToolScope,
    PlannedCall,
    ToolWork,
    _prompts,
    tool_result_extra,
)
from app.services.expert_reasoning_episode import trace_model_reply
from app.services.jobs import job_session_factory
from app.services.expert_reasoning import (
    RoutingDecision,
    assess_expert_reasoning,
    bound_expert_profile,
    build_turn_state,
    emit_routing_event,
    higher_profile,
    RoutingEventState,
    should_reassess_tools,
)


def queue_document_open(scope: LibraryToolScope, source_id: str) -> None:
    scope.client_calls = [
        call for call in scope.client_calls
        if call.name != "show_document" or call.arguments.get("source_id") == source_id
    ]
    already_open = any(
        call.name == "show_document" and call.arguments.get("source_id") == source_id
        for call in scope.client_calls
    )
    if not already_open:
        scope.client_calls.append(PlannedCall(f"open-{source_id}", "show_document", {"source_id": source_id}))
    scope._calls = [call for call in scope._calls if call.name not in {"search_knowledge", "get_workspace_context"}]


def focus_calls_for_search(results: list[tuple[str, str]], workspace_state: dict | None) -> list[PlannedCall]:
    """Ask the document view to paint a searched passage that already has a position."""
    open_ids = _open_source_ids(workspace_state)
    calls: list[PlannedCall] = []
    seen: set[str] = set()
    for name, result in results:
        if name != "search_knowledge":
            continue
        reference_id = _highlight_reference(result, open_ids)
        if reference_id is None or reference_id in seen:
            continue
        seen.add(reference_id)
        calls.append(PlannedCall(f"focus-{reference_id}", "focus_anchor", {"reference_id": reference_id}))
    return calls


def _open_source_ids(state: dict | None) -> set[str]:
    documents = state.get("documents") if isinstance(state, dict) else None
    if not isinstance(documents, list):
        return set()
    return {
        row["source_id"]
        for row in documents
        if isinstance(row, dict) and isinstance(row.get("source_id"), str)
    }


def _highlight_reference(result: str, open_ids: set[str]) -> str | None:
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return None
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None
    fallback: str | None = None
    for item in items:
        reference_id = _positioned_reference(item)
        if reference_id is None:
            continue
        if isinstance(item, dict) and item.get("source_id") in open_ids:
            return reference_id
        fallback = fallback or reference_id
    return fallback


def _positioned_reference(item: object) -> str | None:
    if not isinstance(item, dict):
        return None
    reference_id = item.get("reference_id")
    anchor = item.get("anchor")
    if not isinstance(reference_id, str) or not reference_id or not isinstance(anchor, dict):
        return None
    page = anchor.get("page_number")
    rects = anchor.get("rects")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1 or not isinstance(rects, list) or not rects:
        return None
    return reference_id


async def compose_tool_episode(
    work: ToolWork,
    blob: str,
    tool_results: tuple[str, ...] = (),
    *,
    continue_episode,
    run_call,
    publish,
) -> tuple[str, str | None]:
    factory = job_session_factory()
    async with factory() as session:
        persona = await session.get(Persona, work.persona_id)
        if persona is None:
            return "", None
        prompts = await _prompts(session, persona)
        session.expunge(persona)
        await session.commit()
    reasoning_profile, routing_decision, escalation_reason = await _maybe_escalate(
        work, prompts, blob,
    )

    with bound_expert_profile(reasoning_profile):
        text, reasoning = await continue_episode(
            work,
            tool_results,
            run_call=run_call,
            publish=publish,
        )
    if (
        routing_decision is not None
        and work.reasoning_profile is not None
        and reasoning_profile is not None
    ):
        emit_routing_event(
            routing_decision,
            RoutingEventState(
                initial_profile=work.reasoning_profile,
                final_profile=reasoning_profile,
                escalated=reasoning_profile != work.reasoning_profile,
                escalation_reason=escalation_reason,
                tool_count=len(work.calls),
                turn_latency_ms=(
                    0.0
                    if work.turn_started_at is None
                    else (time.perf_counter() - work.turn_started_at) * 1000
                ),
                phase="final",
                spawn_exposed=work.spawn_exposed,
            ),
        )
    if _deeper_than_main(work.reasoning_profile, reasoning_profile) and text.strip():
        text = await _main_model_reply(work, prompts, text)
        reasoning = None
    return text, reasoning


def _deeper_than_main(
    main: SelectionRole | None, current: SelectionRole | None
) -> bool:
    if main is None or current is None or current == main:
        return False
    return higher_profile(main, current) == current


async def _main_model_reply(work: ToolWork, prompts: dict[str, str], draft: str) -> str:
    """The deeper episode reports back. Only the turn's model speaks to the user."""
    material = tool_result_extra(prompts, draft)
    messages = [
        *(list(work.episode.messages) if work.episode is not None else []),
        {"role": "assistant", "content": draft},
        {"role": "user", "content": material},
    ]
    with bound_expert_profile(work.reasoning_profile):
        text = (
            await complete_text(messages, prompt_key="chat.expert.tool_result")
        ).strip()
    trace_model_reply(work, messages, text)
    return text


async def _maybe_escalate(
    work: ToolWork,
    prompts: dict[str, str],
    blob: str,
) -> tuple[SelectionRole | None, RoutingDecision | None, str | None]:
    reasoning_profile = work.reasoning_profile
    routing_decision = work.reasoning_decision
    tool_names = [call.name for call in work.calls]
    if (
        reasoning_profile == "deep"
        or not settings.expert_reasoning_route_enabled
        or reasoning_profile is None
        or not should_reassess_tools(tool_names)
    ):
        return reasoning_profile, routing_decision, None
    decision = await assess_expert_reasoning(
        prompts=prompts,
        state=build_turn_state(
            work.user_message,
            workspace_state=work.workspace_state,
            tool_names=tool_names,
            tool_result=blob,
        ),
    )
    next_profile = higher_profile(reasoning_profile, decision.profile)
    escalation_reason = decision.reason if next_profile != reasoning_profile else None
    return next_profile, decision, escalation_reason
