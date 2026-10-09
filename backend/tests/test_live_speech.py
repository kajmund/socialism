import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.realtime.library_chat_broadcast import library_chat_broadcast
from app.schemas.live_speech import SessionStart, client_control_adapter
from app.schemas.workspace import WorkspaceState
from app.database.models import Persona, PersonaMessage
from app.services import live_speech_runtime, openai_live_transcription
from app.services.live_speech_history import persist_interrupted_voice_turn
from app.services.live_speech_runtime import LiveSpeechRuntime, LiveSpeechScope
from app.services.live_speech_sessions import LiveSpeechRegistry
from app.services.openai_live_transcription import (
    OpenAITranscriptionStream,
    parse_transcription_event,
)
from app.services.speech_segmenter import (
    SpeechSegmenter,
    VisibleSpeechText,
    normalize_for_speech,
    strip_voice_tags,
)


def test_live_speech_contract_rejects_model_mode_and_wrong_audio_format() -> None:
    with pytest.raises(ValidationError):
        client_control_adapter.validate_python(
            {
                "type": "session.start",
                "workspace_id": "w",
                "expert_id": "e",
                "language": "sv",
                "client_request_id": "r",
                "model_mode": "deep",
            }
        )
    parsed = client_control_adapter.validate_python(
        {
            "type": "session.start",
            "workspace_id": "w",
            "expert_id": "e",
            "language": "sv",
            "client_request_id": "r",
        }
    )
    assert isinstance(parsed, SessionStart)


def test_openai_transcription_parser_tracks_partial_and_final_by_item() -> None:
    partial = parse_transcription_event(
        {
            "type": "conversation.item.input_audio_transcription.delta",
            "item_id": "item-2",
            "delta": "Hej",
        }
    )
    final = parse_transcription_event(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "item-1",
            "transcript": "Första turen",
        }
    )
    assert partial is not None and (partial.kind, partial.item_id, partial.text) == (
        "partial",
        "item-2",
        "Hej",
    )
    assert final is not None and (final.kind, final.item_id, final.text) == (
        "final",
        "item-1",
        "Första turen",
    )


async def test_openai_transcription_uses_transcription_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect_kwargs: dict[str, object] = {}
    sent: list[dict] = []

    class Connection:
        async def send(self, event):
            sent.append(event)

        def __aiter__(self):
            async def events():
                if False:
                    yield None

            return events()

    connection = Connection()

    class Manager:
        async def __aenter__(self):
            return connection

        async def __aexit__(self, *_args):
            return None

    class Realtime:
        def connect(self, **kwargs):
            connect_kwargs.update(kwargs)
            return Manager()

    class Client:
        def __init__(self, *, api_key):
            assert api_key == "key"
            self.realtime = Realtime()

        async def close(self):
            return None

    monkeypatch.setattr(openai_live_transcription, "AsyncOpenAI", Client)
    stream = OpenAITranscriptionStream(
        api_key="key",
        model="gpt-live-transcribe",
        language="sv",
        on_event=lambda _event: asyncio.sleep(0),
    )
    await stream.start()
    await stream.close()

    assert connect_kwargs == {
        "extra_query": {"intent": "transcription"},
        "max_retries": 0,
    }
    assert sent[0]["session"]["audio"]["input"]["transcription"]["model"] == (
        "gpt-live-transcribe"
    )


def test_speech_segmenter_preserves_url_and_drops_cancelled_buffer() -> None:
    segmenter = SpeechSegmenter(first_target=20, max_chars=50)
    assert segmenter.push("Läs https://example.com/a.b först. Sedan ") == [
        "Läs https://example.com/a.b först."
    ]
    segmenter.cancel()
    assert segmenter.push("ska inte talas.") == []
    assert segmenter.finish() == []
    assert normalize_for_speech("[Källan](https://example.com) och `kod`.") == "Källan och kod."


def test_v4_delivery_tags_are_spoken_but_hidden_from_chat() -> None:
    visible = VisibleSpeechText()
    assert visible.push("Hej [laugh") == "Hej "
    assert visible.push("s] världen [R1].") == "världen [R1]."
    assert visible.finish() == ""
    assert strip_voice_tags("[laugh] [laughs] Hej [R1]. [sighs]") == "Hej [R1]."

    segmenter = SpeechSegmenter()
    segmenter.push("[laughs] Hej.")
    assert segmenter.finish() == ["[laughs] Hej."]


async def test_new_live_speech_lease_revokes_previous() -> None:
    registry = LiveSpeechRegistry()
    closed: list[str] = []

    async def close(reason: str) -> None:
        closed.append(reason)

    first = await registry.claim(
        user_id="u",
        customer_id=1,
        workspace_id="w",
        expert_id="e",
        language="sv",
        close=close,
    )
    second = await registry.claim(
        user_id="u",
        customer_id=1,
        workspace_id="w",
        expert_id="e",
        language="sv",
        close=close,
    )
    assert second.generation == first.generation + 1
    assert closed == ["replaced"]
    await registry.release(second)


