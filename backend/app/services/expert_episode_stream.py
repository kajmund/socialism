"""Streaming variant of the expert tool episode, kept out of the baselined loop."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.llm.stream_tools import stream_with_tools
from app.services.expert_async_tools import PlannedCall, ToolWork, _planned_calls
from app.services.expert_reasoning_episode import (
    ExpertEpisode,
    RunCall,
    PublishCalls,
    _RoundOutcome,
    _append_results,
    _finish_round,
    _handle_call_free_round,
    _reasoning_text,
    _recover_empty_text_reply,
    _remember_transcript,
    _result_by_id,
    _trace_reply,
    _trace_rows,
    episode_assistant,
    latest_assistant_text,
    missing_passage_mark_notice,
)
from app.llm.tool_messages import assistant_message_dict
from app.services.dd.company_mcp import visible_assistant_text
from app.services.turn_amendment import current_amendment_queue, drain_amendments

_MAX_ROUNDS = 4


async def stream_expert_episode(
    work: ToolWork,
    results: Any,
    *,
    run_call: RunCall,
    publish: PublishCalls,
    reasoning_out: list[str | None],
) -> AsyncIterator[str]:
    """Stream the visible reply of an expert tool episode, token by token.

    Mirrors ``continue_expert_episode`` but yields text deltas as the final
    round streams. The final reasoning content is written to ``reasoning_out``.
    """
    episode = work.episode
    if episode is None:
        reasoning_out.append(None)
        return
    messages = [dict(message) for message in episode.messages]
    _trace_rows(work, _append_results(messages, _result_by_id(work.calls, results)))
    _remember_transcript(work, messages)
    _apply_opening_notice(work, messages, episode)
    last_text = ""
    last_reasoning: str | None = None
    streamed_any = False
    for _ in range(_MAX_ROUNDS):
        episode = work.episode
        if episode is None:
            break
        holder: list[Any] = []
        async for delta in stream_with_tools(
            messages,
            list(episode.specs),
            prompt_key=episode.prompt_key,
            tool_choice=episode.tool_choice,
            message_out=holder,
        ):
            streamed_any = True
            yield delta
        parts = _streamed_reply_parts(holder, messages, work, episode)
        if parts is None:
            break
        reply, payload, text, calls = parts
        if not calls:
            outcome, visible, last_reasoning = await _call_free_stream_outcome(
                work,
                messages,
                (reply, payload, text),
                episode=episode,
                last_text=last_text,
                last_reasoning=last_reasoning,
            )
            if outcome is _RoundOutcome.CONTINUE:
                continue
            reasoning_out.append(last_reasoning)
            if _visible_needs_yield(outcome, streamed_any, visible):
                yield visible
            return
        last_text = text or last_text
        round_reasoning = await _advance_stream_round(
            messages, calls, text, payload, work=work, run_call=run_call, publish=publish,
        )
        last_reasoning = round_reasoning or last_reasoning
        if await _apply_amendments(work, messages):
            last_text = ""
    recovered = await _recover_empty_text_reply(work, messages, last_text)
    reasoning_out.append(last_reasoning)
    if recovered is not None:
        yield recovered
        return
    if _has_unstreamed_text(last_text, streamed_any):
        yield last_text


async def _advance_stream_round(
    messages: list[dict[str, Any]],
    calls: tuple[PlannedCall, ...],
    text: str,
    payload: dict[str, Any],
    *,
    work: ToolWork,
    run_call: RunCall,
    publish: PublishCalls,
) -> str | None:
    _trace_reply(work, messages, text, calls)
    assistant = episode_assistant(payload, calls)
    messages.append(assistant)
    await _finish_round(messages, calls, work, run_call=run_call, publish=publish)
    _remember_transcript(work, messages)
    return _reasoning_text(assistant.get("reasoning_content"))


def _apply_opening_notice(
    work: ToolWork,
    messages: list[dict[str, Any]],
    episode: ExpertEpisode,
) -> None:
    opening_notice = missing_passage_mark_notice(
        latest_assistant_text(messages), messages, episode.specs,
    )
    if opening_notice is not None:
        messages.append(opening_notice)
        _remember_transcript(work, messages)


def _streamed_reply_parts(
    holder: list[Any],
    messages: list[dict[str, Any]],
    work: ToolWork,
    episode: ExpertEpisode,
) -> tuple[Any, dict[str, Any], str, tuple[PlannedCall, ...]] | None:
    if not holder:
        return None
    reply = holder[0]
    payload = assistant_message_dict(reply)
    text = visible_assistant_text(payload)
    calls = tuple(
        _planned_calls(
            reply,
            text,
            messages,
            offered=frozenset(str(spec["function"]["name"]) for spec in episode.specs),
            consult=False,
            workspace_state=work.workspace_state,
            seen_call_ids=work.seen_call_ids,
        )
    )
    return reply, payload, text, calls


async def _call_free_stream_outcome(
    work: ToolWork,
    messages: list[dict[str, Any]],
    parts: tuple[Any, dict[str, Any], str],
    *,
    episode: ExpertEpisode,
    last_text: str,
    last_reasoning: str | None,
) -> tuple[_RoundOutcome, str, str | None]:
    reply, payload, text = parts
    outcome, visible = await _handle_call_free_round(
        work,
        messages,
        reply=reply,
        payload=payload,
        text=text,
        last_text=last_text,
        episode=episode,
    )
    if outcome is _RoundOutcome.CONTINUE:
        return _RoundOutcome.CONTINUE, "", last_reasoning
    reasoning = _reasoning_text(payload.get("reasoning_content")) or last_reasoning
    return outcome, visible, reasoning


def _visible_needs_yield(outcome: _RoundOutcome, streamed_any: bool, visible: str) -> bool:
    return outcome is _RoundOutcome.RETURN and not streamed_any and bool(visible.strip())


def _has_unstreamed_text(last_text: str, streamed_any: bool) -> bool:
    return bool(last_text.strip()) and not streamed_any


async def _drain_current_amendments() -> list[str]:
    queue = current_amendment_queue()
    if queue is None:
        return []
    return await drain_amendments(queue)


async def _apply_amendments(work: ToolWork, messages: list[dict[str, Any]]) -> bool:
    amendments = await _drain_current_amendments()
    if not amendments:
        return False
    for amendment in amendments:
        messages.append({"role": "user", "content": amendment})
    _remember_transcript(work, messages)
    return True
