import json

import httpx
import pytest
from httpx import AsyncClient

from app.config import settings
from app.services.elevenlabs_live import (
    ElevenLabsLiveVoiceProvider,
    build_elevenlabs_client_init,
    create_elevenlabs_signed_url,
    resolve_elevenlabs_tool_ids,
)
from app.services.live_voice import (
    LiveVoiceProviderError,
    LiveVoiceUnavailable,
    create_live_voice_session,
)


def _enable_elevenlabs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "live_voice_provider", "elevenlabs")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "xi-test-key")
    monkeypatch.setattr(settings, "elevenlabs_agent_id", "agent_shell")
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice_swedish")
    monkeypatch.setattr(settings, "elevenlabs_base_url", "https://api.elevenlabs.io")
    monkeypatch.setattr(settings, "elevenlabs_tool_ids", {})
    monkeypatch.setattr(settings, "elevenlabs_signed_url_ttl_seconds", 900)


async def _create_expert(client: AsyncClient) -> dict[str, object]:
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
    return response.json()


@pytest.mark.asyncio
async def test_elevenlabs_signed_url_mints_session(
    monkeypatch: pytest.MonkeyPatch,
):
    _enable_elevenlabs(monkeypatch)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers["xi-api-key"]
        return httpx.Response(
            200,
            json={
                "signed_url": (
                    "wss://api.elevenlabs.io/v1/convai/conversation"
                    "?agent_id=agent_shell&token=signed-token"
                )
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as el_client:
        session = await ElevenLabsLiveVoiceProvider().create_session(
            "Du är bolagsjuristen.",
            initial_turn="Öppna telefonsamtalet nu.",
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
            client=el_client,
        )

    assert captured["api_key"] == "xi-test-key"
    assert "agent_id=agent_shell" in str(captured["url"])
    assert session.provider == "elevenlabs"
    assert session.websocket_url.endswith("token=signed-token")
    assert session.model == "agent_shell"
    assert session.voice == "voice_swedish"
    assert session.initial_turn == "Öppna telefonsamtalet nu."
    assert session.audio.input_format == "pcm_16000"
    assert session.audio.output_format == "pcm_16000"
    assert session.expires_at.endswith("Z")
    assert session.client_init == {
        "type": "conversation_initiation_client_data",
        "conversation_config_override": {
            "agent": {
                "prompt": {"prompt": "Du är bolagsjuristen."},
                "first_message": "Öppna telefonsamtalet nu.",
                "language": "sv",
            },
            "tts": {"voice_id": "voice_swedish"},
        },
    }


@pytest.mark.asyncio
async def test_elevenlabs_signed_url_includes_tool_ids_when_mapped(
    monkeypatch: pytest.MonkeyPatch,
):
    _enable_elevenlabs(monkeypatch)
    monkeypatch.setattr(
        settings,
        "elevenlabs_tool_ids",
        {"lookup_company": "tool_lookup", "search_wiki": "tool_wiki"},
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"signed_url": "wss://api.elevenlabs.io/v1/convai/conversation?token=x"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as el_client:
        session = await ElevenLabsLiveVoiceProvider().create_session(
            "Prompt",
            initial_turn="Hej",
            tools=[
                {
                    "type": "function",
                    "function": {"name": "lookup_company", "parameters": {}},
                },
                {
                    "type": "function",
                    "function": {"name": "search_wiki", "parameters": {}},
                },
            ],
            client=el_client,
        )

    prompt = session.client_init["conversation_config_override"]["agent"]["prompt"]
    assert prompt["tool_ids"] == ["tool_lookup", "tool_wiki"]


@pytest.mark.asyncio
async def test_elevenlabs_signed_url_fails_loud_when_tool_map_incomplete(
    monkeypatch: pytest.MonkeyPatch,
):
    _enable_elevenlabs(monkeypatch)
    monkeypatch.setattr(settings, "elevenlabs_tool_ids", {"lookup_company": "tool_lookup"})

    with pytest.raises(LiveVoiceUnavailable, match="search_wiki"):
        await ElevenLabsLiveVoiceProvider().create_session(
            "Prompt",
            initial_turn="Hej",
            tools=[
                {
                    "type": "function",
                    "function": {"name": "lookup_company", "parameters": {}},
                },
                {
                    "type": "function",
                    "function": {"name": "search_wiki", "parameters": {}},
                },
            ],
        )


@pytest.mark.asyncio
async def test_elevenlabs_signed_url_requires_credentials(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    monkeypatch.setattr(settings, "elevenlabs_agent_id", "agent_shell")
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice_swedish")
    with pytest.raises(LiveVoiceUnavailable, match="ELEVENLABS_API_KEY"):
        await create_elevenlabs_signed_url()

    monkeypatch.setattr(settings, "elevenlabs_api_key", "xi-test-key")
    monkeypatch.setattr(settings, "elevenlabs_agent_id", "")
    with pytest.raises(LiveVoiceUnavailable, match="ELEVENLABS_AGENT_ID"):
        await create_elevenlabs_signed_url()

    monkeypatch.setattr(settings, "elevenlabs_agent_id", "agent_shell")
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "")
    with pytest.raises(LiveVoiceUnavailable, match="ELEVENLABS_VOICE_ID"):
        await ElevenLabsLiveVoiceProvider().create_session(
            "Prompt",
            initial_turn="Hej",
            tools=[],
        )


@pytest.mark.asyncio
async def test_elevenlabs_signed_url_surfaces_provider_error(
    monkeypatch: pytest.MonkeyPatch,
):
    _enable_elevenlabs(monkeypatch)
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(401, text="invalid api key")
    )
    async with httpx.AsyncClient(transport=transport) as el_client:
        with pytest.raises(LiveVoiceProviderError, match="401.*invalid api key"):
            await create_elevenlabs_signed_url(client=el_client)


@pytest.mark.asyncio
async def test_create_live_voice_session_does_not_fall_back_to_gemini(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "live_voice_provider", "elevenlabs")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    monkeypatch.setattr(settings, "elevenlabs_agent_id", "")
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "")
    monkeypatch.setattr(settings, "google_api_key", "google-test-key")
    with pytest.raises(LiveVoiceUnavailable, match="ELEVENLABS_API_KEY"):
        await create_live_voice_session(
            "Expert instruction",
            initial_turn="Öppna.",
            tools=[],
        )


@pytest.mark.asyncio
async def test_live_token_endpoint_uses_elevenlabs_when_configured(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    expert = await _create_expert(client)
    _enable_elevenlabs(monkeypatch)

    async def fake_signed_url(*, client: httpx.AsyncClient | None = None) -> str:
        return "wss://api.elevenlabs.io/v1/convai/conversation?token=ep"

    monkeypatch.setattr(
        "app.services.elevenlabs_live.create_elevenlabs_signed_url",
        fake_signed_url,
    )
    response = await client.post(f"/personas/{expert['id']}/live-token")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "elevenlabs"
    assert body["websocket_url"].endswith("token=ep")
    assert body["voice"] == "voice_swedish"
    assert body["client_init"]["type"] == "conversation_initiation_client_data"
    prompt = body["client_init"]["conversation_config_override"]["agent"]["prompt"]
    assert "prompt" in prompt
    assert "INTERVJU" in prompt["prompt"]
    assert body["client_init"]["conversation_config_override"]["agent"][
        "first_message"
    ] == body["initial_turn"]


@pytest.mark.asyncio
async def test_live_token_endpoint_fails_loudly_without_elevenlabs_key(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    expert = await _create_expert(client)
    monkeypatch.setattr(settings, "live_voice_provider", "elevenlabs")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    monkeypatch.setattr(settings, "elevenlabs_agent_id", "agent_shell")
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice_swedish")

    response = await client.post(f"/personas/{expert['id']}/live-token")

    assert response.status_code == 503
    assert response.json()["detail"] == "ELEVENLABS_API_KEY is not configured"


def test_resolve_elevenlabs_tool_ids_omits_override_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "elevenlabs_tool_ids", {})
    assert resolve_elevenlabs_tool_ids(["lookup_company"]) is None


def test_build_elevenlabs_client_init_includes_prompt_and_first_message(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice_swedish")
    payload = build_elevenlabs_client_init(
        "System",
        "Öppna.",
        tool_ids=["tool_lookup"],
    )
    assert payload["type"] == "conversation_initiation_client_data"
    agent = payload["conversation_config_override"]["agent"]
    assert agent["prompt"] == {"prompt": "System", "tool_ids": ["tool_lookup"]}
    assert agent["first_message"] == "Öppna."
    assert json.dumps(payload)
