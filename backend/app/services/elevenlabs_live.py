from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import settings
from app.schemas.domain import LiveVoiceAudioOut, PersonaLiveTokenOut
from app.services.elevenlabs_agents import ElevenLabsAgentsClient, ElevenLabsError, require_string
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


def _schema_property(value: dict[str, Any], *, name: str) -> dict[str, Any]:
    raw_type = value.get("type")
    description = value.get("description")
    prop: dict[str, Any] = {
        "type": "number" if raw_type == "integer" else raw_type or "string",
        "description": description if isinstance(description, str) and description else name,
    }
    enum = value.get("enum")
    if isinstance(enum, list) and enum:
        prop["enum"] = enum
    nested = value.get("properties")
    if prop["type"] == "object" and isinstance(nested, dict):
        prop["properties"] = {
            key: _schema_property(item, name=key) if isinstance(item, dict) else {
                "type": "string",
                "description": key,
            }
            for key, item in nested.items()
        }
    return prop


def _client_tool_parameters(raw: object) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    properties = source.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    cleaned = {
        key: _schema_property(item, name=key)
        for key, item in properties.items()
        if isinstance(item, dict)
    }
    required = source.get("required")
    if not isinstance(required, list):
        required = []
    return {
        "type": "object",
        "properties": cleaned,
        "required": [item for item in required if isinstance(item, str) and item in cleaned],
    }


def _client_tool_config(function: dict[str, Any]) -> dict[str, Any]:
    description = function.get("description")
    return {
        "type": "client",
        "name": function["name"],
        "description": description if isinstance(description, str) and description else function["name"],
        "expects_response": True,
        "response_timeout_secs": 60,
        "parameters": _client_tool_parameters(function.get("parameters")),
    }


