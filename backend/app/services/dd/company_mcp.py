"""Company MCP tools — BolagsAPI when a key is set, otherwise Allabolag scrape."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any, Self

from app.config import settings
from app.llm import complete_with_tools
from app.llm.tool_messages import assistant_message_dict, tool_result_message
from app.services.dd import allabolag
from app.services.dd.bolagsapi_mcp import (
    BolagsapiMcpClient,
    BolagsapiMcpError,
    candidates_from_mcp_text,
    mcp_tools_to_openai,
)
from app.services.dd.schemas import DdCandidateCompany
from app.services.help_chat import looks_like_leaked_tool_markup
from app.services.oasis_agent_tools import (
    SEARCH_TOOL_NAMES,
    run_search_tool,
    search_tool_specs,
)

_MAX_TOOL_ROUNDS = 4

_INVOKE_RE = re.compile(
    r'<invoke\s+name="([a-zA-Z0-9_]+)"\s*>(.*?)</invoke>',
    re.IGNORECASE | re.DOTALL,
)
_PARAM_RE = re.compile(
    r'<parameter\s+name="([^"]+)"\s*>(.*?)</parameter>',
    re.IGNORECASE | re.DOTALL,
)
_TOOL_CALL_JSON_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.IGNORECASE | re.DOTALL,
)

COMPANY_TOOL_NAMES = frozenset({"search_companies", "lookup_company", "validate_orgnr"})

_ALLABOLAG_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_companies",
            "description": (
                "Search Swedish companies by name, city, industry, or organization number. "
                "Returns name, orgnr, location, revenue, employees, and profit/loss."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_company",
            "description": (
                "Look up one Swedish company by organization number. "
                "Returns registration, address, multi-year accounts, board, "
                "F-skatt/VAT, group structure, trademarks, and business description."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "orgnr": {
                        "type": "string",
                        "description": "Swedish organization number",
                    },
                    "organization_number": {"type": "string"},
                    "query": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_orgnr",
            "description": "Validate and normalize a Swedish organization number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "orgnr": {"type": "string"},
                    "organization_number": {"type": "string"},
                },
            },
        },
    },
]


class CompanyMcpError(RuntimeError):
    pass


def uses_bolagsapi() -> bool:
    return bool(settings.bolagsapi_api_key.strip())


def company_tool_specs() -> list[dict[str, Any]]:
    return [dict(spec) for spec in _ALLABOLAG_SPECS]


def _orgnr_arg(arguments: dict[str, Any]) -> str:
    for key in ("orgnr", "organization_number", "query"):
        value = str(arguments.get(key) or "").strip()
        if value:
            return value
    return ""


async def _run_allabolag_tool(
    name: str, arguments: dict[str, Any]
) -> tuple[str, list[DdCandidateCompany]]:
    try:
        if name == "search_companies":
            query = str(arguments.get("query") or arguments.get("orgnr") or "").strip()
            rows = await allabolag.search_company_rows(query)
            return (
                allabolag.format_search_markdown(rows),
                [allabolag.candidate_from_allabolag(row) for row in rows],
            )
        if name == "lookup_company":
            orgnr = _orgnr_arg(arguments)
            if not orgnr:
                raise CompanyMcpError("lookup_company requires orgnr")
            try:
                row = await allabolag.lookup_company_row(orgnr)
            except allabolag.AllabolagNotFoundError as exc:
                return str(exc), []
            return allabolag.format_lookup_markdown(row), [allabolag.candidate_from_allabolag(row)]
        if name == "validate_orgnr":
            orgnr = _orgnr_arg(arguments)
            if not orgnr:
                raise CompanyMcpError("validate_orgnr requires orgnr")
            return await allabolag.validate_orgnr(orgnr), []
    except allabolag.AllabolagError as exc:
        raise CompanyMcpError(str(exc)) from exc
    raise CompanyMcpError(f"Unknown company tool: {name}")


class CompanyMcpClient:
    """One company-data session. BolagsAPI if keyed, otherwise Allabolag."""

    def __init__(self) -> None:
        self._bolags: BolagsapiMcpClient | None = None

    async def __aenter__(self) -> Self:
        if uses_bolagsapi():
            self._bolags = BolagsapiMcpClient()
            await self._bolags.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._bolags is not None:
            await self._bolags.__aexit__(*exc)
            self._bolags = None

    async def openai_tools(self) -> list[dict[str, Any]]:
        if self._bolags is None:
            return company_tool_specs()
        tools = [
            tool
            for tool in mcp_tools_to_openai(await self._bolags.list_tools())
            if tool.get("function", {}).get("name") in COMPANY_TOOL_NAMES
        ]
        if not tools:
            raise CompanyMcpError("BolagsAPI MCP has no company search tools")
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        text, _candidates = await self.call_tool_with_candidates(name, arguments)
        return text

    async def call_tool_with_candidates(
        self, name: str, arguments: dict[str, Any]
    ) -> tuple[str, list[DdCandidateCompany]]:
        if name not in COMPANY_TOOL_NAMES:
            raise CompanyMcpError(f"Unknown company tool: {name}")
        try:
            if self._bolags is None:
                text, candidates = await _run_allabolag_tool(name, arguments)
            else:
                text = await self._bolags.call_tool(name, arguments)
                candidates = candidates_from_mcp_text(text)
        except BolagsapiMcpError as exc:
            raise CompanyMcpError(str(exc)) from exc
        if "rate limit" in text.lower():
            raise CompanyMcpError("BolagsAPI rate limit exceeded")
        return text, candidates


async def run_company_tool(name: str, arguments: dict[str, Any]) -> str:
    async with CompanyMcpClient() as client:
        return await client.call_tool(name, arguments)


def candidates_from_company_text(
    text: str,
) -> list[DdCandidateCompany]:
    return candidates_from_mcp_text(text)


def parse_tool_args(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _fake_tool_call(index: int, name: str, arguments: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"call_leak_{index}",
        function=SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments, ensure_ascii=False),
        ),
    )


def tool_calls_from_leaked_markup(text: str) -> list[Any]:
    """Turn leaked invoke/tool_call XML into the same shape as API tool_calls."""
    calls: list[Any] = []
    for match in _INVOKE_RE.finditer(text):
        name = match.group(1)
        args = {
            param.group(1): param.group(2).strip()
            for param in _PARAM_RE.finditer(match.group(2))
        }
        if name and any(value for value in args.values()):
            calls.append(_fake_tool_call(len(calls) + 1, name, args))
    for match in _TOOL_CALL_JSON_RE.finditer(text):
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        name = str(parsed.get("name") or "").strip()
        raw_args = parsed.get("arguments") or parsed.get("parameters") or {}
        if isinstance(raw_args, str):
            raw_args = parse_tool_args(raw_args)
        if (
            name
            and isinstance(raw_args, dict)
            and any(str(value).strip() for value in raw_args.values())
        ):
            calls.append(_fake_tool_call(len(calls) + 1, name, raw_args))
    return calls


def visible_assistant_text(message: dict[str, Any]) -> str:
    if message.get("role") != "assistant":
        return ""
    content = str(message.get("content") or "").strip()
    if not content or looks_like_leaked_tool_markup(content):
        return ""
    return content


async def run_company_tool_loop(
    messages: list[dict[str, Any]],
    *,
    max_rounds: int = _MAX_TOOL_ROUNDS,
    with_search: bool = False,
) -> tuple[list[dict[str, Any]], list[DdCandidateCompany]]:
    """Run search/lookup tool rounds. Returns the working transcript and parsed hits."""
    found: list[DdCandidateCompany] = []
    working = list(messages)
    async with CompanyMcpClient() as mcp:
        tools = await mcp.openai_tools()
        if with_search:
            tools = [*tools, *search_tool_specs()]
        for _ in range(max_rounds):
            reply = await complete_with_tools(working, tools)
            working.append(assistant_message_dict(reply))
            tool_calls = getattr(reply, "tool_calls", None)
            if not tool_calls:
                leaked = str(working[-1].get("content") or "")
                tool_calls = tool_calls_from_leaked_markup(leaked)
                if tool_calls:
                    working[-1]["tool_calls"] = [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in tool_calls
                    ]
                else:
                    break
            for call in tool_calls:
                name = call.function.name
                arguments = parse_tool_args(call.function.arguments)
                try:
                    if name in COMPANY_TOOL_NAMES:
                        tool_text, parsed = await mcp.call_tool_with_candidates(
                            name, arguments
                        )
                    elif with_search and name in SEARCH_TOOL_NAMES:
                        tool_text = run_search_tool(name, arguments)
                        parsed = []
                    else:
                        tool_text = f"Unknown tool: {name}"
                        parsed = []
                except CompanyMcpError as exc:
                    raise CompanyMcpError(str(exc)) from exc
                found = _merge_candidates(found, parsed)
                working.append(
                    tool_result_message(
                        tool_call_id=call.id,
                        content=tool_text,
                        name=name,
                    )
                )
    return working, found


async def complete_text_with_company_tools(messages: list[dict[str, Any]]) -> str:
    """Tool loop then a visible assistant reply. Used by DD experts and chats."""
    working, _found = await run_company_tool_loop(messages, with_search=True)
    content = visible_assistant_text(working[-1])
    if content:
        return content
    reply = await complete_with_tools(working, None)
    working.append(assistant_message_dict(reply))
    content = visible_assistant_text(working[-1])
    if not content:
        raise CompanyMcpError("Company tools produced an empty reply")
    return content


def _merge_candidates(
    existing: list[DdCandidateCompany],
    incoming: list[DdCandidateCompany],
) -> list[DdCandidateCompany]:
    by_orgnr = {row.organisationsnummer: row for row in existing}
    order = [row.organisationsnummer for row in existing]
    for row in incoming:
        if row.organisationsnummer not in by_orgnr:
            order.append(row.organisationsnummer)
        by_orgnr[row.organisationsnummer] = row
    return [by_orgnr[orgnr] for orgnr in order]
