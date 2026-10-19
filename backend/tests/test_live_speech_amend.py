import asyncio

from app.services.live_speech_amend import amend_turn


class _Coordinator:
    def __init__(self) -> None:
        self.interrupted = False

    def interrupt_playback(self) -> None:
        self.interrupted = True


class _Conversation:
    def ai_interrupted(self) -> None:
        return None


class _TurnTask:
    def __init__(self, done: bool = False) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done


def _runtime(turn_id: str | None) -> tuple[object, list[dict], asyncio.Queue[str]]:
    events: list[dict] = []

    async def emit(payload: dict) -> None:
        events.append(payload)

    runtime = type(
        "Runtime",
        (),
        {
            "_turn_task": _TurnTask(),
            "_turn_id": turn_id,
            "_amendment_queue": asyncio.Queue(),
            "_conversation": _Conversation(),
            "_coordinator": _Coordinator(),
        },
    )()
    runtime._emit_json = emit  # type: ignore[attr-defined]
    return runtime, events, runtime._amendment_queue  # type: ignore[attr-defined]


async def test_amend_turn_stops_playback_and_queues_without_cancelling():
    runtime, events, queue = _runtime("turn-1")
    await amend_turn(runtime, "turn-1", "fast avtalet är tre år")

    assert runtime._coordinator.interrupted is True  # type: ignore[attr-defined]
    assert queue.get_nowait() == "fast avtalet är tre år"
    assert any(event.get("type") == "assistant.amended" for event in events)
    assert runtime._turn_task.done() is False  # type: ignore[attr-defined]


async def test_amend_turn_ignores_a_stale_turn():
    runtime, events, queue = _runtime("other")
    await amend_turn(runtime, "turn-1", "fast avtalet är tre år")

    assert events == []
    assert queue.empty()
    assert runtime._coordinator.interrupted is False  # type: ignore[attr-defined]
