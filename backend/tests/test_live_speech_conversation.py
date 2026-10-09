import asyncio
from types import SimpleNamespace

import pytest

from app.services.live_speech_backchannel import classify_utterance
from app.services.live_speech_coordinator import SpeechResponseCoordinator
from app.services.live_speech_phrases import (
    ProgressContext,
    generate_listener_phrase,
    generate_opening_phrase,
    generate_progress_phrase,
)
from app.services.live_speech_progress import (
    ToolProgress,
    bind_tool_progress,
    emit_tool_progress,
)
from app.services import live_speech_phrases
from app.schemas.workspace import WorkspaceState
from app.services.live_speech_runtime import LiveSpeechRuntime, LiveSpeechScope


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("mm", "backchannel"),
        ("just det", "backchannel"),
        ("jajust", "backchannel"),
        ("ja, precis", "backchannel"),
        ("okej", "backchannel"),
        ("stopp", "interruption"),
        ("nej", "interruption"),
        ("vänta", "interruption"),
        ("ja, men kan du läsa om", "interruption"),
        ("inte okej", "uncertain"),
        ("vad betyder det?", "new_question"),
    ],
)
def test_backchannel_rules(text: str, kind: str) -> None:
    assert classify_utterance(text) == kind


def test_urgent_wins_over_short_duration() -> None:
    assert classify_utterance("stopp", duration_ms=80) == "interruption"


def test_listener_echo_is_not_a_new_turn() -> None:
    assert classify_utterance("intressant", echoed="intressant") == "backchannel"


async def test_progress_hook_is_silent_without_voice_bind() -> None:
    seen: list[ToolProgress] = []

    async def handler(event: ToolProgress) -> None:
        seen.append(event)

    await emit_tool_progress("started", "read_source", remaining=1)
    assert seen == []
    with bind_tool_progress(handler):
        await emit_tool_progress("partial", "read_source", remaining=0, summary="ok")
    assert seen == [ToolProgress("partial", "read_source", 0, "ok")]


