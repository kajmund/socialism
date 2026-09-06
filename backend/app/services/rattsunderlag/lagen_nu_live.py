"""Live lagen-nu-mcp client. Fail loud — never fall back to the mock corpus."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings
from app.services.rattsunderlag.lagen_nu import LagenNuError, LagenNuNotFoundError
from app.services.rattsunderlag.schemas import ForarbeteRef, LagtextRef, PraxisRef

_PROTOCOL = "2025-03-26"


def _parse_sse_json(body: str) -> dict[str, Any]:
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise LagenNuError("MCP SSE payload was not an object")
        return parsed
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LagenNuError("MCP response was not JSON or SSE") from exc
    if not isinstance(parsed, dict):
        raise LagenNuError("MCP JSON payload was not an object")
    return parsed


def _tool_result_payload(result: dict[str, Any]) -> Any:
    content = result.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        text = "\n".join(part for part in parts if part)
    elif result:
        return result
    else:
        raise LagenNuError("MCP tool returned empty content")
    stripped = text.strip()
    if not stripped:
        raise LagenNuError("MCP tool returned empty content")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LagenNuError("MCP tool content was not JSON") from exc


def _as_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        payload = payload["items"]
    if not isinstance(payload, list):
        raise LagenNuError("MCP search result was not a list")
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise LagenNuError("MCP search item was not an object")
        rows.append(item)
    return rows


def _lagtext(item: dict[str, Any]) -> LagtextRef:
    return LagtextRef.model_validate(
        {
            "sfs_id": item.get("sfs_id") or item.get("id") or "",
            "rubrik": item.get("rubrik") or item.get("title") or "",
            "utdrag": item.get("utdrag") or item.get("text") or "",
            "url": item.get("url"),
            "forarbete_referens": item.get("forarbete_referens") or item.get("forarbete"),
        }
    )


def _praxis(item: dict[str, Any]) -> PraxisRef:
    return PraxisRef.model_validate(
        {
            "referens": item.get("referens") or item.get("citation") or "",
            "instans": item.get("instans") or item.get("court") or "",
            "utdrag": item.get("utdrag") or item.get("text") or "",
            "url": item.get("url"),
        }
    )


def _forarbete(item: dict[str, Any]) -> ForarbeteRef:
    return ForarbeteRef.model_validate(
        {
            "referens": item.get("referens") or item.get("id") or "",
            "titel": item.get("titel") or item.get("title") or "",
            "utdrag": item.get("utdrag") or item.get("text") or "",
            "url": item.get("url"),
        }
    )


class LiveLagenNuClient:
    def __init__(
        self,
        *,
        url: str | None = None,
        api_key: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = (url or settings.lagen_nu_mcp_url).strip()
        if not self._url:
            raise LagenNuError("LAGEN_NU_MCP_URL is required for the live client")
        self._api_key = (api_key if api_key is not None else settings.lagen_nu_mcp_key).strip()
        self._http = http
        self._owns_http = http is None
        self._rpc_id = 0
        self._initialized = False

    async def __aenter__(self) -> LiveLagenNuClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": _PROTOCOL,
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _ensure_connected(self) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=60.0)
            self._owns_http = True
        if not self._initialized:
            await self.initialize()
            self._initialized = True

    async def _post(self, payload: dict[str, Any]) -> tuple[int, str]:
        if self._http is None:
            raise LagenNuError("MCP client is closed")
        try:
            response = await self._http.post(self._url, headers=self._headers(), json=payload)
        except httpx.HTTPError as exc:
            raise LagenNuError(f"lagen-nu MCP unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise LagenNuError(
                f"lagen-nu MCP HTTP {response.status_code}: {response.text[:300]}"
            )
        return response.status_code, response.text

    async def initialize(self) -> None:
        self._rpc_id += 1
        status, body = await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._rpc_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": _PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "socialism-rattsunderlag", "version": "0.1"},
                },
            }
        )
        if status != 200:
            raise LagenNuError(f"lagen-nu MCP initialize failed: HTTP {status}")
        parsed = _parse_sse_json(body)
        if parsed.get("error"):
            raise LagenNuError(f"lagen-nu MCP initialize error: {parsed['error']}")
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        await self._ensure_connected()
        self._rpc_id += 1
        _status, body = await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._rpc_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        parsed = _parse_sse_json(body)
        if parsed.get("error"):
            raise LagenNuError(f"lagen-nu MCP {name} error: {parsed['error']}")
        result = parsed.get("result")
        if not isinstance(result, dict):
            raise LagenNuError(f"lagen-nu MCP {name} returned no result")
        if result.get("isError"):
            raise LagenNuError(f"lagen-nu MCP {name} reported an error")
        return _tool_result_payload(result)

    async def search_law(self, query: str) -> list[LagtextRef]:
        payload = await self.call_tool("search_law", {"query": query})
        return [_lagtext(item) for item in _as_list(payload)]

    async def get_sfs(self, sfs_id: str) -> LagtextRef:
        payload = await self.call_tool("get_sfs", {"sfs_id": sfs_id})
        if payload is None or payload == {}:
            raise LagenNuNotFoundError(f"Unknown SFS id: {sfs_id}")
        if isinstance(payload, list):
            if not payload:
                raise LagenNuNotFoundError(f"Unknown SFS id: {sfs_id}")
            payload = payload[0]
        if not isinstance(payload, dict):
            raise LagenNuError("get_sfs did not return an object")
        return _lagtext(payload)

    async def search_case_law(self, query: str) -> list[PraxisRef]:
        payload = await self.call_tool("search_case_law", {"query": query})
        return [_praxis(item) for item in _as_list(payload)]

    async def get_forarbete(self, referens: str) -> ForarbeteRef:
        payload = await self.call_tool("get_forarbete", {"referens": referens})
        if payload is None or payload == {}:
            raise LagenNuNotFoundError(f"Unknown förarbete: {referens}")
        if isinstance(payload, list):
            if not payload:
                raise LagenNuNotFoundError(f"Unknown förarbete: {referens}")
            payload = payload[0]
        if not isinstance(payload, dict):
            raise LagenNuError("get_forarbete did not return an object")
        return _forarbete(payload)
