"""Official lagen.nu MCP client. Streamable HTTP, read-only, no auth."""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from app.config import settings
from app.services.lagen_nu.models import (
    IncomingCitations,
    LagenNuDocument,
    LagenNuPin,
    LagenNuSearchHit,
    RecognizedCitation,
    ResolvedCitations,
    SearchResults,
)
from app.services.lagen_nu.uris import canonical_lagen_nu_uri

_PROTOCOL = "2025-03-26"
_CLIENT_NAME = "socialism-research"
_CLIENT_VERSION = "0.1"


class OfficialLagenNuMcpError(RuntimeError):
    pass


class OfficialLagenNuMcpNotFoundError(OfficialLagenNuMcpError):
    pass


class LagenNuMcpClient(Protocol):
    async def search(
        self,
        query: str,
        *,
        source: str | None = None,
        kind: str | None = None,
        limit: int = 10,
    ) -> SearchResults: ...

    async def resolve_citation(self, citation: str) -> ResolvedCitations: ...

    async def get_incoming_citations(
        self,
        uri: str,
        *,
        source: str | None = None,
        sort: str = "rail",
        limit: int = 10,
    ) -> IncomingCitations: ...

    async def get_document(
        self,
        uri: str,
        *,
        pinpoint: str | None = None,
        max_chars: int = 8000,
    ) -> LagenNuDocument: ...


def _parse_rpc_body(body: str) -> dict[str, Any]:
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise OfficialLagenNuMcpError("lagen.nu MCP SSE payload was not an object")
        return parsed
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OfficialLagenNuMcpError("lagen.nu MCP response was not JSON or SSE") from exc
    if not isinstance(parsed, dict):
        raise OfficialLagenNuMcpError("lagen.nu MCP JSON payload was not an object")
    return parsed


def _tool_result_payload(result: dict[str, Any]) -> Any:
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and structured:
        return structured
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
        raise OfficialLagenNuMcpError("lagen.nu MCP tool returned empty content")
    stripped = text.strip()
    if not stripped:
        raise OfficialLagenNuMcpError("lagen.nu MCP tool returned empty content")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise OfficialLagenNuMcpError("lagen.nu MCP tool content was not JSON") from exc


def _optional_str(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item)
    return tuple(out)


