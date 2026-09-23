from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import settings
from app.schemas.domain import LiveVoiceAudioOut, PersonaLiveTokenOut
from app.services.live_voice import LiveVoiceProviderError, LiveVoiceUnavailable

ELEVENLABS_INPUT_AUDIO_FORMAT = "pcm_16000"
ELEVENLABS_OUTPUT_AUDIO_FORMAT = "pcm_16000"


def _rfc3339(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _openai_tool_names(specs: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for spec in specs:
        function = spec.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def resolve_elevenlabs_tool_ids(allowed_names: list[str]) -> list[str] | None:
    mapping = settings.elevenlabs_tool_ids
    if not mapping:
        return None
    missing = [name for name in allowed_names if name not in mapping]
    if missing:
        raise LiveVoiceUnavailable(
            "ELEVENLABS_TOOL_IDS is missing ids for: " + ", ".join(missing)
        )
    return [mapping[name] for name in allowed_names]


def build_elevenlabs_client_init(
    system_instruction: str,
    initial_turn: str,
    *,
    tool_ids: list[str] | None,
) -> dict[str, Any]:
    prompt: dict[str, Any] = {"prompt": system_instruction}
    if tool_ids is not None:
        prompt["tool_ids"] = tool_ids
    return {
        "type": "conversation_initiation_client_data",
        "conversation_config_override": {
            "agent": {
                "prompt": prompt,
                "first_message": initial_turn,
                "language": "sv",
            },
            "tts": {
                "voice_id": settings.elevenlabs_voice_id,
            },
        },
    }


def _require_elevenlabs_config() -> tuple[str, str, str]:
    api_key = settings.elevenlabs_api_key.strip()
    agent_id = settings.elevenlabs_agent_id.strip()
    voice_id = settings.elevenlabs_voice_id.strip()
    missing: list[str] = []
    if not api_key:
        missing.append("ELEVENLABS_API_KEY")
    if not agent_id:
        missing.append("ELEVENLABS_AGENT_ID")
    if not voice_id:
        missing.append("ELEVENLABS_VOICE_ID")
    if missing:
        raise LiveVoiceUnavailable(
            " and ".join(missing) + " is not configured"
            if len(missing) == 1
            else ", ".join(missing[:-1])
            + " and "
            + missing[-1]
            + " are not configured"
        )
    return api_key, agent_id, voice_id


async def create_elevenlabs_signed_url(
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    api_key, agent_id, _voice_id = _require_elevenlabs_config()
    base = settings.elevenlabs_base_url.rstrip("/")
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        try:
            response = await client.get(
                f"{base}/v1/convai/conversation/get-signed-url",
                headers={"xi-api-key": api_key},
                params={"agent_id": agent_id},
            )
        except httpx.HTTPError as exc:
            raise LiveVoiceProviderError(
                f"ElevenLabs signed URL request failed: {exc}"
            ) from exc
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise LiveVoiceProviderError(
            f"ElevenLabs signed URL request failed ({response.status_code}): {detail}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise LiveVoiceProviderError(
            "ElevenLabs signed URL response was not valid JSON"
        ) from exc
    signed_url = body.get("signed_url")
    if not isinstance(signed_url, str) or not signed_url:
        raise LiveVoiceProviderError(
            "ElevenLabs signed URL response did not contain a signed_url"
        )
    return signed_url


class ElevenLabsLiveVoiceProvider:
    async def create_session(
        self,
        system_instruction: str,
        *,
        initial_turn: str,
        tools: list[dict[str, Any]],
        client: httpx.AsyncClient | None = None,
    ) -> PersonaLiveTokenOut:
        _, agent_id, voice_id = _require_elevenlabs_config()
        tool_ids = resolve_elevenlabs_tool_ids(_openai_tool_names(tools))
        signed_url = await create_elevenlabs_signed_url(client=client)
        now = datetime.now(UTC)
        return PersonaLiveTokenOut(
            provider="elevenlabs",
            websocket_url=signed_url,
            model=agent_id,
            voice=voice_id,
            expires_at=_rfc3339(
                now + timedelta(seconds=settings.elevenlabs_signed_url_ttl_seconds)
            ),
            initial_turn=initial_turn,
            audio=LiveVoiceAudioOut(
                input_format=ELEVENLABS_INPUT_AUDIO_FORMAT,
                output_format=ELEVENLABS_OUTPUT_AUDIO_FORMAT,
            ),
            client_init=build_elevenlabs_client_init(
                system_instruction,
                initial_turn,
                tool_ids=tool_ids,
            ),
        )