async def test_phrase_helpers_drop_silence_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def silent(_messages, _model, **_kwargs):
        return SimpleNamespace(phrase="", silence=True)

    monkeypatch.setattr(live_speech_phrases, "complete_structured", silent)
    assert await generate_listener_phrase("prompt", partial="hej", spoken="") is None
    assert await generate_opening_phrase("prompt", (("user", "hej"),)) is None

    async def boom(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(live_speech_phrases, "complete_structured", boom)
    assert (
        await generate_progress_phrase(
            "prompt",
            ProgressContext(kind="started", tool_name="read_source"),
        )
        is None
    )


async def test_coordinator_clips_aside_when_main_arrives() -> None:
    chunks: list[str] = []

    async def stream(text: str):
        chunks.append(text)
        yield b"\x00\x00"

    events: list[dict] = []

    async def emit_json(event: dict) -> None:
        events.append(event)

    async def emit_audio(_chunk: bytes) -> None:
        return None

    coordinator = SpeechResponseCoordinator(
        stream=stream,
        emit_json=emit_json,
        emit_audio=emit_audio,
        sample_rate=24_000,
        next_sequence=lambda: 1,
    )
    await coordinator.play_aside("Jag väntar in svaret.", "turn")
    coordinator.note_main_text()
    await coordinator.play_aside("Det här ska inte höras.", "turn")
    await coordinator.play_main("Här är svaret.", "turn")
    assert chunks == ["Jag väntar in svaret.", "Här är svaret."]
    assert coordinator.spoken_text == "Här är svaret."


async def test_coordinator_allows_progress_after_main() -> None:
    chunks: list[str] = []

    async def stream(text: str):
        chunks.append(text)
        yield b"\x00\x00"

    async def emit_json(_event: dict) -> None:
        return None

    async def emit_audio(_chunk: bytes) -> None:
        return None

    coordinator = SpeechResponseCoordinator(
        stream=stream,
        emit_json=emit_json,
        emit_audio=emit_audio,
        sample_rate=24_000,
        next_sequence=lambda: 1,
    )
    await coordinator.play_main("Första svaret.", "turn")
    coordinator.allow_progress()
    await coordinator.play_aside("Jag har fått en del.", "turn")
    assert chunks == ["Första svaret.", "Jag har fått en del."]


async def test_runtime_does_not_barge_in_on_audio_start() -> None:
    events: list[dict] = []

    async def emit_json(event: dict) -> None:
        events.append(event)

    async def emit_audio(_chunk: bytes) -> None:
        return None

    runtime = LiveSpeechRuntime(
        LiveSpeechScope(
            user_id="user",
            customer_id=1,
            workspace_id="workspace",
            expert_id="expert",
            language="sv",
            voice_id="voice",
            workspace_state=WorkspaceState(expert_id="expert"),
        ),
        emit_json=emit_json,
        emit_audio=emit_audio,
    )
    runtime._turn_task = asyncio.create_task(asyncio.sleep(30))
    runtime._turn_id = "old"
    await runtime.audio_started(1)
    assert runtime._turn_task is not None and not runtime._turn_task.done()
    runtime._turn_task.cancel()
    await asyncio.gather(runtime._turn_task, return_exceptions=True)


async def test_backchannel_final_does_not_start_a_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict] = []

    async def emit_json(event: dict) -> None:
        events.append(event)

    async def emit_audio(_chunk: bytes) -> None:
        return None

    runtime = LiveSpeechRuntime(
        LiveSpeechScope(
            user_id="user",
            customer_id=1,
            workspace_id="workspace",
            expert_id="expert",
            language="sv",
            voice_id="voice",
            workspace_state=WorkspaceState(expert_id="expert"),
        ),
        emit_json=emit_json,
        emit_audio=emit_audio,
    )
    started: list[str] = []

    async def begin(item_id: str, text: str) -> None:
        started.append(text)

    monkeypatch.setattr(runtime, "_begin_turn", begin)
    runtime._turn_task = asyncio.create_task(asyncio.sleep(30))
    runtime._turn_id = "old"
    from app.services.openai_live_transcription import TranscriptEvent

    await runtime._on_transcript(
        TranscriptEvent(kind="final", item_id="item", text="mm", code=None)
    )
    assert started == []
    assert any(event.get("type") == "transcript.backchannel" for event in events)
    runtime._turn_task.cancel()
    await asyncio.gather(runtime._turn_task, return_exceptions=True)


def _runtime(
    events: list[dict] | None = None,
    *,
    recent_turns: tuple[tuple[str, str], ...] = (),
) -> LiveSpeechRuntime:
    collected = events if events is not None else []

    async def emit_json(event: dict) -> None:
        collected.append(event)

    async def emit_audio(_chunk: bytes) -> None:
        return None

    return LiveSpeechRuntime(
        LiveSpeechScope(
            user_id="user",
            customer_id=1,
            workspace_id="workspace",
            expert_id="expert",
            language="sv",
            voice_id="voice",
            workspace_state=WorkspaceState(expert_id="expert"),
            prompts={
                "chat.expert.live_speech_listener": "lyssna",
                "chat.expert.live_speech_progress": "progress",
                "chat.expert.live_speech_opening": "öppna",
            },
            recent_turns=recent_turns,
        ),
        emit_json=emit_json,
        emit_audio=emit_audio,
    )


async def test_stopp_interrupts_the_active_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict] = []
    runtime = _runtime(events)
    cancelled: list[str] = []

    async def cancel(turn_id: str | None, reason: str) -> None:
        cancelled.append(reason)
        if runtime._turn_task is not None:
            runtime._turn_task.cancel()
            await asyncio.gather(runtime._turn_task, return_exceptions=True)
            runtime._turn_task = None

    started: list[str] = []

    async def begin(_item_id: str, spoken: str) -> None:
        started.append(spoken)

    monkeypatch.setattr(runtime, "cancel_turn", cancel)
    monkeypatch.setattr(runtime, "_begin_turn", begin)
    runtime._turn_task = asyncio.create_task(asyncio.sleep(30))
    runtime._turn_id = "old"
    from app.services.openai_live_transcription import TranscriptEvent

    await runtime._on_transcript(
        TranscriptEvent(kind="final", item_id="item", text="stopp", code=None)
    )
    assert cancelled == ["interruption"]
    assert started == ["stopp"]


