"""Second-pass offline transcription and settings-driven STT hints."""

import asyncio

import pytest

from app.config import settings
from app.services.live_speech_offline import OfflineTranscriber, pcm_to_wav
from app.services.live_speech_runtime import LiveSpeechRuntime
from app.services.live_speech_scope import LiveSpeechScope
from app.services.openai_live_transcription import (
    clean_keywords,
    transcription_session,
)
from app.schemas.workspace import WorkspaceState


def test_pcm_to_wav_builds_a_44_byte_mono_pcm_header() -> None:
    wav = pcm_to_wav(b"\x00\x00\x01\x00")
    assert len(wav) == 48
    assert wav[:4] == b"RIFF"
    assert int.from_bytes(wav[4:8], "little") == 40
    assert wav[8:12] == b"WAVE"
    assert wav[36:40] == b"data"
    assert int.from_bytes(wav[24:28], "little") == 24000
    assert int.from_bytes(wav[40:44], "little") == 4


def test_transcription_session_reads_delay_and_keyword_cap_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "live_speech_stt_delay", "normal")
    monkeypatch.setattr(settings, "live_speech_stt_keyword_limit", 2)
    payload = transcription_session(
        model="gpt-live-transcribe",
        language="sv",
        prompt="",
        keywords=["ett", "två", "tre"],
        noise_reduction="near_field",
    )
    transcription = payload["session"]["audio"]["input"]["transcription"]
    assert transcription["delay"] == "normal"
    assert transcription["keywords"] == ["ett", "två"]
    assert clean_keywords(["a", "b", "c"]) == ["a", "b"]


class _Transcription:
    def __init__(self, text: str) -> None:
        self.text = text


class _SlowTranscriptions:
    async def create(self, **_kwargs):
        await asyncio.sleep(60)
        return _Transcription("Aldrig.")


class _RaisingTranscriptions:
    async def create(self, **_kwargs):
        raise RuntimeError("provider down")


class _FakeClient:
    def __init__(self, *, api_key: str, transcriptions) -> None:
        assert api_key == settings.openai_api_key
        self.audio = type("Audio", (), {"transcriptions": transcriptions})()

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_offline_transcriber_returns_text_and_sends_wav(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Transcriptions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return _Transcription("  Avtalslagen paragraf tre. ")

    monkeypatch.setattr(
        "app.services.live_speech_offline.AsyncOpenAI",
        lambda *, api_key: _FakeClient(api_key=api_key, transcriptions=Transcriptions()),
    )
    transcriber = OfflineTranscriber()
    assert transcriber.enabled is True
    text = await transcriber.transcribe(b"\x00\x00\x01\x00", "sv")
    assert text == "Avtalslagen paragraf tre."
    assert captured["model"] == (
        settings.live_speech_offline_stt_model or settings.live_speech_stt_model
    )
    assert captured["language"] == "sv"
    filename, content, content_type = captured["file"]
    assert filename == "utterance.wav"
    assert content_type == "audio/wav"
    assert content[:4] == b"RIFF"
    assert len(content) == len(b"\x00\x00\x01\x00") + 44
    await transcriber.aclose()


@pytest.mark.asyncio
async def test_offline_pass_reuses_the_streaming_model_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Transcriptions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return _Transcription("Text.")

    monkeypatch.setattr(settings, "live_speech_offline_stt_model", "")
    monkeypatch.setattr(settings, "live_speech_stt_model", "gpt-live-transcribe")
    monkeypatch.setattr(
        "app.services.live_speech_offline.AsyncOpenAI",
        lambda *, api_key: _FakeClient(api_key=api_key, transcriptions=Transcriptions()),
    )
    await OfflineTranscriber().transcribe(b"\x00\x00", "sv")
    assert captured["model"] == "gpt-live-transcribe"


@pytest.mark.asyncio
async def test_offline_transcriber_degrades_to_none_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "live_speech_offline_timeout_seconds", 0.05)
    monkeypatch.setattr(
        "app.services.live_speech_offline.AsyncOpenAI",
        lambda *, api_key: _FakeClient(
            api_key=api_key, transcriptions=_SlowTranscriptions()
        ),
    )
    assert await OfflineTranscriber().transcribe(b"\x00\x00", "sv") is None


@pytest.mark.asyncio
async def test_offline_transcriber_degrades_to_none_on_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.live_speech_offline.AsyncOpenAI",
        lambda *, api_key: _FakeClient(
            api_key=api_key, transcriptions=_RaisingTranscriptions()
        ),
    )
    assert await OfflineTranscriber().transcribe(b"\x00\x00", "sv") is None


