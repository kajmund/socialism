from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings
from app.schemas.domain import LiveVoiceAudioOut, PersonaLiveTokenOut
from app.services.live_voice import LiveVoiceProviderError, LiveVoiceUnavailable

GEMINI_LIVE_WEBSOCKET_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained"
)
GEMINI_INPUT_AUDIO_FORMAT = "pcm_16000"
GEMINI_OUTPUT_AUDIO_FORMAT = "pcm_24000"

GeminiLiveUnavailable = LiveVoiceUnavailable
GeminiLiveProviderError = LiveVoiceProviderError


def openai_to_gemini_tools(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    declarations = [spec["function"] for spec in specs if "function" in spec]
    return [{"functionDeclarations": declarations}] if declarations else []


def _rfc3339(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _token_payload(
    system_instruction: str,
    *,
    tools: list[dict[str, object]] | None,
    now: datetime,
) -> dict[str, object]:
    model = f"models/{settings.gemini_live_model}"
    setup: dict[str, object] = {
        "model": model,
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": settings.gemini_live_voice,
                    }
                }
            },
        },
        "systemInstruction": {
            "parts": [{"text": system_instruction}],
        },
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
    }
    if tools:
        setup["tools"] = tools
    return {
        "uses": 1,
        "expireTime": _rfc3339(
            now + timedelta(seconds=settings.gemini_live_token_ttl_seconds)
        ),
        "newSessionExpireTime": _rfc3339(
            now + timedelta(seconds=settings.gemini_live_new_session_ttl_seconds)
        ),
        "bidiGenerateContentSetup": setup,
    }


async def create_gemini_live_token(
    system_instruction: str,
    *,
    tools: list[dict[str, object]] | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str, str, str]:
    api_key = settings.google_api_key.strip()
    if not api_key:
        raise GeminiLiveUnavailable("GOOGLE_API_KEY is not configured")

    now = datetime.now(UTC)
    payload = _token_payload(system_instruction, tools=tools, now=now)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        try:
            response = await client.post(
                f"{settings.google_live_base_url.rstrip('/')}/auth_tokens",
                headers={"x-goog-api-key": api_key},
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise GeminiLiveProviderError(
                f"Gemini Live token request failed: {exc}"
            ) from exc
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise GeminiLiveProviderError(
            f"Gemini Live token request failed ({response.status_code}): {detail}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise GeminiLiveProviderError(
            "Gemini Live token response was not valid JSON"
        ) from exc
    token = body.get("name")
    if not isinstance(token, str) or not token:
        raise GeminiLiveProviderError("Gemini Live token response did not contain a token")

    return (
        token,
        settings.gemini_live_model,
        settings.gemini_live_voice,
        str(payload["expireTime"]),
    )


class GeminiLiveVoiceProvider:
    async def create_session(
        self,
        system_instruction: str,
        *,
        initial_turn: str,
        tools: list[dict[str, Any]],
        client: httpx.AsyncClient | None = None,
    ) -> PersonaLiveTokenOut:
        gemini_tools = openai_to_gemini_tools(tools)
        token, model, voice, expires_at = await create_gemini_live_token(
            system_instruction,
            tools=gemini_tools or None,
            client=client,
        )
        return PersonaLiveTokenOut(
            provider="gemini",
            websocket_url=(
                f"{GEMINI_LIVE_WEBSOCKET_URL}?access_token={quote(token, safe='')}"
            ),
            model=model,
            voice=voice,
            expires_at=expires_at,
            initial_turn=initial_turn,
            audio=LiveVoiceAudioOut(
                input_format=GEMINI_INPUT_AUDIO_FORMAT,
                output_format=GEMINI_OUTPUT_AUDIO_FORMAT,
            ),
            client_init=None,
        )
