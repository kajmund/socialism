"""Streaming variant of the expert tool episode for live voice."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from app.services.expert_async_tools import (
    LibraryToolScope,
    PlannedCall,
    _bounded_call,
    _work,
    complete_tool_episode,
    run_tool_calls,
)
from app.services.expert_reasoning_turn import reroute_workspace_episode
from app.services.expert_tool_followup import stream_compose_tool_episode
from app.services.live_speech_progress import voice_turn_active
from app.services.passage_mark_claim import mark_followup_needed


async def stream_tool_episode(
    scope: LibraryToolScope,
    calls: tuple[PlannedCall, ...],
) -> AsyncIterator[str]:
    """Run the tool episode and stream the visible reply, token by token."""
    scope.defer(calls)
    calls = tuple(scope._calls)
    work = _work(scope, calls)
    blob, results = await run_tool_calls(work) if calls else ("", ())
    if blob and any(
        call.name in {"find_documents", "search_knowledge", "read_source"} for call in calls
    ):
        rerouted, require_tool = await reroute_workspace_episode(scope, blob)
        if rerouted and work.episode is not None:
            require_presentation = (
                require_tool
                and any(call.name == "find_documents" for call in calls)
            )
            workspace_names = {
                str(spec.get("function", {}).get("name") or "")
                for spec in scope.workspace_tool_catalog
            }
            non_workspace = tuple(
                spec
                for spec in work.episode.specs
                if str(spec.get("function", {}).get("name") or "") not in workspace_names
            )
            work.episode = replace(
                work.episode,
                specs=(*non_workspace, *rerouted),
                tool_choice="required" if require_presentation else "auto",
            )
            scope.episode = work.episode

    async def publish(client_calls: list[PlannedCall]) -> None:
        if client_calls:
            scope.defer(client_calls)

    reasoning_out: list[str | None] = []
    async for delta in stream_compose_tool_episode(
        work,
        blob,
        results,
        run_call=_bounded_call,
        publish=publish,
        reasoning_out=reasoning_out,
    ):
        yield delta
    episode = getattr(scope, "episode", None)
    if episode is not None:
        scope.episode = replace(episode, reasoning_content=reasoning_out[0])


async def stream_expert_tool_reply(
    ack: Any,
    scope: LibraryToolScope,
    specs: tuple[Any, ...],
) -> AsyncIterator[str]:
    """Yield an expert tool-episode reply; streams the episode in a voice turn."""
    names = [call.name for call in ack.calls]
    if ack.calls or mark_followup_needed(ack.text, names, specs):
        if voice_turn_active():
            # A voice turn streams the reply as the tool episode generates it, so
            # the first content audio does not wait for the whole episode.
            produced = bool(ack.text.strip())
            if ack.text.strip():
                yield f"{ack.text.strip()} "
            async for delta in stream_tool_episode(scope, ack.calls):
                produced = True
                yield delta
            if not produced:
                raise ValueError("Expert tool episode produced no reply")
            return
        reply = await complete_tool_episode(scope, ack.calls)
        if reply:
            yield reply
        else:
            raise ValueError("Expert tool episode produced no reply")
        return
    if ack.text:
        yield ack.text
    else:
        raise ValueError("Expert tool episode produced no reply")
