import json
import time
from types import SimpleNamespace

import httpx
import pytest
from httpx import AsyncClient

from app.config import settings
from app.realtime.openai_live_relay import openai_live_relay_registry
from app.services.live_voice import (
    OPENAI_NATIVE_VOICES,
    LiveVoiceProviderError,
    LiveVoiceUnavailable,
    expert_live_voice,
    get_live_voice_provider,
)
from app.services.openai_live import (
    OpenAILiveVoiceProvider,
    create_openai_realtime_secret,
    realtime_session_payload,
)


def test_openai_voices_are_a_static_provider_list() -> None:
    assert "alloy" in OPENAI_NATIVE_VOICES
    assert "marin" in OPENAI_NATIVE_VOICES
    assert "cedar" in OPENAI_NATIVE_VOICES


def test_realtime_session_payload_includes_voice_tools_and_server_vad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_native_model", "gpt-realtime-2.1")
    payload = realtime_session_payload(
        "Server-owned expert instruction",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup_company",
                    "description": "Slå upp bolag",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        voice="shimmer",
    )
    session = payload["session"]
    assert session["type"] == "realtime"
    assert session["model"] == "gpt-realtime-2.1"
    assert session["instructions"] == "Server-owned expert instruction"
    assert session["audio"] == {
        "input": {
            "format": {"type": "audio/pcm", "rate": 24000},
            "transcription": {"model": settings.openai_native_transcription_model},
            "turn_detection": {
                "type": "server_vad",
                "create_response": True,
                "interrupt_response": True,
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 500,
            },
        },
        "output": {
            "format": {"type": "audio/pcm", "rate": 24000},
            "voice": "shimmer",
        },
    }
    assert session["tools"] == [
        {
            "type": "function",
            "name": "lookup_company",
            "description": "Slå upp bolag",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    assert payload["expires_after"] == {
        "anchor": "created_at",
        "seconds": settings.openai_native_token_ttl_seconds,
    }


def test_realtime_tools_flatten_chat_specs_and_skip_malformed() -> None:
    payload = realtime_session_payload(
        "Probe",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup_company",
                    "description": "Slå upp bolag",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {"type": "function", "function": {"description": "saknar namn"}},
            {"not": "a tool"},
        ],
        voice="alloy",
    )
    assert payload["session"]["tools"] == [
        {
            "type": "function",
            "name": "lookup_company",
            "description": "Slå upp bolag",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    empty = realtime_session_payload("Probe", tools=[], voice="alloy")
    assert "tools" not in empty["session"]


@pytest.mark.asyncio
async def test_create_openai_realtime_secret_mints_and_registers(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "openai_native_model", "gpt-realtime-test")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers["Authorization"]
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "value": "ek_ephemeral_secret",
                "expires_at": int(time.time()) + 600,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        secret, expires_at = await create_openai_realtime_secret(
            "Server-owned expert instruction",
            tools=[],
            voice="coral",
            client=http,
        )

    assert secret == "ek_ephemeral_secret"
    assert expires_at.endswith("Z")
    assert captured["auth"] == "Bearer openai-test-key"
    assert captured["url"] == "https://api.openai.com/v1/realtime/client_secrets"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["session"]["model"] == "gpt-realtime-test"
    assert payload["session"]["audio"]["output"]["voice"] == "coral"
    assert openai_live_relay_registry.take("ek_ephemeral_secret") is not None
    assert openai_live_relay_registry.take("ek_ephemeral_secret") is None


@pytest.mark.asyncio
async def test_create_openai_realtime_secret_accepts_a_saved_model_override(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "openai_api_key", "openai-test-key")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "value": "ek_ephemeral_secret",
                "expires_at": int(time.time()) + 600,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        await create_openai_realtime_secret(
            "Server-owned expert instruction",
            model="gpt-realtime-2",
            client=http,
        )

    assert captured["payload"]["session"]["model"] == "gpt-realtime-2"
    assert openai_live_relay_registry.take("ek_ephemeral_secret") == "gpt-realtime-2"


@pytest.mark.asyncio
async def test_openai_live_provider_session_points_at_the_relay(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "openai_api_key", "openai-test-key")
    monkeypatch.setattr(settings, "openai_relay_base_url", "ws://localhost:8000")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": "ek_ephemeral_secret",
                "expires_at": int(time.time()) + 600,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        session = await OpenAILiveVoiceProvider().create_session(
            "Server-owned expert instruction",
            initial_turn="Öppna telefonsamtalet nu.",
            tools=[],
            voice="shimmer",
            client=http,
        )

    assert session.provider == "openai"
    assert session.websocket_url == (
        "ws://localhost:8000/ws/openai-live?session=ek_ephemeral_secret"
    )
    assert session.model == settings.openai_native_model
    assert session.voice == "shimmer"
    assert session.expires_at.endswith("Z")
    assert session.initial_turn == "Öppna telefonsamtalet nu."
    assert session.audio.input_format == "pcm_24000"
    assert session.audio.output_format == "pcm_24000"
    assert session.client_init is None


@pytest.mark.asyncio
async def test_create_openai_realtime_secret_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(LiveVoiceUnavailable, match="OPENAI_API_KEY"):
        await create_openai_realtime_secret("Expert instruction")


@pytest.mark.asyncio
async def test_create_openai_realtime_secret_surfaces_provider_error(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "openai_api_key", "openai-test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid key")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(LiveVoiceProviderError, match="401"):
            await create_openai_realtime_secret("Expert instruction", client=http)


@pytest.mark.asyncio
async def test_create_openai_realtime_secret_rejects_missing_value(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "openai_api_key", "openai-test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"expires_at": 1_700_000_000})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(LiveVoiceProviderError, match="did not contain a value"):
            await create_openai_realtime_secret("Expert instruction", client=http)


@pytest.mark.asyncio
async def test_expert_saves_stt_correction_settings(client: AsyncClient):
    response = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "name": "Röstexpert",
            "occ": "Bolagsjurist",
            "district": "Göteborg",
            "profile": {
                "name": "Röstexpert",
                "kompetensomrade": "Bolagsrätt",
                "radgivningsstil": "Lugn och konkret",
                "yrkesbakgrund": "Bolagsjurist",
                "professionell_anekdot": "Ledde en komplicerad fusion.",
                "beskrivning": "Rådgivare inom bolagsrätt.",
            },
        },
    )
    assert response.status_code == 201, response.text
    expert = response.json()
    assert expert["stt_correction_enabled"] is None
    assert expert["stt_correction_timeout_seconds"] is None

    saved = await client.put(
        f"/personas/{expert['id']}",
        json={
            "live_voice_provider": "socialism",
            "stt_correction_enabled": False,
            "stt_correction_timeout_seconds": 3.5,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["stt_correction_enabled"] is False
    assert saved.json()["stt_correction_timeout_seconds"] == 3.5

    rejected = await client.put(
        f"/personas/{expert['id']}",
        json={"stt_correction_timeout_seconds": 0.1},
    )
    assert rejected.status_code == 422


def test_get_live_voice_provider_selects_openai(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "live_voice_provider", "openai")
    from app.services.openai_live import OpenAILiveVoiceProvider

    assert isinstance(get_live_voice_provider(), OpenAILiveVoiceProvider)


def test_expert_live_voice_accepts_saved_openai_voice_and_rejects_unknown(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "openai_native_voice", "alloy")
    persona = SimpleNamespace(
        live_voice_provider="openai",
        live_voice="shimmer",
    )
    assert expert_live_voice(persona) == ("openai", "shimmer")
    persona.live_voice = ""
    assert expert_live_voice(persona) == ("openai", "alloy")
    persona.live_voice = "not-a-voice"
    with pytest.raises(ValueError, match="unknown_openai_voice"):
        expert_live_voice(persona)


@pytest.mark.asyncio
async def test_expert_saves_openai_provider_and_lists_voices(client: AsyncClient):
    response = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "name": "Röstexpert",
            "occ": "Bolagsjurist",
            "district": "Göteborg",
            "profile": {
                "name": "Röstexpert",
                "kompetensomrade": "Bolagsrätt",
                "radgivningsstil": "Lugn och konkret",
                "yrkesbakgrund": "Bolagsjurist",
                "professionell_anekdot": "Ledde en komplicerad fusion.",
                "beskrivning": "Rådgivare inom bolagsrätt.",
            },
        },
    )
    assert response.status_code == 201, response.text
    expert = response.json()

    saved = await client.put(
        f"/personas/{expert['id']}",
        json={
            "live_voice_provider": "openai",
            "live_voice": "coral",
            "live_voice_model": "gpt-realtime-2.1",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["live_voice_provider"] == "openai"
    assert saved.json()["live_voice"] == "coral"
    assert saved.json()["live_voice_model"] == "gpt-realtime-2.1"

    voices = await client.get("/personas/live-voices", params={"provider": "openai"})
    assert voices.status_code == 200
    ids = {row["id"] for row in voices.json()}
    assert {"coral", "alloy", "marin"}.issubset(ids)

    models = await client.get("/personas/live-models", params={"provider": "openai"})
    assert models.status_code == 200
    model_ids = [row["id"] for row in models.json()]
    assert model_ids[0] == "gpt-realtime-2.1"
    assert "gpt-realtime-2" in model_ids

    rejected = await client.put(
        f"/personas/{expert['id']}",
        json={"live_voice_provider": "openai", "live_voice": "not-a-voice"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "unknown_openai_voice"

    rejected_model = await client.put(
        f"/personas/{expert['id']}",
        json={"live_voice_model": "not-a-model"},
    )
    assert rejected_model.status_code == 422
    assert rejected_model.json()["detail"] == "unknown_openai_model"
