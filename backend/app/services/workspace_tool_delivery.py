"""One delivery path for workspace tool calls across text and voice channels.

Each channel supplies a turn correlation id and, where it has one, a ``current``
predicate. A stale callback (cancelled turn, lost floor) delivers nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from app.services.sme_open_document import workspace_tool_delivery_key

EmitJson = Callable[[dict[str, Any]], Awaitable[None]]
Current = Callable[[], bool]
Deliver = Callable[[list[dict[str, Any]]], Awaitable[None]]


class VoiceTurnRuntime(Protocol):
    """The live-speech runtime state that decides whether a turn is still current."""

    _emit_json: EmitJson
    _turn_id: str | None
    _turn_cancel: Any


class WorkspaceToolDelivery:
    """Emit each workspace tool call once, for the channel that still owns it."""

    def __init__(
        self,
        emit: EmitJson,
        *,
        event_type: str = "workspace.tool",
        turn_id: str | None = None,
        expert_id: str | None = None,
        current: Current | None = None,
        envelope: dict[str, Any] | None = None,
    ) -> None:
        self._emit = emit
        self._event_type = event_type
        self._turn_id = turn_id
        self._expert_id = expert_id
        self._current = current
        self._envelope = dict(envelope or {})
        self._sent: set[tuple[str, ...]] = set()

    async def deliver(self, calls: list[dict[str, Any]]) -> None:
        for call in calls:
            if self._current is not None and not self._current():
                return
            arguments = dict(call.get("arguments") or {})
            name = str(call.get("name") or "")
            if not name:
                continue
            key = workspace_tool_delivery_key(name, arguments, self._expert_id)
            if key in self._sent:
                continue
            self._sent.add(key)
            if name == "focus_anchor" and self._expert_id:
                arguments["expert_id"] = self._expert_id
            payload: dict[str, Any] = {
                "type": self._event_type,
                "name": name,
                "arguments": arguments,
                **self._envelope,
            }
            if self._turn_id:
                payload["turn_id"] = self._turn_id
            await self._emit(payload)


def voice_tool_callback(runtime: VoiceTurnRuntime, turn_id: str) -> Deliver:
    """The callback 1:1 voice hands to the expert turn.

    The callback may run after a barge-in; only the turn that still owns the
    socket may deliver.
    """

    async def callback(calls: list[dict[str, Any]]) -> None:
        await WorkspaceToolDelivery(
            runtime._emit_json,
            turn_id=turn_id,
            current=lambda: turn_id == runtime._turn_id
            and not runtime._turn_cancel.is_set(),
        ).deliver(calls)

    return callback
