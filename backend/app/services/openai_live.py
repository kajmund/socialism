"""OpenAI Realtime native-audio provider for expert live voice.

Mints an ephemeral Realtime client secret server-side (POST
/v1/realtime/client_secrets) and hands the browser a session URL on our own
relay WebSocket. The relay authenticates upstream with the secret as a bearer
token, which browsers cannot attach themselves. The model hears audio natively
(speech in, speech out) — the same architecture as ChatGPT voice mode, with no
separate transcription hop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import settings
from app.realtime.openai_live_relay import openai_live_relay_registry
from app.schemas.domain import LiveVoiceAudioOut, PersonaLiveTokenOut
from app.services.live_voice import LiveVoiceProviderError, LiveVoiceUnavailable

OPENAI_NATIVE_INPUT_FORMAT = "pcm_24000"
OPENAI_NATIVE_OUTPUT_FORMAT = "pcm_24000"


def _rfc3339(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _realtime_tools(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten chat-format tool specs into the Realtime sessions tool shape."""
    tools: list[dict[str, Any]] = []
    for spec in specs:
        function = spec.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            continue
        tools.append(
            {
                "type": "function",
                "name": function["name"],
                "description": function.get("description", function["name"]),
                "parameters": function.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return tools


def realtime_session_payload(
    system_instruction: str,
    *,
    tools: list[dict[str, Any]],
    voice: str,
    model: str | None = None,
) -> dict[str, Any]:
    """Client-secret request body: a realtime session plus a bounded TTL."""
    session: dict[str, Any] = {
        "type": "realtime",
        "model": (model or "").strip() or settings.openai_native_model,
        "instructions": system_instruction,
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": 24000},
                # On-screen transcripts; the model itself hears the audio.
                "transcription": {
                    "model": settings.openai_native_transcription_model,
                },
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
                "voice": voice,
            },
        },
    }
    flattened = _realtime_tools(tools)
    if flattened:
        session["tools"] = flattened
    return {
        "expires_after": {
            "anchor": "created_at",
            "seconds": settings.openai_native_token_ttl_seconds,
        },
        "session": session,
    }


async def create_openai_realtime_secret(
    system_instruction: str,
    *,
    tools: list[dict[str, Any]] | None = None,
    voice: str | None = None,
    model: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str]:
    """Mint a client secret and register it for the relay. Returns (secret, expires_at)."""
    api_key = settings.openai_api_key.strip()
    if not api_key:
        raise LiveVoiceUnavailable("OPENAI_API_KEY is not configured")
    chosen = (voice or "").strip() or settings.openai_native_voice
    chosen_model = (model or "").strip() or settings.openai_native_model

    payload = realtime_session_payload(
        system_instruction,
        tools=tools or [],
        voice=chosen,
        model=chosen_model,
    )
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        try:
            response = await client.post(
                f"{settings.openai_base_url.rstrip('/')}/v1/realtime/client_secrets",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise LiveVoiceProviderError(
                f"OpenAI Realtime client secret request failed: {exc}"
            ) from exc
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise LiveVoiceProviderError(
            f"OpenAI Realtime client secret request failed "
            f"({response.status_code}): {detail}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise LiveVoiceProviderError(
            "OpenAI Realtime client secret response was not valid JSON"
        ) from exc
    secret = body.get("value") if isinstance(body, dict) else None
    expires_at = body.get("expires_at") if isinstance(body, dict) else None
    if not isinstance(secret, str) or not secret:
        raise LiveVoiceProviderError(
            "OpenAI Realtime client secret response did not contain a value"
        )
    if not isinstance(expires_at, (int, float)):
        raise LiveVoiceProviderError(
            "OpenAI Realtime client secret response did not contain an expiry"
        )
    openai_live_relay_registry.register(
        secret,
        chosen_model,
        float(expires_at),
    )
    return secret, _rfc3339(datetime.fromtimestamp(expires_at, tz=UTC))


class OpenAILiveVoiceProvider:
    async def create_session(
        self,
        system_instruction: str,
        *,
        initial_turn: str,
        tools: list[dict[str, Any]],
        voice: str | None = None,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> PersonaLiveTokenOut:
        chosen = (voice or "").strip() or settings.openai_native_voice
        secret, expires_at = await create_openai_realtime_secret(
            system_instruction,
            tools=tools,
            voice=chosen,
            model=model,
            client=client,
        )
        return PersonaLiveTokenOut(
            provider="openai",
            websocket_url=(
                f"{settings.openai_relay_base_url.rstrip('/')}"
                f"/ws/openai-live?session={secret}"
            ),
            model=(model or "").strip() or settings.openai_native_model,
            voice=chosen,
            expires_at=expires_at,
            initial_turn=initial_turn,
            audio=LiveVoiceAudioOut(
                input_format=OPENAI_NATIVE_INPUT_FORMAT,
                output_format=OPENAI_NATIVE_OUTPUT_FORMAT,
            ),
            client_init=None,
        )
