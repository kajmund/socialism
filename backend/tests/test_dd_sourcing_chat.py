"""Tests for BolagsAPI MCP parsing and DD sourcing chat."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Self

import pytest
from httpx import AsyncClient

from app.config import settings
from app.llm import set_tools_completer
from app.services.dd.bolagsapi_mcp import (
    BolagsapiMcpError,
    candidates_from_mcp_text,
    format_orgnr,
    mcp_tools_to_openai,
    require_bolagsapi_key,
)
from app.services.dd.allabolag import AllabolagNotFoundError
from app.services.dd.company_mcp import tool_calls_from_leaked_markup
from app.services.dd.schemas import DdCandidateCompany
from app.services.dd.sourcing_chat import (
    SourcingChatError,
    merge_candidates,
    run_sourcing_chat_turn,
)
from app.services.prompt_catalog import default_prompts

_SEARCH_MD = "- **Spotify AB** [5567037485] - AB (STOCKHOLM)"
_LOOKUP_MD = """# Spotify AB

**Organization Number:** 556703-7485
**Registered:** 2006-05-10
**Address:** Regeringsgatan 19, STOCKHOLM, SE

## Business Description
Music streaming platform.
"""


def test_sourcing_chat_prompt_is_in_catalog():
    prompts = default_prompts("sv")
    assert "dd.sourcing.chat.system" in prompts
    assert "search_companies" in prompts["dd.sourcing.chat.system"]
    assert "synlig text" in prompts["dd.sourcing.chat.visible_reply"]


def test_format_orgnr_normalizes_ten_and_twelve_digits():
    assert format_orgnr("5567037485") == "556703-7485"
    assert format_orgnr("556703-7485") == "556703-7485"
    assert format_orgnr("165567037485") == "556703-7485"


def test_candidates_from_search_markdown():
    found = candidates_from_mcp_text(_SEARCH_MD)
    assert len(found) == 1
    row = found[0]
    assert row.namn == "Spotify AB"
    assert row.organisationsnummer == "556703-7485"
    assert row.omrade == "Stockholm"
    assert "AB (STOCKHOLM)" in row.beskrivning


def test_candidates_from_lookup_markdown():
    found = candidates_from_mcp_text(_LOOKUP_MD, today=date(2026, 8, 28))
    assert len(found) == 1
    row = found[0]
    assert row.namn == "Spotify AB"
    assert row.organisationsnummer == "556703-7485"
    assert row.alder_ar == 20
    assert row.omrade == "Stockholm"
    assert "Music streaming" in row.beskrivning


def test_candidates_lookup_enriches_search_hit():
    found = candidates_from_mcp_text(f"{_SEARCH_MD}\n\n{_LOOKUP_MD}", today=date(2026, 8, 28))
    assert len(found) == 1
    row = found[0]
    assert row.alder_ar == 20
    assert "Music streaming" in row.beskrivning


def test_mcp_tools_to_openai_keeps_schema():
    converted = mcp_tools_to_openai(
        [
            {
                "name": "search_companies",
                "description": "Search companies",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
            {"name": "", "description": "skip"},
        ]
    )
    assert converted == [
        {
            "type": "function",
            "function": {
                "name": "search_companies",
                "description": "Search companies",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
    ]


def test_tool_calls_from_leaked_invoke_and_json():
    invoke = (
        '<invoke name="search_companies">'
        '<parameter name="query">IT Göteborg</parameter>'
        "</invoke>"
    )
    calls = tool_calls_from_leaked_markup(invoke)
    assert len(calls) == 1
    assert calls[0].function.name == "search_companies"
    assert "IT Göteborg" in calls[0].function.arguments

    json_block = (
        '<tool_call>{"name": "lookup_company", "arguments": {"orgnr": "556703-7485"}}</tool_call>'
    )
    lookup = tool_calls_from_leaked_markup(json_block)
    assert lookup[0].function.name == "lookup_company"
    assert tool_calls_from_leaked_markup('<invoke name="search_companies">') == []


def test_merge_candidates_upserts_by_orgnr():
    existing = [
        DdCandidateCompany(
            id="556111-1111",
            namn="Old AB",
            organisationsnummer="556111-1111",
            alder_ar=4,
            omrade="Malmö",
            resultat="oavsett",
        )
    ]
    incoming = [
        DdCandidateCompany(
            id="556111-1111",
            namn="New AB",
            organisationsnummer="556111-1111",
            alder_ar=8,
            omrade="Malmö",
            resultat="vinst",
        ),
        DdCandidateCompany(
            id="556222-2222",
            namn="Other AB",
            organisationsnummer="556222-2222",
            alder_ar=2,
            omrade="Göteborg",
            resultat="oavsett",
        ),
    ]
    merged = merge_candidates(existing, incoming)
    assert [row.organisationsnummer for row in merged] == ["556111-1111", "556222-2222"]
    assert merged[0].namn == "New AB"


def test_require_bolagsapi_key_fails_loud(monkeypatch):
    monkeypatch.setattr(settings, "bolagsapi_api_key", "")
    with pytest.raises(BolagsapiMcpError, match="BOLAGSAPI_API_KEY"):
        require_bolagsapi_key()


class _FakeMcp:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def list_tools(self) -> list[dict[str, object]]:
        return [
            {
                "name": "search_companies",
                "description": "Search companies",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
            {
                "name": "analyze_company_financials",
                "description": "Should be hidden from sourcing chat",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    async def call_tool(self, name: str, arguments: dict[str, object]) -> str:
        self.calls.append((name, arguments))
        return _SEARCH_MD


def _tool_reply() -> SimpleNamespace:
    return SimpleNamespace(
        content="",
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(
                    name="search_companies",
                    arguments='{"query": "IT Stockholm"}',
                ),
            )
        ],
    )


def _final_reply(text: str) -> SimpleNamespace:
    return SimpleNamespace(content=text, tool_calls=None)


@pytest.mark.asyncio
async def test_sourcing_chat_turn_parses_mcp_hits(client_db, monkeypatch):
    _client, factory = client_db
    monkeypatch.setattr(settings, "bolagsapi_api_key", "test-bolagsapi-key")
    fake = _FakeMcp()
    monkeypatch.setattr(
        "app.services.dd.company_mcp.BolagsapiMcpClient",
        lambda *args, **kwargs: fake,
    )
    turns = {"n": 0}

    seen_tools: list[list[str]] = []

    async def _tools(_messages: list, tools: list | None = None):
        turns["n"] += 1
        if tools:
            seen_tools.append([
                item["function"]["name"] for item in tools if item.get("function")
            ])
        if turns["n"] == 1:
            return _tool_reply()
        return _final_reply("Spotify AB (556703-7485) i Stockholm passar.")

    set_tools_completer(_tools)
    async with factory() as session:
        reply, candidates = await run_sourcing_chat_turn(session, customer_id=1, message="IT-bolag i Stockholm")
    assert "Spotify" in reply
    assert len(candidates) == 1
    assert candidates[0].organisationsnummer == "556703-7485"
    assert fake.calls == [("search_companies", {"query": "IT Stockholm"})]
    assert seen_tools
    assert "search_companies" in seen_tools[0]
    assert "analyze_company_financials" not in seen_tools[0]
    assert "search_duckduckgo" not in seen_tools[0]
    assert "search_wiki" not in seen_tools[0]


@pytest.mark.asyncio
async def test_sourcing_chat_turn_rejects_empty_message(client_db):
    _client, factory = client_db
    async with factory() as session:
        with pytest.raises(SourcingChatError, match="required"):
            await run_sourcing_chat_turn(session, customer_id=1, message="   ")


@pytest.mark.asyncio
async def test_sourcing_chat_asks_for_reply_after_empty_tool_turn(client_db, monkeypatch):
    _client, factory = client_db
    monkeypatch.setattr(settings, "bolagsapi_api_key", "test-bolagsapi-key")
    fake = _FakeMcp()
    monkeypatch.setattr(
        "app.services.dd.company_mcp.BolagsapiMcpClient",
        lambda *args, **kwargs: fake,
    )
    turns = {"n": 0}

    async def _tools(_messages: list, _tools: list | None = None):
        turns["n"] += 1
        if turns["n"] == 1:
            return _tool_reply()
        if turns["n"] == 2:
            return _final_reply("")
        return _final_reply("Spotify AB i Stockholm passar.")

    set_tools_completer(_tools)
    async with factory() as session:
        reply, candidates = await run_sourcing_chat_turn(session, customer_id=1, message="IT-bolag i Stockholm")
    assert reply == "Spotify AB i Stockholm passar."
    assert candidates[0].organisationsnummer == "556703-7485"
    assert turns["n"] == 3


@pytest.mark.asyncio
async def test_sourcing_chat_continues_when_allabolag_has_no_company(client_db, monkeypatch):
    _client, factory = client_db
    monkeypatch.setattr(settings, "bolagsapi_api_key", "")

    async def _lookup(orgnr: str):
        raise AllabolagNotFoundError(f"Allabolag has no company for {orgnr}")

    monkeypatch.setattr("app.services.dd.allabolag.lookup_company_row", _lookup)
    turns = {"n": 0}

    async def _tools(_messages: list, _tools: list | None = None):
        turns["n"] += 1
        if turns["n"] == 1:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    SimpleNamespace(
                        id="call_1",
                        function=SimpleNamespace(
                            name="lookup_company",
                            arguments='{"orgnr":"556332-8753"}',
                        ),
                    )
                ],
            )
        return _final_reply("Allabolag har inget bolag med 556332-8753.")

    set_tools_completer(_tools)
    async with factory() as session:
        reply, candidates = await run_sourcing_chat_turn(
            session,
            customer_id=1,
            message="Slå upp 556332-8753",
        )
    assert "556332-8753" in reply
    assert candidates == []


@pytest.mark.asyncio
async def test_sourcing_chat_fails_loud_on_rate_limit(client_db, monkeypatch):
    _client, factory = client_db
    monkeypatch.setattr(settings, "bolagsapi_api_key", "test-bolagsapi-key")

    class _RateLimited(_FakeMcp):
        async def call_tool(self, name: str, arguments: dict[str, object]) -> str:
            return "Rate limit exceeded"

    monkeypatch.setattr(
        "app.services.dd.company_mcp.BolagsapiMcpClient",
        lambda *args, **kwargs: _RateLimited(),
    )

    async def _tools(_messages: list, _tools: list | None = None):
        return _tool_reply()

    set_tools_completer(_tools)
    async with factory() as session:
        with pytest.raises(SourcingChatError, match="rate limit"):
            await run_sourcing_chat_turn(session, customer_id=1, message="Spotify")


@pytest.mark.asyncio
async def test_sourcing_chat_runs_leaked_invoke_as_tool(client_db, monkeypatch):
    _client, factory = client_db
    monkeypatch.setattr(settings, "bolagsapi_api_key", "test-bolagsapi-key")
    fake = _FakeMcp()
    monkeypatch.setattr(
        "app.services.dd.company_mcp.BolagsapiMcpClient",
        lambda *args, **kwargs: fake,
    )
    turns = {"n": 0}

    async def _tools(_messages: list, _tools: list | None = None):
        turns["n"] += 1
        if turns["n"] == 1:
            return _final_reply(
                '<invoke name="search_companies">'
                '<parameter name="query">IT Stockholm</parameter>'
                "</invoke>"
            )
        return _final_reply("Spotify AB i Stockholm passar.")

    set_tools_completer(_tools)
    async with factory() as session:
        reply, candidates = await run_sourcing_chat_turn(session, customer_id=1, message="IT-bolag")
    assert "Spotify" in reply
    assert candidates[0].organisationsnummer == "556703-7485"
    assert fake.calls == [("search_companies", {"query": "IT Stockholm"})]


@pytest.mark.asyncio
async def test_sourcing_chat_rejects_leaked_tool_markup(client_db, monkeypatch):
    _client, factory = client_db
    monkeypatch.setattr(settings, "bolagsapi_api_key", "test-bolagsapi-key")
    monkeypatch.setattr("app.services.dd.company_mcp.BolagsapiMcpClient", lambda: _FakeMcp())

    async def _tools(_messages: list, _tools: list | None = None):
        return _final_reply('<invoke name="search_companies">')

    set_tools_completer(_tools)
    async with factory() as session:
        with pytest.raises(SourcingChatError, match="invalid reply"):
            await run_sourcing_chat_turn(session, customer_id=1, message="IT-bolag")


@pytest.mark.asyncio
async def test_sourcing_chat_api_requires_campaign(client: AsyncClient):
    response = await client.post(
        "/dd/campaigns/99999/sourcing/chat",
        json={"message": "IT-bolag", "history": []},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_sourcing_chat_uses_allabolag_when_key_missing(client_db, monkeypatch):
    _client, factory = client_db
    monkeypatch.setattr(settings, "bolagsapi_api_key", "")
    called = {"n": 0}

    async def _search(query: str) -> list[dict]:
        called["n"] += 1
        assert query
        return [
            {
                "name": "Spotify AB",
                "orgnr": "5567037485",
                "location": {"municipality": "Stockholm"},
            }
        ]

    monkeypatch.setattr("app.services.dd.allabolag.search_company_rows", _search)
    turns = {"n": 0}

    async def _tools(_messages: list, _tools: list | None = None):
        turns["n"] += 1
        if turns["n"] == 1:
            return _tool_reply()
        return _final_reply("Spotify AB i Stockholm via Allabolag.")

    set_tools_completer(_tools)
    async with factory() as session:
        reply, candidates = await run_sourcing_chat_turn(session, customer_id=1, message="IT-bolag")
    assert "Spotify" in reply
    assert called["n"] == 1
    assert candidates[0].organisationsnummer == "556703-7485"


@pytest.mark.asyncio
async def test_sourcing_chat_api_returns_candidates(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "bolagsapi_api_key", "test-bolagsapi-key")
    monkeypatch.setattr("app.services.dd.company_mcp.BolagsapiMcpClient", lambda: _FakeMcp())
    turns = {"n": 0}

    async def _tools(_messages: list, _tools: list | None = None):
        turns["n"] += 1
        if turns["n"] == 1:
            return _tool_reply()
        return _final_reply("Spotify AB i Stockholm.")

    set_tools_completer(_tools)
    create = await client.post("/dd/campaigns", json={"title": "Chat hit test"})
    assert create.status_code == 201
    campaign_id = create.json()["id"]
    response = await client.post(
        f"/dd/campaigns/{campaign_id}/sourcing/chat",
        json={"message": "Musikbolag i Stockholm", "history": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert "Spotify" in body["reply"]
    assert body["candidates"][0]["organisationsnummer"] == "556703-7485"
