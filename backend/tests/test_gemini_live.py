import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import AsyncClient

from app.api import personas as personas_api
from app.config import settings
from app.services.expertgranskning.memory import ExpertMemoryHit
from app.services.gemini_live import (
    GeminiLiveProviderError,
    GeminiLiveUnavailable,
    create_gemini_live_token,
)
from app.services.live_voice_context import recent_voice_memories
from tests.conftest import USER_USER_ID, mint_access_token


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

    async def fake_create_token(
        system_instruction: str,
        *,
        tools: list[dict[str, object]] | None = None,
    ):
        captured.append(system_instruction)
        captured_tools.append(tools or [])
        return (
            "auth_tokens/test",
            "gemini-3.8-live",
            "Algenib",
            "2026-09-20T00:20:00Z",
        )

    monkeypatch.setattr(personas_api, "create_gemini_live_token", fake_create_token)
    response = await client.post(f"/personas/{expert['id']}/live-token")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "token": "auth_tokens/test",
        "model": "gemini-3.8-live",
        "voice": "Algenib",
        "expires_at": "2026-09-20T00:20:00Z",
        "initial_turn": "Öppna telefonsamtalet nu.",
    }
    assert len(captured) == 1
    assert "du är den här experten" in captured[0]
    assert str(expert["name"]) in captured[0]
    assert "Bolagsrätt" in captured[0]
    assert '"current_user"' in captured[0]
    assert '"customer"' in captured[0]
    assert "Ja, det är" in captured[0]
    declarations = captured_tools[0][0]["functionDeclarations"]
    assert {declaration["name"] for declaration in declarations} == {
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

    async def fake_create_token(
        _system_instruction: str,
        *,
        tools: list[dict[str, object]] | None = None,
    ):
        assert tools
        return (
            "auth_tokens/test",
            "gemini-3.8-live",
            "Algenib",
            "2026-09-20T00:20:00Z",
        )

    monkeypatch.setattr(personas_api, "create_gemini_live_token", fake_create_token)
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

    async def fail_create_token(
        _system_instruction: str,
        *,
        tools: list[dict[str, object]] | None = None,
    ):
        assert tools
        raise GeminiLiveProviderError("Gemini Live token request failed (429): quota")

    monkeypatch.setattr(personas_api, "create_gemini_live_token", fail_create_token)
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
async def test_gemini_live_token_requires_google_key(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "google_api_key", "")
    with pytest.raises(GeminiLiveUnavailable, match="GOOGLE_API_KEY"):
        await create_gemini_live_token("Expert instruction")


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