def test_offline_transcriber_disabled_without_flag_or_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "live_speech_two_pass_enabled", False)
    monkeypatch.setattr(settings, "openai_api_key", "key")
    assert OfflineTranscriber().enabled is False
    monkeypatch.setattr(settings, "live_speech_two_pass_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert OfflineTranscriber().enabled is False


class _Metrics:
    def __init__(self) -> None:
        self.entries: list[tuple[str, float]] = []

    def add(self, phase: str, milliseconds: float) -> None:
        self.entries.append((phase, milliseconds))


def _bare_runtime() -> LiveSpeechRuntime:
    runtime = LiveSpeechRuntime.__new__(LiveSpeechRuntime)
    runtime._metrics = _Metrics()
    runtime._commit_at = 1.0
    runtime._offline_task = None
    runtime._correction_history = []
    runtime.scope = LiveSpeechScope(
        user_id="user",
        customer_id=1,
        workspace_id="workspace",
        expert_id="expert",
        language="sv",
        voice_id="voice",
        workspace_state=WorkspaceState(expert_id="expert"),
        correction_enabled=False,
    )
    return runtime


@pytest.mark.asyncio
async def test_canonical_text_prefers_the_offline_pass() -> None:
    runtime = _bare_runtime()

    async def offline() -> str:
        return "Avtalslagen paragraf tre."

    runtime._offline_task = asyncio.create_task(offline())
    assert (
        await runtime._canonical_text("Avtalslagen paragraf tre.")
        == "Avtalslagen paragraf tre."
    )


@pytest.mark.asyncio
async def test_canonical_text_keeps_streaming_when_offline_matches_or_fails() -> None:
    runtime = _bare_runtime()

    async def same() -> str:
        return "Samma text."

    runtime._offline_task = asyncio.create_task(same())
    assert await runtime._canonical_text("Samma text.") == "Samma text."

    async def empty() -> str | None:
        return None

    runtime._offline_task = asyncio.create_task(empty())
    assert await runtime._canonical_text("Bara streaming.") == "Bara streaming."


@pytest.mark.asyncio
async def test_canonical_text_falls_back_when_the_grace_window_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "live_speech_offline_grace_seconds", 0.0)
    runtime = _bare_runtime()
    slow = asyncio.create_task(asyncio.sleep(30))
    runtime._offline_task = slow
    assert await runtime._canonical_text("Streamad text.") == "Streamad text."
    slow.cancel()


def _runtime_with_fake_offline(text: str | None) -> tuple[LiveSpeechRuntime, "FakeOffline"]:
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
        emit_json=_noop,
        emit_audio=_noop,
    )
    fake = FakeOffline(text)
    runtime._offline = fake
    runtime._stt = _FakeStt()
    return runtime, fake


async def _noop(*_args) -> None:
    return None


class _FakeStt:
    async def append(self, _frame: bytes) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def clear(self) -> None:
        return None

    async def close(self) -> None:
        return None


class FakeOffline:
    enabled = True

    def __init__(self, text: str | None) -> None:
        self.text = text
        self.pcm: bytes | None = None
        self.language: str | None = None

    async def transcribe(self, pcm: bytes, language: str) -> str | None:
        self.pcm = pcm
        self.language = language
        return self.text

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_committed_utterance_uses_the_offline_pass_as_canonical_text() -> None:
    runtime, fake = _runtime_with_fake_offline("Avtalslagen paragraf tre.")
    begun: list[str] = []

    async def begin(_item_id: str, text: str) -> None:
        begun.append(text)

    runtime._begin_turn = begin
    try:
        await runtime.audio_started(1)
        await runtime.append_audio(b"\x00\x00" * 200)
        await runtime.commit_audio(2, None)
        await runtime._on_final_transcript("pending", "Fel transkription.")
        assert begun == ["Avtalslagen paragraf tre."]
        assert fake.pcm == b"\x00\x00" * 200
        assert fake.language == "sv"
    finally:
        await runtime.close("test")


@pytest.mark.asyncio
async def test_offline_pass_rescues_an_empty_streaming_transcript() -> None:
    runtime, _fake = _runtime_with_fake_offline("Ändå hört.")
    begun: list[str] = []

    async def begin(_item_id: str, text: str) -> None:
        begun.append(text)

    runtime._begin_turn = begin
    try:
        await runtime.audio_started(1)
        await runtime.append_audio(b"\x00\x00" * 200)
        await runtime.commit_audio(2, None)
        await runtime._on_final_transcript("pending", "  ")
        assert begun == ["Ändå hört."]
    finally:
        await runtime.close("test")


@pytest.mark.asyncio
async def test_empty_streaming_and_offline_keeps_the_retryable_error() -> None:
    runtime, _fake = _runtime_with_fake_offline(None)
    errors: list[tuple[str, str, bool]] = []

    async def error(code: str, message: str, retryable: bool) -> None:
        errors.append((code, message, retryable))

    runtime._error = error
    try:
        await runtime.audio_started(1)
        await runtime.append_audio(b"\x00\x00" * 200)
        await runtime.commit_audio(2, None)
        await runtime._on_final_transcript("pending", "")
        assert errors == [("empty_transcript", "No speech was transcribed", True)]
    finally:
        await runtime.close("test")
