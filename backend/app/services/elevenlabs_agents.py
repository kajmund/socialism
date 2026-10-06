"""ElevenLabs' native REST API. Never expose provider response bodies on failure."""

from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import HTTPException

from app.config import settings


class ElevenLabsError(RuntimeError):
    def __init__(self, code: str, status: int = 502) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


class ElevenLabsAgentsClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def request(self, method: str, path: str, *, body: dict | None = None, params: dict | None = None) -> dict:
        try:
            response = await self.http.request(method, path, json=body, params=params)
        except httpx.RequestError:
            raise ElevenLabsError("elevenlabs_unreachable") from None
        if response.is_error:
            raise ElevenLabsError("elevenlabs_request_failed")
        if response.status_code == 204 or (method == "DELETE" and not response.content):
            return {}
        try:
            value = response.json()
        except ValueError:
            raise ElevenLabsError("elevenlabs_invalid_response") from None
        if method == "DELETE" and value is None:
            return {}
        if not isinstance(value, dict):
            raise ElevenLabsError("elevenlabs_invalid_response")
        return value

    async def connection(self, *, agent_id: str, agent_version: str, mode: str) -> dict:
        params = {"agent_id": agent_id}
        if agent_version:
            params["version_id"] = agent_version
        if mode == "voice":
            result = await self.request("GET", "/v1/convai/conversation/token", params=params)
            return {"connection_type": "webrtc", "conversation_token": require_string(result, "token"),
                    "conversation_id": require_string(result, "conversation_id"), "signed_url": None}
        result = await self.request("GET", "/v1/convai/conversation/get-signed-url",
                                    params={**params, "include_conversation_id": "true"})
        signed_url = require_string(result, "signed_url")
        conversation_id = parse_qs(urlparse(signed_url).query).get("conversation_id", [None])[0]
        if not conversation_id:
            raise ElevenLabsError("elevenlabs_missing_conversation_binding")
        return {"connection_type": "websocket", "signed_url": signed_url,
                "conversation_token": None, "conversation_id": conversation_id}


def require_string(value: dict, key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ElevenLabsError("elevenlabs_invalid_response")
    return result


async def get_elevenlabs_client() -> AsyncIterator[ElevenLabsAgentsClient]:
    if not settings.elevenlabs_api_key:
        raise HTTPException(503, "elevenlabs_not_configured")
    if not settings.elevenlabs_voice_id:
        raise HTTPException(503, "elevenlabs_incomplete_configuration")
    async with httpx.AsyncClient(base_url=settings.elevenlabs_base_url,
                                headers={"xi-api-key": settings.elevenlabs_api_key}, timeout=45) as http:
        yield ElevenLabsAgentsClient(http)