async def test_waiting_phrase_is_suppressed_when_main_delta_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spoken: list[str] = []

    async def phrase(_prompt: str, context: ProgressContext) -> str | None:
        spoken.append(context.kind)
        return "Jag väntar in svaret."

    monkeypatch.setattr(
        "app.services.live_speech_cues.generate_progress_phrase",
        phrase,
    )
    monkeypatch.setattr(
        "app.config.settings.live_speech_waiting_suppress_ms",
        20,
    )
    runtime = _runtime()
    runtime._cues.start_waiting("turn")
    runtime._coordinator.note_main_text()
    await asyncio.sleep(0.05)
    assert spoken == []


async def test_text_cancel_leaves_the_session_open() -> None:
    runtime = _runtime()
    runtime._turn_task = asyncio.create_task(asyncio.sleep(30))
    runtime._turn_id = "old"
    await runtime.cancel_turn("old", "text_message")
    assert runtime._closed is False
    assert runtime._turn_task is None


async def test_listener_starts_after_threshold_and_silence_is_not_played(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def phrase(_prompt: str, *, partial: str, spoken: str) -> str | None:
        calls.append(partial)
        return None

    played: list[str] = []

    async def play(text: str, _turn_id: str) -> None:
        played.append(text)

    monkeypatch.setattr(
        "app.services.live_speech_cues.generate_listener_phrase",
        phrase,
    )
    monkeypatch.setattr("app.config.settings.live_speech_listener_after_ms", 15)
    runtime = _runtime()
    monkeypatch.setattr(runtime._coordinator, "play_aside", play)
    runtime._user_text_partial = "hej där"
    runtime._cues.restart_listener()
    await asyncio.sleep(0.005)
    assert calls == []
    await asyncio.sleep(0.03)
    assert calls == ["hej där"]
    assert played == []
    runtime._cues.stop_listener()


async def test_listener_phrase_is_ephemeral_and_commit_clips_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def phrase(_prompt: str, *, partial: str, spoken: str) -> str | None:
        return "mm intressant"

    monkeypatch.setattr(
        "app.services.live_speech_cues.generate_listener_phrase",
        phrase,
    )
    monkeypatch.setattr("app.config.settings.live_speech_listener_after_ms", 10)

    async def stream(text: str):
        yield b"\x00\x00"

    runtime = _runtime()
    runtime._coordinator._stream = stream
    runtime._user_text_partial = "en lång fråga"
    runtime._cues.restart_listener()
    await asyncio.sleep(0.03)
    assert runtime._coordinator.spoken_asides == ["mm intressant"]
    assert runtime._coordinator.spoken_text == ""
    runtime._cues.stop_listener()
    runtime._coordinator.drop_aside()
    await runtime._coordinator.play_aside("ska klippas", "listener")
    runtime._coordinator.note_main_text()
    await runtime._coordinator.play_aside("efter commit", "listener")
    assert runtime._coordinator.spoken_text == ""


async def test_progress_talk_covers_running_tool_and_mid_series_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts: list[ProgressContext] = []

    async def phrase(_prompt: str, context: ProgressContext) -> str | None:
        contexts.append(context)
        return f"status {context.kind}"

    played: list[str] = []

    async def play(text: str, _turn_id: str) -> None:
        played.append(text)

    monkeypatch.setattr(
        "app.services.live_speech_cues.generate_progress_phrase",
        phrase,
    )
    monkeypatch.setattr("app.config.settings.live_speech_tool_progress_ms", 10)
    events: list[dict] = []
    runtime = _runtime(events)
    runtime._turn_id = "turn"
    monkeypatch.setattr(runtime._coordinator, "play_aside", play)
    await runtime._cues.on_tool_progress(
        ToolProgress("started", "read_source", 2, "")
    )
    await runtime._cues.on_tool_progress(
        ToolProgress("partial", "read_source", 1, "första delen")
    )
    await asyncio.sleep(0.03)
    kinds = [context.kind for context in contexts]
    assert "started" in kinds
    assert "partial" in kinds
    partial = next(context for context in contexts if context.kind == "partial")
    assert partial.tool_name == "read_source"
    assert partial.remaining == 1
    assert partial.summary == "första delen"
    assert "status started" in played
    assert "status partial" in played
    assert runtime._coordinator.spoken_text == ""
    assert any(event.get("type") == "assistant.waiting" for event in events)


async def test_tool_calls_emit_progress_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.expert_async_tools import PlannedCall, ToolWork, run_tool_calls

    seen: list[ToolProgress] = []

    async def handler(event: ToolProgress) -> None:
        seen.append(event)

    async def run_one(call, _work):
        return f"resultat {call.name}"

    monkeypatch.setattr("app.services.expert_async_tools._run_one", run_one)
    work = ToolWork(
        persona_id="expert",
        mode="interview",
        actor_user_id="user",
        history=[],
        user_message="läs",
        calls=(
            PlannedCall("1", "read_source", {}),
            PlannedCall("2", "search", {}),
        ),
    )
    with bind_tool_progress(handler):
        blob, results = await run_tool_calls(work)
    assert [event.kind for event in seen] == ["started", "partial", "started", "partial"]
    assert seen[0].remaining == 2
    assert seen[1].remaining == 1
    assert seen[1].summary == "resultat read_source"
    assert seen[2].remaining == 1
    assert seen[3].remaining == 0
    assert "resultat read_source" in blob
    assert results == ("resultat read_source", "resultat search")


async def test_published_chat_followup_does_not_create_a_second_speech_reply() -> None:
    events: list[dict] = []
    runtime = _runtime(events)
    spoken: list[str] = []

    async def play_main(text: str, _turn_id: str) -> None:
        spoken.append(text)

    runtime._coordinator.play_main = play_main
    runtime._assistant_text = "Jag tar reda på det."
    payload = {
        "type": "thread.message",
        "thread_id": "expert",
        "mode": "character",
        "messages": [
            {"role": "assistant", "content": "Jag tar reda på det."},
            {"role": "assistant", "content": "Omsättningen är tolv."},
        ],
    }
    await runtime._on_library_event(payload)
    await runtime._on_library_event(payload)
    assert spoken == []


async def test_opening_uses_recent_turns_and_is_not_an_expert_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[tuple[str, str], ...]] = []

    async def opening(_prompt: str, turns: tuple[tuple[str, str], ...]) -> str | None:
        seen.append(turns)
        return "Vi var inne på avtalet."

    played: list[str] = []

    async def play(text: str, _turn_id: str) -> None:
        played.append(text)

    started: list[str] = []

    async def begin(item_id: str, text: str) -> None:
        started.append(text)

    events: list[dict] = []
    runtime = _runtime(
        events,
        recent_turns=(("user", "Kan du läsa avtalet?"), ("assistant", "Ja, sid tre.")),
    )
    monkeypatch.setattr(
        "app.services.live_speech_cues.generate_opening_phrase",
        opening,
    )
    monkeypatch.setattr(runtime._coordinator, "play_aside", play)
    monkeypatch.setattr(runtime, "_begin_turn", begin)
    runtime._cues.start_opening()
    await asyncio.sleep(0.02)
    assert seen == [(("user", "Kan du läsa avtalet?"), ("assistant", "Ja, sid tre."))]
    assert played == ["Vi var inne på avtalet."]
    assert started == []
    assert any(event.get("type") == "assistant.opening" for event in events)
    assert runtime._coordinator.spoken_text == ""


async def test_recent_interview_turns_are_oldest_first() -> None:
    from app.services.live_speech_admit import recent_interview_turns

    class Session:
        async def scalars(self, _statement):
            return SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(role="assistant", content="senast"),
                    SimpleNamespace(role="user", content="först"),
                ]
            )

    turns = await recent_interview_turns(Session(), "expert")
    assert turns == (("user", "först"), ("assistant", "senast"))
