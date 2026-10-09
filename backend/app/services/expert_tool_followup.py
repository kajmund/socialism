"""Continue an expert tool episode on the same transcript, and open a requested document."""

import logging
import time

from app.config import settings
from app.database.models import Persona, PersonaMessage
from app.llm import complete_text
from app.llm.runtime_override import SelectionRole
from app.realtime.library_chat_broadcast import library_chat_broadcast
from app.serializers import utcnow
from app.services.expert_async_tools import (
    LibraryToolScope,
    PlannedCall,
    ToolWork,
    _Thread,
    _last_user_text,
    _library_messages,
    _prompts,
    _run_one,
    tool_result_extra,
)
from app.services.expert_reasoning_episode import continue_expert_episode, trace_model_reply
from app.services.jobs import job_session_factory
from app.services.library_chat_fifo import trim_and_commit_library_chat
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

logger = logging.getLogger(__name__)


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


async def _wake(thread: _Thread, work: ToolWork, blob: str, tool_results: tuple[str, ...] = ()) -> None:
    try:
        text, reasoning = await _compose_followup(work, blob, tool_results)
    except Exception:
        logger.exception("Expert tool wake failed for %s", work.persona_id)
        text, reasoning = "", None
    async with thread.cond:
        if thread.busy or not text.strip():
            if thread.busy and blob:
                thread.pending.append(blob)
            thread.waking = False
            thread.cond.notify_all()
            return
    try:
        await _save_followup(work, text, reasoning)
    except Exception:
        logger.exception("Expert tool wake save failed for %s", work.persona_id)
        async with thread.cond:
            thread.pending.append(blob)
    finally:
        async with thread.cond:
            thread.waking = False
            thread.cond.notify_all()


async def _compose_followup(
    work: ToolWork,
    blob: str,
    tool_results: tuple[str, ...] = (),
) -> tuple[str, str | None]:
    factory = job_session_factory()
    async with factory() as session:
        persona = await session.get(Persona, work.persona_id)
        if persona is None:
            return "", None
        prompts = await _prompts(session, persona)
        customer_id = persona.customer_id
        session.expunge(persona)
        await session.commit()
    reasoning_profile, routing_decision, escalation_reason = await _maybe_escalate(
        work, prompts, blob,
    )

    async def publish(calls: list[PlannedCall]) -> None:
        await _publish_workspace_tools(customer_id, work, calls)

    with bound_expert_profile(reasoning_profile):
        text, reasoning = await continue_expert_episode(
            work,
            tool_results,
            run_call=_run_one,
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
        {"role": "system", "content": material},
        {"role": "user", "content": work.user_message},
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


async def _publish_workspace_tools(customer_id: int, work: ToolWork, calls: list[PlannedCall]) -> None:
    for call in calls:
        await library_chat_broadcast.publish(customer_id, work.persona_id, {
            "type": "workspace_tool", "thread_type": "expert", "thread_id": work.persona_id,
            "mode": work.mode, "name": call.name, "arguments": call.arguments,
        })


async def _save_followup(work: ToolWork, text: str, reasoning: str | None) -> None:
    from app.services.persona_chat import schedule_expert_memory_update, serialize_persona_message

    factory = job_session_factory()
    async with factory() as session:
        persona = await session.get(Persona, work.persona_id)
        if persona is None:
            return
        row = PersonaMessage(
            persona_id=work.persona_id,
            mode=work.mode,
            role="assistant",
            content=text,
            reasoning_content=reasoning,
            created_at=utcnow(),
        )
        session.add(row)
        await trim_and_commit_library_chat(session, work.persona_id, work.mode)
        stored = list((await session.execute(_library_messages(work.persona_id, work.mode))).scalars())
        customer_id = persona.customer_id
        question = _last_user_text(stored) or work.user_message
        payload = [serialize_persona_message(item).model_dump(mode="json") for item in stored]
        session.expunge(persona)
        await session.commit()
    await library_chat_broadcast.publish(
        customer_id,
        work.persona_id,
        {
            "type": "thread.message",
            "thread_type": "expert",
            "thread_id": work.persona_id,
            "mode": work.mode,
            "messages": payload,
        },
    )
    schedule_expert_memory_update(persona, message=question, reply=text, image_sha256=None)
