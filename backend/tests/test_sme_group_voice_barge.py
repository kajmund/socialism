"""Group voice barge-in uses the same rule and playback stop as one expert."""

from __future__ import annotations

import asyncio

from app.services.live_speech_backchannel import utterance_barge
from app.services.openai_live_transcription import TranscriptEvent
from app.services.sme_group_voice import GroupVoiceSession
from app.services.sme_group_voice_runtime import GroupVoiceAudioRuntime, GroupVoiceAudioScope


def _session() -> GroupVoiceSession:
    return GroupVoiceSession(
        panel_id="1",
        member_ids={"a"},
        member_names={"a": "Anna"},
    )


def _runtime(session: GroupVoiceSession, events: list[dict], audio: list[bytes] | None = None):
    async def emit(payload: dict) -> None:
        events.append(payload)

    async def emit_audio(pcm: bytes) -> None:
        if audio is not None:
            audio.append(pcm)

    return GroupVoiceAudioRuntime(
        session,
        GroupVoiceAudioScope(language="sv", voice_ids={"a": "voice"}),
        emit_json=emit,
        emit_audio=emit_audio,
    )


def test_the_group_uses_the_same_barge_rule_as_one_expert():
    assert utterance_barge("mm", final=False)[0] == "ignore"
    assert utterance_barge("vänta", final=False)[0] == "barge"
    assert utterance_barge("jag menar avtalet", final=False)[0] == "wait"
    assert utterance_barge("jag menar avtalet", final=True)[0] == "barge"


def test_ordinary_speech_stops_the_reply_after_the_same_confirm(monkeypatch):
    session = _session()
    session.grant_floor("a")
    events: list[dict] = []
    seen: list[str] = []

    async def confirm(_prompt: str, text: str) -> bool:
        seen.append(text)
        return True

    monkeypatch.setattr("app.services.live_speech_backchannel.confirm_barge", confirm)
    runtime = _runtime(session, events)

    async def run() -> None:
        await runtime._on_transcript(TranscriptEvent(kind="partial", text="mm"))
        assert session.floor == "a"
        assert runtime._barge.task is None
        await runtime._on_transcript(TranscriptEvent(kind="partial", text="jag menar avtalet"))
        assert session.floor == "a"
        assert runtime._barge.task is not None
        await runtime._barge.task

    asyncio.run(run())
    assert seen == ["jag menar avtalet"]
    assert session.floor is None
    assert any(event.get("type") == "assistant.cancelled" for event in events)


def test_talking_over_a_reply_stops_the_rest_of_the_audio(monkeypatch):
    session = _session()
    session.grant_floor("a")
    events: list[dict] = []
    audio: list[bytes] = []
    started = asyncio.Event()
    release = asyncio.Event()

    class FakeTts:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def stream(self, _text: str, *, language: str):
            assert language == "sv"
            yield b"\x00\x01"
            started.set()
            await release.wait()
            yield b"\x00\x02"

    monkeypatch.setattr("app.services.sme_group_voice_runtime.ElevenLabsTts", FakeTts)
    runtime = _runtime(session, events, audio)

    async def run() -> None:
        task = asyncio.create_task(runtime.speak_as("a", "Uppsägningstiden är sex månader."))

        async def interrupt() -> None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        runtime.interrupt_speech = interrupt
        await started.wait()
        await runtime._on_transcript(TranscriptEvent(kind="partial", text="vänta"))
        if not task.done():
            release.set()
            await task

    asyncio.run(run())
    assert audio == [b"\x00\x01"]
    assert any(event.get("type") == "assistant.cancelled" for event in events)
    assert session.floor is None