def _as_object(value: object, *, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OfficialLagenNuMcpError(f"lagen.nu MCP {what} was not an object")
    return value


def _parse_pin(value: object) -> LagenNuPin | None:
    if not isinstance(value, dict):
        return None
    pinpoint = _optional_str(value.get("pinpoint"))
    uri = canonical_lagen_nu_uri(value.get("uri"))
    if uri is None and pinpoint is None:
        return None
    return LagenNuPin(
        uri=uri,
        pinpoint=pinpoint,
        label=_optional_str(value.get("label")),
        highlight=_string_tuple(value.get("highlight")),
    )


def parse_search_hit(value: object) -> LagenNuSearchHit:
    item = _as_object(value, what="search hit")
    pin = _parse_pin(item.get("pin"))
    fragments: list[LagenNuPin] = []
    raw_fragments = item.get("fragments")
    if isinstance(raw_fragments, list):
        for fragment in raw_fragments:
            parsed = _parse_pin(fragment)
            if parsed is not None:
                fragments.append(parsed)
    return LagenNuSearchHit(
        id=_optional_str(item.get("id")),
        uri=canonical_lagen_nu_uri(item.get("uri")) or canonical_lagen_nu_uri(item.get("url")),
        url=_optional_str(item.get("url")),
        title=_optional_str(item.get("title")) or _optional_str(item.get("display")),
        identifier=_optional_str(item.get("identifier")),
        source=_optional_str(item.get("source")),
        kind=_optional_str(item.get("kind")),
        score=_optional_float(item.get("score")),
        inbound_count=_optional_int(item.get("inbound_count")),
        pin=pin,
        fragments=tuple(fragments),
        highlight=_string_tuple(item.get("highlight")),
        raw=item,
    )


def parse_search_results(payload: object) -> SearchResults:
    data = _as_object(payload, what="search result")
    rows = data.get("results")
    if not isinstance(rows, list):
        raise OfficialLagenNuMcpError("lagen.nu MCP search results was not a list")
    return SearchResults(
        query=str(data.get("query") or ""),
        total=_optional_int(data.get("total")) or 0,
        results=tuple(parse_search_hit(item) for item in rows),
    )


def parse_resolved_citations(payload: object) -> ResolvedCitations:
    data = _as_object(payload, what="resolve_citation result")
    rows = data.get("results")
    recognized_rows = data.get("recognized")
    if not isinstance(rows, list):
        raise OfficialLagenNuMcpError("lagen.nu MCP resolve results was not a list")
    if recognized_rows is None:
        recognized_rows = []
    if not isinstance(recognized_rows, list):
        raise OfficialLagenNuMcpError("lagen.nu MCP recognized citations was not a list")
    recognized: list[RecognizedCitation] = []
    for item in recognized_rows:
        row = _as_object(item, what="recognized citation")
        recognized.append(
            RecognizedCitation(
                uri=canonical_lagen_nu_uri(row.get("uri")),
                source=_optional_str(row.get("source")),
                invalid=row.get("invalid") is True,
                raw=row,
            )
        )
    return ResolvedCitations(
        results=tuple(parse_search_hit(item) for item in rows),
        recognized=tuple(recognized),
    )


def parse_incoming_citations(payload: object) -> IncomingCitations:
    data = _as_object(payload, what="get_incoming_citations result")
    uri = canonical_lagen_nu_uri(data.get("uri"))
    if uri is None:
        raise OfficialLagenNuMcpError(
            "lagen.nu MCP get_incoming_citations result had no canonical URI"
        )
    rows = data.get("citations")
    if not isinstance(rows, list):
        raise OfficialLagenNuMcpError(
            "lagen.nu MCP get_incoming_citations citations was not a list"
        )
    return IncomingCitations(
        uri=uri,
        total=_optional_int(data.get("total")) or 0,
        results=tuple(parse_search_hit(item) for item in rows),
    )


def parse_document(payload: object) -> LagenNuDocument:
    data = _as_object(payload, what="get_document result")
    uri = canonical_lagen_nu_uri(data.get("uri"))
    if uri is None:
        raise OfficialLagenNuMcpError("lagen.nu MCP document had no canonical URI")
    text = data.get("text")
    if not isinstance(text, str):
        raise OfficialLagenNuMcpError("lagen.nu MCP document text was not a string")
    return LagenNuDocument(
        uri=uri,
        title=_optional_str(data.get("title")) or _optional_str(data.get("label")),
        text=text,
        source=_optional_str(data.get("source")),
        kind=_optional_str(data.get("kind")),
        label=_optional_str(data.get("label")),
        publisher_source_url=_optional_str(data.get("source_url")),
        pinpoint=_optional_str(data.get("pinpoint")),
        truncated=data.get("truncated") is True,
        inbound_count=_optional_int(data.get("inbound_count")),
        raw=data,
    )


class OfficialLagenNuMcpClient:
    def __init__(
        self,
        *,
        url: str | None = None,
        timeout_seconds: float | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = (url if url is not None else settings.lagen_nu_official_mcp_url).strip()
        if not self._url:
            raise OfficialLagenNuMcpError("LAGEN_NU_OFFICIAL_MCP_URL is required")
        timeout = (
            settings.lagen_nu_official_mcp_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        self._timeout = timeout
        self._http = http
        self._owns_http = http is None
        self._rpc_id = 0
        self._initialized = False
        self._session_id: str | None = None

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": _PROTOCOL,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _ensure_connected(self) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
            self._owns_http = True
        if not self._initialized:
            await self.initialize()
            self._initialized = True

    async def _post(self, payload: dict[str, Any]) -> str:
        if self._http is None:
            raise OfficialLagenNuMcpError("lagen.nu MCP client is closed")
        try:
            response = await self._http.post(self._url, headers=self._headers(), json=payload)
        except httpx.TimeoutException as exc:
            raise OfficialLagenNuMcpError("lagen.nu MCP timed out") from exc
        except httpx.HTTPError as exc:
            raise OfficialLagenNuMcpError("lagen.nu MCP unreachable") from exc
        session = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
        if session:
            self._session_id = session
        if response.status_code >= 400:
            raise OfficialLagenNuMcpError(f"lagen.nu MCP HTTP {response.status_code}")
        return response.text

    async def initialize(self) -> None:
        self._rpc_id += 1
        body = await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._rpc_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": _PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": _CLIENT_NAME, "version": _CLIENT_VERSION},
                },
            }
        )
        parsed = _parse_rpc_body(body)
        if parsed.get("error"):
            raise OfficialLagenNuMcpError("lagen.nu MCP initialize error")
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        await self._ensure_connected()
        self._rpc_id += 1
        body = await self._post(
            {
                "jsonrpc": "2.0",
                "id": self._rpc_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        parsed = _parse_rpc_body(body)
        if parsed.get("error"):
            raise OfficialLagenNuMcpError(f"lagen.nu MCP {name} error")
        result = parsed.get("result")
        if not isinstance(result, dict):
            raise OfficialLagenNuMcpError(f"lagen.nu MCP {name} returned no result")
        if result.get("isError"):
            raise OfficialLagenNuMcpError(f"lagen.nu MCP {name} reported an error")
        return _tool_result_payload(result)

    async def search(
        self,
        query: str,
        *,
        source: str | None = None,
        kind: str | None = None,
        limit: int = 10,
    ) -> SearchResults:
        arguments: dict[str, Any] = {"query": query, "limit": limit}
        if source is not None:
            arguments["source"] = source
        if kind is not None:
            arguments["kind"] = kind
        return parse_search_results(await self.call_tool("search", arguments))

    async def resolve_citation(self, citation: str) -> ResolvedCitations:
        return parse_resolved_citations(
            await self.call_tool("resolve_citation", {"citation": citation})
        )

    async def get_incoming_citations(
        self,
        uri: str,
        *,
        source: str | None = None,
        sort: str = "rail",
        limit: int = 10,
    ) -> IncomingCitations:
        arguments: dict[str, Any] = {
            "uri": uri,
            "sort": sort,
            "limit": limit,
        }
        if source is not None:
            arguments["source"] = source
        return parse_incoming_citations(
            await self.call_tool("get_incoming_citations", arguments)
        )

    async def get_document(
        self,
        uri: str,
        *,
        pinpoint: str | None = None,
        max_chars: int = 8000,
    ) -> LagenNuDocument:
        arguments: dict[str, Any] = {"uri": uri, "max_chars": max_chars, "format": "md"}
        if pinpoint:
            arguments["pinpoint"] = pinpoint
        payload = await self.call_tool("get_document", arguments)
        if payload is None or payload == {}:
            raise OfficialLagenNuMcpNotFoundError(f"Unknown lagen.nu document: {uri}")
        return parse_document(payload)