async def test_registry_closes_all_sessions() -> None:
    registry = LiveSpeechRegistry()
    closed = asyncio.Event()

    async def close(_reason: str) -> None:
        closed.set()

    await registry.claim(
        user_id="u",
        customer_id=1,
        workspace_id="w",
        expert_id="e",
        language="sv",
        close=close,
    )
    await registry.close_all()
    assert closed.is_set()


async def test_interruption_reconciles_already_persisted_turn(client_db) -> None:
    _client, factory = client_db
    request_id = "voice-completed-before-cancel"
    async with factory() as session:
        persona_id = await session.scalar(select(Persona.id).limit(1))
        assert persona_id is not None
        session.add_all(
            [
                PersonaMessage(
                    persona_id=persona_id,
                    mode="interview",
                    role="user",
                    content="Fråga",
                    sme_expert_turn_request_id=request_id,
                ),
                PersonaMessage(
                    persona_id=persona_id,
                    mode="interview",
                    role="assistant",
                    content="Hela svaret som inte hann yttras",
                    sme_expert_turn_request_id=request_id,
                ),
            ]
        )
        await session.commit()

    await persist_interrupted_voice_turn(
        factory,
        request_id=request_id,
        fence=1,
        turn_id="voice-turn",
        persona_id=persona_id,
        user_text="Fråga",
        assistant_text="Yttrad del",
    )

    async with factory() as session:
        rows = list(
            await session.scalars(
                select(PersonaMessage)
                .where(PersonaMessage.sme_expert_turn_request_id == request_id)
                .order_by(PersonaMessage.id)
            )
        )
    assert [(row.role, row.content) for row in rows] == [
        ("user", "Fråga"),
        ("assistant", "Yttrad del"),
    ]
    assert all(row.voice_turn_id == "voice-turn" for row in rows)
    assert rows[1].interrupted is True


async def test_tts_can_acquire_only_connection_after_turn_admission(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'voice.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def admit(_factory, _scope, request_id: str, _spoken: str):
        async with factory() as session:
            await session.execute(text("select 1"))
        return SimpleNamespace(lease_token="token", fence=1)

    async def execute(*_args, on_token, **kwargs):
        assert engine.pool.checkedout() == 0
        assert kwargs["extra_system_prompt_key"] == "chat.expert.live_speech_delivery"
        transform = kwargs["assistant_reply_transform"]
        assert transform("[laughs] Hej.") == "Hej."
        await on_token("[laugh")
        await on_token("s] Hej.")
        return SimpleNamespace(reply="Hej.")

    class Tts:
        async def stream(self, segment, *, language):
            assert language == "sv"
            assert segment == "[laughs] Hej."
            assert engine.pool.checkedout() == 0
            async with factory() as probe:
                await probe.execute(text("select 1"))
            yield b"\x00\x00"

    monkeypatch.setattr(live_speech_runtime.jobs_service, "job_session_factory", lambda: factory)
    monkeypatch.setattr(live_speech_runtime, "admit_voice_turn", admit)
    monkeypatch.setattr(live_speech_runtime, "execute_expert_turn", execute)
    events: list[dict] = []

    async def emit_json(event):
        events.append(event)

    async def emit_audio(_chunk):
        assert engine.pool.checkedout() == 0

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
    runtime._tts = Tts()

    async def current_workspace_state(_factory, _scope):
        return runtime.scope.workspace_state

    monkeypatch.setattr(live_speech_runtime, "current_workspace_state", current_workspace_state)
    try:
        await runtime._run_turn("turn", "Hej")
        assert any(event["type"] == "assistant.text.final" for event in events)
    finally:
        await engine.dispose()


async def test_live_speech_forwards_model_traces_on_its_own_socket() -> None:
    events: list[dict] = []

    async def emit_json(event):
        events.append(event)

    async def emit_audio(_chunk):
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

    async def idle() -> None:
        return None

    runtime._stt.start = idle
    runtime._stt.close = idle
    await runtime.start()
    try:
        await library_chat_broadcast.publish(
            1,
            "expert",
            {
                "type": "model_trace",
                "thread_id": "expert",
                "workspace_id": "workspace",
                "target_user_id": "user",
                "kind": "message",
                "text": "Jag läser avtalet.",
            },
        )
        await library_chat_broadcast.publish(
            1,
            "other",
            {
                "type": "model_trace",
                "thread_id": "other",
                "kind": "message",
                "text": "Fel expert.",
            },
        )
        traces = [event for event in events if event.get("type") == "model_trace"]
        assert [event["text"] for event in traces] == ["Jag läser avtalet."]
    finally:
        await runtime.close("test")
