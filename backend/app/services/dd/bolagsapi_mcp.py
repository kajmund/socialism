"""BolagsAPI remote MCP client — Streamable HTTP + Bearer API key."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import httpx

from app.config import settings
from app.services.dd.bolagsapi_cache import get_cached, put_cached
from app.services.dd.schemas import DdCandidateCompany

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_SEARCH_LINE = re.compile(
    r"-\s+\*\*(?P<namn>.+?)\*\*\s+\[(?P<orgnr>\d{6}-?\d{4}|\d{10}|\d{12})\]"
    r"(?:\s+-\s+(?P<rest>.+))?"
)
_LOOKUP_NAME = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_LOOKUP_ORGNR = re.compile(
    r"\*\*(?:Organization Number|Organisationsnummer):\*\*\s*(\d{6}-?\d{4}|\d{10}|\d{12})",
    re.IGNORECASE,
)
_LOOKUP_REGISTERED = re.compile(
    r"\*\*(?:Registered|Registrerad):\*\*\s*(\d{4})-(\d{2})-(\d{2})",
    re.IGNORECASE,
)
_LOOKUP_CITY = re.compile(
    r"\*\*(?:Address|Adress):\*\*\s*.+,\s*([A-ZÅÄÖa-zåäö\- ]+),\s*[A-Z]{2}\s*$",
    re.MULTILINE,
)
_LOOKUP_DESC = re.compile(
    r"##\s+(?:Business Description|Verksamhetsbeskrivning)\s*\n(?P<body>.+?)(?:\n##|\n\*|$)",
    re.DOTALL | re.IGNORECASE,
)
_LOOKUP_REVENUE = re.compile(
    r"\*\*(?:Revenue|Omsättning):\*\*\s*([\d\s]+)\s*(?:SEK)?",
    re.IGNORECASE,
)
_LOOKUP_EMPLOYEES = re.compile(
    r"\*\*(?:Employees|Anställda):\*\*\s*(\d+)",
    re.IGNORECASE,
)
_LOOKUP_RESULTAT = re.compile(
    r"\*\*(?:Result|Resultat):\*\*\s*(vinst|förlust|oavsett)",
    re.IGNORECASE,
)
_CITY_IN_PARENS = re.compile(r"\(([^)]+)\)\s*$")
_HEADING_SPLIT = re.compile(r"(?=^#\s+)", re.MULTILINE)


class BolagsapiMcpError(RuntimeError):
    pass


def require_bolagsapi_key() -> str:
    key = settings.bolagsapi_api_key.strip()
    if not key:
        raise BolagsapiMcpError(
            "BOLAGSAPI_API_KEY is required for company search — set it in backend/.env"
        )
    return key


def format_orgnr(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"{digits[:6]}-{digits[6:]}"
    if len(digits) == 12:
        return f"{digits[2:8]}-{digits[8:]}"
    return raw.strip()


def _age_from_year(year: int, today: date | None = None) -> int:
    current = today or date.today()
    return max(0, current.year - year)


def _lookup_fields(text: str, *, today: date | None = None) -> dict[str, Any]:
    orgnr_match = _LOOKUP_ORGNR.search(text)
    if not orgnr_match:
        return {}
    name_match = _LOOKUP_NAME.search(text)
    registered = _LOOKUP_REGISTERED.search(text)
    city = _LOOKUP_CITY.search(text)
    desc = _LOOKUP_DESC.search(text)
    revenue = _LOOKUP_REVENUE.search(text)
    employees = _LOOKUP_EMPLOYEES.search(text)
    resultat = _LOOKUP_RESULTAT.search(text)
    omsattning = None
    if revenue:
        digits = re.sub(r"\D", "", revenue.group(1))
        omsattning = int(digits) if digits else None
    return {
        "orgnr": format_orgnr(orgnr_match.group(1)),
        "namn": name_match.group(1).strip() if name_match else "",
        "alder_ar": _age_from_year(int(registered.group(1)), today) if registered else None,
        "omrade": city.group(1).strip().title() if city else "",
        "beskrivning": desc.group("body").strip() if desc else "",
        "omsattning_sek": omsattning,
        "anstallda": int(employees.group(1)) if employees else None,
        "resultat": resultat.group(1).lower() if resultat else None,
    }


def _merge_candidate(
    existing: DdCandidateCompany | None,
    *,
    orgnr: str,
    namn: str = "",
    alder_ar: int | None = None,
    omrade: str = "",
    resultat: str | None = None,
    omsattning_sek: int | None = None,
    anstallda: int | None = None,
    beskrivning: str = "",
) -> DdCandidateCompany:
    return DdCandidateCompany(
        id=orgnr,
        namn=namn or (existing.namn if existing else orgnr),
        organisationsnummer=orgnr,
        alder_ar=alder_ar if alder_ar is not None else (existing.alder_ar if existing else 0),
        omrade=omrade or (existing.omrade if existing else ""),
        resultat=resultat or (existing.resultat if existing else "oavsett"),  # type: ignore[arg-type]
        omsattning_sek=omsattning_sek if omsattning_sek is not None else (existing.omsattning_sek if existing else None),
        anstallda=anstallda if anstallda is not None else (existing.anstallda if existing else None),
        beskrivning=beskrivning or (existing.beskrivning if existing else ""),
    )


def candidates_from_mcp_text(text: str, *, today: date | None = None) -> list[DdCandidateCompany]:
    """Parse company hits out of BolagsAPI or Allabolag markdown tool results."""
    found: dict[str, DdCandidateCompany] = {}
    for match in _SEARCH_LINE.finditer(text):
        orgnr = format_orgnr(match.group("orgnr"))
        rest = (match.group("rest") or "").strip()
        city_match = _CITY_IN_PARENS.search(rest)
        omrade = city_match.group(1).title() if city_match else ""
        found[orgnr] = _merge_candidate(
            found.get(orgnr),
            orgnr=orgnr,
            namn=match.group("namn").strip(),
            omrade=omrade,
            beskrivning=rest,
        )

    for block in _HEADING_SPLIT.split(text):
        fields = _lookup_fields(block, today=today)
        if not fields:
            continue
        orgnr = fields["orgnr"]
        found[orgnr] = _merge_candidate(
            found.get(orgnr),
            orgnr=orgnr,
            namn=fields["namn"],
            alder_ar=fields["alder_ar"],
            omrade=fields["omrade"],
            resultat=fields["resultat"],
            omsattning_sek=fields["omsattning_sek"],
            anstallda=fields["anstallda"],
            beskrivning=fields["beskrivning"],
        )
    return list(found.values())


def mcp_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            continue
        schema = tool.get("inputSchema")
        parameters = schema if isinstance(schema, dict) else {"type": "object", "properties": {}}
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(tool.get("description") or name),
                    "parameters": parameters,
                },
            }
        )
    return converted


def _parse_sse_json(body: str) -> dict[str, Any]:
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise BolagsapiMcpError("MCP SSE payload was not an object")
        return parsed
    raise BolagsapiMcpError("MCP SSE response had no data")


def _tool_result_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part)
    if result:
        return json.dumps(result, ensure_ascii=False)
    return ""


class BolagsapiMcpClient:
    def __init__(
        self,
        *,
        url: str | None = None,
        api_key: str | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = (url or settings.bolagsapi_mcp_url).strip()
        self._api_key = api_key if api_key is not None else require_bolagsapi_key()
        self._http = http
        self._owns_http = http is None
        self._rpc_id = 0
        self._initialized = False

    async def __aenter__(self) -> BolagsapiMcpClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
            "User-Agent": _BROWSER_UA,
        }

    async def _ensure_connected(self) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=60.0)
            self._owns_http = True
        if not self._initialized:
            await self.initialize()
            self._initialized = True

    def _cache_payload(self, **fields: Any) -> dict[str, Any]:
        return {"url": self._url, **fields}

    async def _post(self, payload: dict[str, Any]) -> tuple[int, str]:
        if self._http is None:
            raise BolagsapiMcpError("MCP client is closed")
        response = await self._http.post(self._url, headers=self._headers(), json=payload)
        if response.status_code >= 400:
            raise BolagsapiMcpError(
                f"BolagsAPI MCP HTTP {response.status_code}: {response.text[:300]}"
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
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "opinionssimulator", "version": "0.1"},
                },
            }
        )
        if status != 200:
            raise BolagsapiMcpError(f"BolagsAPI MCP initialize failed: HTTP {status}")
        parsed = _parse_sse_json(body)
        if parsed.get("error"):
            raise BolagsapiMcpError(f"BolagsAPI MCP initialize error: {parsed['error']}")
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def list_tools(self) -> list[dict[str, Any]]:
        cached = get_cached("list_tools", self._cache_payload())
        if cached is not None:
            parsed_tools = json.loads(cached)
            if not isinstance(parsed_tools, list) or not parsed_tools:
                raise BolagsapiMcpError("BolagsAPI cache returned no tools")
            return parsed_tools
        await self._ensure_connected()
        self._rpc_id += 1
        _status, body = await self._post(
            {"jsonrpc": "2.0", "id": self._rpc_id, "method": "tools/list"}
        )
        parsed = _parse_sse_json(body)
        if parsed.get("error"):
            raise BolagsapiMcpError(f"BolagsAPI MCP tools/list error: {parsed['error']}")
        tools = parsed.get("result", {}).get("tools")
        if not isinstance(tools, list) or not tools:
            raise BolagsapiMcpError("BolagsAPI MCP returned no tools")
        put_cached("list_tools", self._cache_payload(), json.dumps(tools, ensure_ascii=False))
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        payload = self._cache_payload(name=name, arguments=arguments)
        cached = get_cached("call_tool", payload)
        if cached is not None:
            return cached
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
            raise BolagsapiMcpError(f"BolagsAPI MCP {name} error: {parsed['error']}")
        result = parsed.get("result")
        if not isinstance(result, dict):
            raise BolagsapiMcpError(f"BolagsAPI MCP {name} returned no result")
        text = _tool_result_text(result)
        if not text.strip():
            raise BolagsapiMcpError(f"BolagsAPI MCP {name} returned empty content")
        if "rate limit" in text.lower():
            raise BolagsapiMcpError("BolagsAPI rate limit exceeded")
        put_cached("call_tool", payload, text)
        return text
