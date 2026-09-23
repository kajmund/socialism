import json
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

import httpx
import pytest
from httpx import AsyncClient

from app.api import personas as personas_api
from app.config import settings
from app.schemas.domain import LiveVoiceAudioOut, PersonaLiveTokenOut
from app.services.expertgranskning.memory import ExpertMemoryHit
from app.services.gemini_live import (
    GEMINI_LIVE_WEBSOCKET_URL,
    GeminiLiveProviderError,
    GeminiLiveUnavailable,
    GeminiLiveVoiceProvider,
    create_gemini_live_token,
    openai_to_gemini_tools,
)
from app.services.live_voice import LiveVoiceUnavailable, create_live_voice_session
from app.services.live_voice_context import recent_voice_memories
from tests.conftest import USER_USER_ID, mint_access_token


def _gemini_session_out() -> PersonaLiveTokenOut:
    return PersonaLiveTokenOut(
        provider="gemini",
        websocket_url=f"{GEMINI_LIVE_WEBSOCKET_URL}?access_token=auth_tokens/test",
        model="gemini-3.8-live",
        voice="Algenib",
        expires_at="2026-09-20T00:20:00Z",
        initial_turn="Öppna telefonsamtalet nu.",
        audio=LiveVoiceAudioOut(
            input_format="pcm_16000",
            output_format="pcm_24000",
        ),
        client_init=None,
    )


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
async def test_live_token_for_expert_uses_server_built_prompt(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    expert = await _create_expert(client)
    captured: list[str] = []
    captured_tools: list[list[dict[str, object]]] = []

    async def fake_create_session(
        system_instruction: str,
        *,
        initial_turn: str,
        tools: list[dict[str, object]],
        client: httpx.AsyncClient | None = None,
    ):
        captured.append(system_instruction)
        captured_tools.append(tools)
        return _gemini_session_out().model_copy(update={"initial_turn": initial_turn})

    monkeypatch.setattr(personas_api, "create_live_voice_session", fake_create_session)
    response = await client.post(f"/personas/{expert['id']}/live-token")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "gemini"
    assert body["websocket_url"].endswith("access_token=auth_tokens/test")
    assert body["model"] == "gemini-3.8-live"
    assert body["voice"] == "Algenib"
    assert body["expires_at"] == "2026-09-20T00:20:00Z"
    assert body["initial_turn"] == "Öppna telefonsamtalet nu."
    assert body["audio"] == {
        "input_format": "pcm_16000",
        "output_format": "pcm_24000",
    }
    assert body["client_init"] is None
    assert "token" not in body
    assert len(captured) == 1
    assert "du är den här experten" in captured[0]
    assert str(expert["name"]) in captured[0]
    assert "Bolagsrätt" in captured[0]
    assert '"current_user"' in captured[0]
    assert '"customer"' in captured[0]
    assert "Ja, det är" in captured[0]
    assert {spec["function"]["name"] for spec in captured_tools[0]} == {
        "search_companies",
        "lookup_company",
        "validate_orgnr",
        "search_duckduckgo",
        "search_wiki",
        "start_research",
        "get_actor_context",
        "propose_actor_context_update",
    }


@pytest.mark.asyncio
async def test_live_token_rejects_regular_persona(client: AsyncClient):
    persona = await client.post(
        "/personas",
        json={
            "kind": "persona",
            "name": "Test Persona",
            "age": 40,
            "occ": "Lärare",
            "district": "Malmö",
        },
    )
    assert persona.status_code == 201

    response = await client.post(f"/personas/{persona.json()['id']}/live-token")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_live_token_enforces_customer_scope(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    expert = await _create_expert(client)

    async def fake_create_session(
        _system_instruction: str,
        *,
        initial_turn: str,
        tools: list[dict[str, object]],
        client: httpx.AsyncClient | None = None,
    ):
        assert tools
        return _gemini_session_out()

    monkeypatch.setattr(personas_api, "create_live_voice_session", fake_create_session)
    user_token = mint_access_token(sub=USER_USER_ID, email="user@test.local")
    response = await client.post(
        f"/personas/{expert['id']}/live-token",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "kund_access_denied"


@pytest.mark.asyncio
async def test_live_token_endpoint_fails_loudly_without_google_key(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    expert = await _create_expert(client)
    monkeypatch.setattr(settings, "live_voice_provider", "gemini")
    monkeypatch.setattr(settings, "google_api_key", "")

    response = await client.post(f"/personas/{expert['id']}/live-token")

    assert response.status_code == 503
    assert response.json()["detail"] == "GOOGLE_API_KEY is not configured"


@pytest.mark.asyncio
async def test_live_token_endpoint_maps_google_failure_to_bad_gateway(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    expert = await _create_expert(client)

    async def fail_create_session(
        _system_instruction: str,
        *,
        initial_turn: str,
        tools: list[dict[str, object]],
        client: httpx.AsyncClient | None = None,
    ):
        assert tools
        raise GeminiLiveProviderError("Gemini Live token request failed (429): quota")

    monkeypatch.setattr(personas_api, "create_live_voice_session", fail_create_session)
    response = await client.post(f"/personas/{expert['id']}/live-token")

    assert response.status_code == 502
    assert "429" in response.json()["detail"]


@pytest.mark.asyncio
async def test_live_memory_is_written_as_background_work(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    expert = await _create_expert(client)
    captured: list[dict[str, object]] = []

    async def fake_remember(persona, **kwargs):
        captured.append({"persona_id": persona.id, **kwargs})
        return []

    monkeypatch.setattr(personas_api, "remember_expert_chat_turn", fake_remember)
    response = await client.post(
        f"/personas/{expert['id']}/live-memory",
        json={
            "session_id": "voice-session-1",
            "user_message": "Vad minns du från mötet?",
            "assistant_message": "Jag minns att tidsplanen flyttades.",
        },
    )

    assert response.status_code == 202, response.text
    assert captured == [
        {
            "persona_id": expert["id"],
            "message": "Vad minns du från mötet?",
            "reply": "Jag minns att tidsplanen flyttades.",
            "image_sha256": None,
            "session_id": "voice-session-1",
        }
    ]


@pytest.mark.asyncio
async def test_live_tool_runs_allowed_actor_context_and_rejects_disabled_tool(
    client: AsyncClient,
):
    expert = await _create_expert(client)
    request = {
        "session_id": "voice-session-tools",
        "name": "get_actor_context",
        "arguments": {},
        "history": [],
        "user_message": "Vem talar du med?",
    }

    allowed = await client.post(
        f"/personas/{expert['id']}/live-tool",
        json=request,
    )
    assert allowed.status_code == 200, allowed.text
    actor_context = json.loads(allowed.json()["result"])
    assert actor_context["current_user"]["id"]
    assert actor_context["customer"]["id"]

    disabled = await client.put(
        f"/personas/{expert['id']}",
        json={"tools": []},
    )
    assert disabled.status_code == 200
    rejected = await client.post(
        f"/personas/{expert['id']}/live-tool",
        json=request,
    )
    assert rejected.status_code == 403
    assert rejected.json()["detail"] == "voice_tool_not_allowed"


def test_recent_voice_memories_uses_four_hour_window():
    now = datetime(2026, 9, 20, 2, 0, tzinfo=UTC)
    recent = ExpertMemoryHit(
        id="recent",
        text="Nytt minne",
        source="persona_chat",
        metadata={},
        updated_at=(now - timedelta(hours=3, minutes=59)).isoformat(),
    )
    old = ExpertMemoryHit(
        id="old",
        text="Gammalt minne",
        source="persona_chat",
        metadata={},
        updated_at=(now - timedelta(hours=4, seconds=1)).isoformat(),
    )

    assert recent_voice_memories([old, recent], now=now) == [recent]


def test_openai_to_gemini_tools_wraps_function_declarations():
    specs = [
        {
            "type": "function",
            "function": {
                "name": "lookup_company",
                "description": "Slå upp bolag",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    assert openai_to_gemini_tools(specs) == [
        {
            "functionDeclarations": [
                {
                    "name": "lookup_company",
                    "description": "Slå upp bolag",
                    "parameters": {"type": "object", "properties": {}},
                }
            ]
        }
    ]
    assert openai_to_gemini_tools([]) == []


@pytest.mark.asyncio
async def test_gemini_live_token_is_single_use_and_constrained(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "google_api_key", "google-test-key")
    monkeypatch.setattr(settings, "gemini_live_model", "gemini-3.8-live")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["api_key"] = request.headers["x-goog-api-key"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"name": "auth_tokens/constrained"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as google_client:
        token, model, voice, expires_at = await create_gemini_live_token(
            "Server-owned expert instruction",
            client=google_client,
        )

    assert token == "auth_tokens/constrained"
    assert model == "gemini-3.8-live"
    assert voice == "Algenib"
    assert expires_at.endswith("Z")
    assert captured["api_key"] == "google-test-key"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["uses"] == 1
    setup = payload["bidiGenerateContentSetup"]
    assert setup["model"] == "models/gemini-3.8-live"
    assert setup["generationConfig"] == {
        "responseModalities": ["AUDIO"],
        "speechConfig": {
            "voiceConfig": {
                "prebuiltVoiceConfig": {
                    "voiceName": "Algenib",
                }
            }
        },
    }
    assert setup["systemInstruction"] == {
        "parts": [{"text": "Server-owned expert instruction"}],
    }
    assert setup["inputAudioTranscription"] == {}
    assert setup["outputAudioTranscription"] == {}


@pytest.mark.asyncio
async def test_gemini_live_provider_session_includes_websocket_and_audio(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "google_api_key", "google-test-key")
    monkeypatch.setattr(settings, "gemini_live_model", "gemini-3.8-live")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"name": "auth_tokens/constrained"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as google_client:
        session = await GeminiLiveVoiceProvider().create_session(
            "Server-owned expert instruction",
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
            client=google_client,
        )

    assert session.provider == "gemini"
    assert session.websocket_url.startswith(GEMINI_LIVE_WEBSOCKET_URL + "?access_token=")
    assert unquote(session.websocket_url.split("access_token=", 1)[1]) == (
        "auth_tokens/constrained"
    )
    assert session.model == "gemini-3.8-live"
    assert session.voice == "Algenib"
    assert session.initial_turn == "Öppna telefonsamtalet nu."
    assert session.audio.input_format == "pcm_16000"
    assert session.audio.output_format == "pcm_24000"
    assert session.client_init is None
    setup = captured["payload"]["bidiGenerateContentSetup"]
    assert setup["tools"] == [
        {
            "functionDeclarations": [
                {
                    "name": "lookup_company",
                    "description": "Slå upp bolag",
                    "parameters": {"type": "object", "properties": {}},
                }
            ]
        }
    ]


@pytest.mark.asyncio
async def test_gemini_live_token_requires_google_key(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "google_api_key", "")
    with pytest.raises(GeminiLiveUnavailable, match="GOOGLE_API_KEY"):
        await create_gemini_live_token("Expert instruction")


@pytest.mark.asyncio
async def test_create_live_voice_session_uses_gemini_when_configured(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "live_voice_provider", "gemini")
    monkeypatch.setattr(settings, "google_api_key", "")
    with pytest.raises(LiveVoiceUnavailable, match="GOOGLE_API_KEY"):
        await create_live_voice_session(
            "Expert instruction",
            initial_turn="Öppna.",
            tools=[],
        )


@pytest.mark.asyncio
async def test_gemini_live_token_surfaces_provider_error(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "google_api_key", "google-test-key")
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(429, text="quota exhausted")
    )
    async with httpx.AsyncClient(transport=transport) as google_client:
        with pytest.raises(GeminiLiveProviderError, match="429.*quota exhausted"):
            await create_gemini_live_token(
                "Expert instruction",
                client=google_client,
            )