async def _listed_client_tool_ids(client: httpx.AsyncClient) -> dict[str, str]:
    api_key, _agent_id, _voice_id = _require_elevenlabs_config()
    try:
        response = await client.get(
            f"{settings.elevenlabs_base_url.rstrip('/')}/v1/convai/tools",
            headers={"xi-api-key": api_key},
        )
    except httpx.HTTPError as exc:
        raise LiveVoiceProviderError(f"ElevenLabs tool list failed: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise LiveVoiceProviderError(
            f"ElevenLabs tool list failed ({response.status_code}): {detail}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise LiveVoiceProviderError("ElevenLabs tool list was not valid JSON") from exc
    rows = body.get("tools") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise LiveVoiceProviderError("ElevenLabs tool list did not contain tools")
    found: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        config = row.get("tool_config")
        if not isinstance(config, dict) or config.get("type") != "client":
            continue
        name = config.get("name")
        tool_id = row.get("id")
        if isinstance(name, str) and name and isinstance(tool_id, str) and tool_id:
            found[name] = tool_id
    return found


async def _create_client_tool(client: httpx.AsyncClient, function: dict[str, Any]) -> str:
    api_key, _agent_id, _voice_id = _require_elevenlabs_config()
    try:
        response = await client.post(
            f"{settings.elevenlabs_base_url.rstrip('/')}/v1/convai/tools",
            headers={"xi-api-key": api_key},
            json={"tool_config": _client_tool_config(function)},
        )
    except httpx.HTTPError as exc:
        raise LiveVoiceProviderError(
            f"ElevenLabs tool create failed for {function.get('name')}: {exc}"
        ) from exc
    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise LiveVoiceProviderError(
            f"ElevenLabs tool create failed for {function.get('name')} "
            f"({response.status_code}): {detail}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise LiveVoiceProviderError(
            f"ElevenLabs tool create for {function.get('name')} was not valid JSON"
        ) from exc
    tool_id = body.get("id") if isinstance(body, dict) else None
    if not isinstance(tool_id, str) or not tool_id:
        raise LiveVoiceProviderError(
            f"ElevenLabs tool create for {function.get('name')} did not return an id"
        )
    return tool_id


def _agent_url() -> str:
    _api_key, agent_id, _voice_id = _require_elevenlabs_config()
    return f"{settings.elevenlabs_base_url.rstrip('/')}/v1/convai/agents/{agent_id}"


async def _attached_agent_tool_ids(client: httpx.AsyncClient) -> list[str]:
    api_key, _agent_id, _voice_id = _require_elevenlabs_config()
    try:
        response = await client.get(_agent_url(), headers={"xi-api-key": api_key})
    except httpx.HTTPError as exc:
        raise LiveVoiceProviderError(f"ElevenLabs agent read failed: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise LiveVoiceProviderError(
            f"ElevenLabs agent read failed ({response.status_code}): {detail}"
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise LiveVoiceProviderError("ElevenLabs agent read was not valid JSON") from exc
    prompt = (
        body.get("conversation_config", {})
        .get("agent", {})
        .get("prompt", {})
        if isinstance(body, dict)
        else {}
    )
    raw = prompt.get("tool_ids") if isinstance(prompt, dict) else None
    if not isinstance(raw, list):
        raise LiveVoiceProviderError("ElevenLabs agent did not contain tool_ids")
    return [item for item in raw if isinstance(item, str) and item]


async def _ensure_agent_has_tools(client: httpx.AsyncClient, tool_ids: list[str]) -> None:
    """ElevenLabs rejects a per-call tool id that is not already on the agent."""
    attached = await _attached_agent_tool_ids(client)
    missing = [tool_id for tool_id in tool_ids if tool_id not in attached]
    if not missing:
        return
    api_key, _agent_id, _voice_id = _require_elevenlabs_config()
    try:
        response = await client.patch(
            _agent_url(),
            headers={"xi-api-key": api_key},
            json={
                "conversation_config": {
                    "agent": {"prompt": {"tool_ids": [*attached, *missing]}},
                }
            },
        )
    except httpx.HTTPError as exc:
        raise LiveVoiceProviderError(f"ElevenLabs agent tool attach failed: {exc}") from exc
    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise LiveVoiceProviderError(
            f"ElevenLabs agent tool attach failed ({response.status_code}): {detail}"
        )


async def client_tool_ids_for_session(
    tools: list[dict[str, Any]],
    *,
    client: httpx.AsyncClient,
) -> list[str] | None:
    functions = [
        spec["function"]
        for spec in tools
        if isinstance(spec.get("function"), dict) and isinstance(spec["function"].get("name"), str)
    ]
    names = [function["name"] for function in functions]
    if not names:
        return None
    mapped = resolve_elevenlabs_tool_ids(names)
    if mapped is not None:
        ids = mapped
    else:
        existing = await _listed_client_tool_ids(client)
        ids = []
        for function in functions:
            name = function["name"]
            tool_id = existing.get(name)
            if tool_id is None:
                tool_id = await _create_client_tool(client, function)
                existing[name] = tool_id
            ids.append(tool_id)
    await _ensure_agent_has_tools(client, ids)
    return ids


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
    # A per-call voice override makes ElevenLabs close the socket (1002,
    # reported as a prohibited-use violation) when the voice is a clone.
    # The voice saved on the agent is the one that speaks.
    return {
        "type": "conversation_initiation_client_data",
        "conversation_config_override": {
            "agent": {
                "prompt": prompt,
                "first_message": initial_turn,
                "language": "sv",
            },
        },
    }


def _tts_voice_id(agent: dict) -> str | None:
    config = agent.get("conversation_config")
    if not isinstance(config, dict):
        return None
    tts = config.get("tts")
    if not isinstance(tts, dict):
        return None
    voice_id = tts.get("voice_id")
    return voice_id if isinstance(voice_id, str) else None


async def publish_agent_voice(voice_id: str, *, client: httpx.AsyncClient) -> None:
    """Point the one configured agent at this expert's ElevenLabs voice."""
    agent_id = settings.elevenlabs_agent_id.strip()
    if not agent_id:
        raise LiveVoiceUnavailable("ELEVENLABS_AGENT_ID is not configured")
    api = ElevenLabsAgentsClient(client)
    try:
        agent = await api.request("GET", f"/v1/convai/agents/{agent_id}")
    except ElevenLabsError as exc:
        raise LiveVoiceProviderError("ElevenLabs voice update failed") from exc
    if _tts_voice_id(agent) == voice_id:
        return
    branch_id = require_string(agent, "main_branch_id")
    try:
        await api.request("PATCH", f"/v1/convai/agents/{agent_id}", body={
            "conversation_config": {"tts": {"voice_id": voice_id}}})
        await api.request("PATCH", f"/v1/convai/agents/{agent_id}", params={"branch_id": branch_id},
                          body={"version_description": f"expert-voice:{voice_id}"})
    except ElevenLabsError as exc:
        raise LiveVoiceProviderError("ElevenLabs voice update failed") from exc


async def list_elevenlabs_voices() -> list[dict[str, str]]:
    api_key = settings.elevenlabs_api_key.strip()
    if not api_key:
        raise LiveVoiceUnavailable("ELEVENLABS_API_KEY is not configured")
    async with httpx.AsyncClient(base_url=settings.elevenlabs_base_url,
                                  headers={"xi-api-key": api_key}, timeout=30.0) as http:
        try:
            payload = await ElevenLabsAgentsClient(http).request("GET", "/v1/voices")
        except ElevenLabsError as exc:
            raise LiveVoiceProviderError("ElevenLabs voice list failed") from exc
    rows = payload.get("voices")
    if not isinstance(rows, list):
        raise LiveVoiceProviderError("ElevenLabs voice list failed")
    options = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        voice_id, name = row.get("voice_id"), row.get("name")
        if isinstance(voice_id, str) and voice_id.strip() and isinstance(name, str) and name.strip():
            options.append({"id": voice_id, "name": name})
    return sorted(options, key=lambda item: item["name"].casefold())


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
        voice: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> PersonaLiveTokenOut:
        _, agent_id, configured_voice = _require_elevenlabs_config()
        voice_id = (voice or "").strip() or configured_voice
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=30.0)
        try:
            if voice_id != configured_voice:
                await publish_agent_voice(voice_id, client=client)
            tool_ids = await client_tool_ids_for_session(tools, client=client)
            signed_url = await create_elevenlabs_signed_url(client=client)
        finally:
            if owns_client:
                await client.aclose()
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
