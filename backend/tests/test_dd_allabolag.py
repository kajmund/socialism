"""Tests for Allabolag Next.js parsing and company MCP routing."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.database.models import Persona
from app.llm import set_text_completer, set_tools_completer
from app.llm.chat import build_chat_system_prompt
from app.schemas.domain import EditablePersona, PersonaChatResponse
from app.services.dd.allabolag import (
    AllabolagError,
    AllabolagNotFoundError,
    candidate_from_allabolag,
    companies_from_person_roles,
    company_from_next_data,
    enrich_candidates,
    format_lookup_markdown,
    lookup_company_row,
    people_from_search_next_data,
    person_page_path,
    roles_from_person_next_data,
    search_companies_from_next_data,
    validate_orgnr,
)
from app.services.dd.bolagsapi_mcp import candidates_from_mcp_text
from app.services.dd.company_mcp import (
    COMPANY_TOOL_NAMES,
    CompanyMcpClient,
    CompanyMcpError,
    complete_text_with_company_tools,
    uses_bolagsapi,
)
from app.services.persona_chat import stream_library_chat_turn
from app.services.prompt_catalog import default_prompts
from app.services.prompt_store import ensure_default_configurations

_SEARCH_NEXT = {
    "props": {
        "pageProps": {
            "hydrationData": {
                "searchStore": {
                    "companies": {
                        "companies": [
                            {
                                "name": "Spotify AB",
                                "legalName": "Spotify AB",
                                "orgnr": "5567037485",
                                "companyId": "2K2GXM5I5YH40",
                                "revenue": "114518989",
                                "profit": "22229937",
                                "employees": "1271",
                                "location": {"municipality": "Stockholm", "county": "Stockholm"},
                                "visitorAddress": {
                                    "addressLine": "Regeringsgatan 19 5tr",
                                    "zipCode": "111 53",
                                    "postPlace": "Stockholm",
                                },
                                "currentIndustry": {"name": "Radio, TV-programbolag"},
                                "industries": [{"name": "Radio, TV-programbolag"}],
                            }
                        ]
                    }
                }
            }
        }
    }
}

_COMPANY_NEXT = {
    "props": {
        "pageProps": {
            "company": {
                "name": "Spotify AB",
                "orgnr": "5567037485",
                "companyId": "2K2GXM5I5YH40",
                "revenue": "114518989",
                "profit": "19299658",
                "employees": "1271",
                "registrationDate": "2006-05-10",
                "purpose": "Internetrelaterade tjänster inom digitala medier.",
                "location": {"municipality": "Stockholm"},
                "visitorAddress": {
                    "addressLine": "Regeringsgatan 19 5tr",
                    "zipCode": "111 53",
                    "postPlace": "Stockholm",
                },
                "status": {"status": "ACTIVE", "statusCode": "ACTIVE"},
                "companyType": {"name": "Aktiebolag"},
                "currentIndustry": {"name": "Radio, TV-programbolag"},
                "registeredForVat": True,
                "registeredForPayrollTax": True,
                "registryStatusEntries": [
                    {"label": "registeredForVat", "value": True},
                    {"label": "registeredForPrepayment", "value": True},
                    {"label": "registeredForPayrollTax", "value": True},
                ],
                "corporateStructure": {
                    "numberOfCompanies": 28,
                    "numberOfSubsidiaries": 26,
                    "parentCompanyName": None,
                    "parentCompanyOrganisationNumber": None,
                },
                "roles": {
                    "roleGroups": [
                        {
                            "name": "Board",
                            "roles": [
                                {"name": "Ada Ordförande", "role": "Ordförande"},
                                {"name": "Bo Ledamot", "role": "Ledamot"},
                            ],
                        }
                    ]
                },
                "signatories": ["Firman tecknas av styrelsen"],
                "naceIndustries": ["60.200 Radio- och TV-verksamhet"],
                "announcements": [{"date": "2026-03-01", "text": "Årsredovisning registrerad"}],
                "businessUnits": [{"name": "Stockholm HQ"}],
                "phone": "08-123 45 67",
                "mortgages": False,
                "paymentRemarks": False,
                "gaselle": False,
                "companyAccounts": [
                    {
                        "year": "2025",
                        "accounts": [
                            {"code": "SDI", "amount": "114518989"},
                            {"code": "DR", "amount": "19299658"},
                            {"code": "EBITDA", "amount": "13020137"},
                            {"code": "ANT", "amount": "1271"},
                            {"code": "EK", "amount": "65093974"},
                            {"code": "SEK", "amount": "80000000"},
                            {"code": "SUB", "amount": "2500000"},
                            {"code": "EKA", "amount": "60.1"},
                            {"code": "UTR", "amount": "0"},
                        ],
                    },
                    {
                        "year": "2024",
                        "accounts": [
                            {"code": "SDI", "amount": "100000000"},
                            {"code": "DR", "amount": "10000000"},
                        ],
                    },
                ],
            },
            "trademarks": {
                "trademarks": [
                    {"title": "SPOTIFY", "type": "Word"},
                    {"title": "Marrow", "type": "Word"},
                ]
            },
            "relatedCompanies": {
                "companies": [
                    {
                        "name": "Spotify Ltd",
                        "orgnr": "12345678",
                        "industryName": "Music",
                        "postPlace": "London",
                    },
                ]
            },
        }
    }
}


_PERSON_SEARCH_NEXT = {
    "props": {
        "pageProps": {
            "rolePersons": {
                "businessPersons": [
                    {
                        "name": "Erik Nils Gustav Fremred",
                        "personId": "10129399",
                        "numberOfRoles": 8,
                    },
                    {
                        "name": "Jesper Karl-Olof Thorzelius",
                        "personId": "13572158",
                        "numberOfRoles": 1,
                    },
                ]
            }
        }
    }
}

_PERSON_PAGE_NEXT = {
    "props": {
        "pageProps": {
            "rolePerson": {
                "name": "Erik Nils Gustav Fremred",
                "personId": "10129399",
                "roles": [
                    {"id": "5567958615", "role": "Ordförande", "name": "FA Consulting Group AB"},
                    {"id": "5567958615", "role": "Ledamot", "name": "FA Consulting Group AB"},
                    {"id": "5590855473", "role": "Ordförande", "name": "Devbrains AB"},
                    {"id": "NO123", "role": "Ledamot", "name": "Foreign AS"},
                ],
            }
        }
    }
}


def test_search_companies_from_next_data():
    rows = search_companies_from_next_data(_SEARCH_NEXT)
    assert len(rows) == 1
    assert rows[0]["name"] == "Spotify AB"


def test_people_from_search_next_data():
    people = people_from_search_next_data(_PERSON_SEARCH_NEXT)
    assert [row["personId"] for row in people] == ["10129399", "13572158"]


def test_companies_from_person_roles_dedupes_and_skips_foreign():
    roles = roles_from_person_next_data(_PERSON_PAGE_NEXT)
    rows = companies_from_person_roles(roles)
    assert rows == [
        {"name": "FA Consulting Group AB", "orgnr": "556795-8615"},
        {"name": "Devbrains AB", "orgnr": "559085-5473"},
    ]


def test_person_page_path():
    assert person_page_path("Erik Nils Gustav Fremred", "10129399") == (
        "https://www.allabolag.se/befattning/erik-nils-gustav-fremred/-/10129399"
    )


def test_company_from_next_data():
    row = company_from_next_data(_COMPANY_NEXT)
    assert row["registrationDate"] == "2006-05-10"
    assert [mark["title"] for mark in row["trademarks"]] == ["SPOTIFY", "Marrow"]


def test_candidate_from_search_card():
    row = search_companies_from_next_data(_SEARCH_NEXT)[0]
    candidate = candidate_from_allabolag(row, today=date(2026, 8, 28))
    assert candidate.organisationsnummer == "556703-7485"
    assert candidate.omrade == "Stockholm"
    assert candidate.resultat == "vinst"
    assert candidate.omsattning_sek == 114_518_989_000
    assert candidate.anstallda == 1271
    assert candidate.alder_ar == 0


def test_candidate_from_company_page():
    row = company_from_next_data(_COMPANY_NEXT)
    candidate = candidate_from_allabolag(row, today=date(2026, 8, 28))
    assert candidate.alder_ar == 20
    assert "digitala medier" in candidate.beskrivning
    assert candidate.omsattning_sek == 114_518_989_000
    assert candidate.fskatt is True
    assert candidate.moms is True
    assert candidate.arbetsgivaravgift is True
    assert candidate.koncern_bolag == 28
    assert candidate.koncern_dotter == 26
    assert [officer.namn for officer in candidate.styrelse] == ["Ada Ordförande", "Bo Ledamot"]
    assert candidate.varumarken == ["SPOTIFY (Word)", "Marrow (Word)"]
    assert [year.year for year in candidate.rakenskaper] == ["2025", "2024"]
    assert candidate.rakenskaper[0].soliditet_pct == "60.1"
    assert candidate.rakenskaper[0].utdelning_sek == 2_500_000_000
    assert candidate.rakenskaper[0].eget_kapital_sek == 80_000_000_000
    poster_by_code = {fig.kod: fig for fig in candidate.rakenskaper[0].poster}
    assert poster_by_code["EK"].namn == "Avskrivningar och nedskrivningar"
    assert poster_by_code["SEK"].namn == "Eget kapital"
    assert poster_by_code["SUB"].namn == "Föreslagen utdelning"
    assert candidate.sni == ["60.200 Radio- och TV-verksamhet"]
    assert candidate.handelser == ["2026-03-01 — Årsredovisning registrerad"]
    assert candidate.arbetsstallen == ["Stockholm HQ"]
    assert candidate.relaterade_bolag == []
    assert candidate.telefon == "08-123 45 67"
    assert candidate.foretagshypotek is False
    assert candidate.betalningsanmarkning is False
    assert candidate.gasell is False


def test_lookup_markdown_is_parseable():
    row = company_from_next_data(_COMPANY_NEXT)
    text = format_lookup_markdown(row, today=date(2026, 8, 28))
    found = candidates_from_mcp_text(text, today=date(2026, 8, 28))
    assert len(found) == 1
    assert found[0].organisationsnummer == "556703-7485"
    assert found[0].alder_ar == 20
    assert found[0].omsattning_sek == 114_518_989_000
    assert found[0].anstallda == 1271
    assert found[0].resultat == "vinst"
    assert "Styrelse och roller" in text
    assert "Ada Ordförande" in text
    assert "## Räkenskaper" in text
    assert "### 2024" in text
    assert "SPOTIFY (Word)" in text
    assert "F-skatt: Ja" in text
    assert "26 dotterbolag" in text
    assert "Föreslagen utdelning" in text
    assert "Eget kapital" in text
    assert "Avskrivningar och nedskrivningar" in text
    assert "60.200 Radio- och TV-verksamhet" in text
    assert "Årsredovisning registrerad" in text
    assert "Relaterade bolag" not in text


@pytest.mark.asyncio
async def test_enrich_candidates_uses_company_page(monkeypatch):
    row = company_from_next_data(_COMPANY_NEXT)

    async def _lookup(orgnr: str):
        assert orgnr == "556703-7485"
        return row

    monkeypatch.setattr("app.services.dd.allabolag.lookup_company_row", _lookup)
    thin = candidate_from_allabolag(search_companies_from_next_data(_SEARCH_NEXT)[0])
    assert thin.styrelse == []
    enriched = await enrich_candidates([thin])
    assert enriched[0].id == thin.id
    assert enriched[0].styrelse[0].namn == "Ada Ordförande"
    assert enriched[0].rakenskaper[0].year == "2025"
    assert enriched[0].rakenskaper[0].utdelning_sek == 2_500_000_000


@pytest.mark.asyncio
async def test_lookup_missing_company_raises_not_found(monkeypatch):
    async def _html(_url: str) -> str:
        return (
            '<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"hydrationData":{"searchStore":'
            '{"companies":{"companies":[]}}}}}}'
            "</script>"
        )

    monkeypatch.setattr("app.services.dd.allabolag._get_html", _html)
    with pytest.raises(AllabolagNotFoundError, match="556332-8753"):
        await lookup_company_row("556332-8753")


@pytest.mark.asyncio
async def test_lookup_tool_returns_not_found_without_raising(monkeypatch):
    monkeypatch.setattr(settings, "bolagsapi_api_key", "")

    async def _lookup(_orgnr: str):
        raise AllabolagNotFoundError("Allabolag has no company for 556332-8753")

    monkeypatch.setattr("app.services.dd.allabolag.lookup_company_row", _lookup)
    async with CompanyMcpClient() as client:
        text, candidates = await client.call_tool_with_candidates(
            "lookup_company",
            {"orgnr": "556332-8753"},
        )
    assert "556332-8753" in text
    assert candidates == []


@pytest.mark.asyncio
async def test_enrich_keeps_thin_candidate_when_lookup_missing(monkeypatch):
    async def _lookup(_orgnr: str):
        raise AllabolagNotFoundError("Allabolag has no company for 556332-8753")

    monkeypatch.setattr("app.services.dd.allabolag.lookup_company_row", _lookup)
    thin = candidate_from_allabolag(search_companies_from_next_data(_SEARCH_NEXT)[0])
    out = await enrich_candidates([thin])
    assert out == [thin]


@pytest.mark.asyncio
async def test_enrich_skips_when_full_accounts_exist(monkeypatch):
    async def _lookup(_orgnr: str):
        raise AssertionError("lookup should not run when poster already exist")

    monkeypatch.setattr("app.services.dd.allabolag.lookup_company_row", _lookup)
    full = candidate_from_allabolag(company_from_next_data(_COMPANY_NEXT))
    assert full.rakenskaper[0].poster
    out = await enrich_candidates([full])
    assert out[0] is full


def test_loss_maps_to_forlust():
    row = search_companies_from_next_data(_SEARCH_NEXT)[0]
    row = {**row, "profit": "-1200"}
    candidate = candidate_from_allabolag(row)
    assert candidate.resultat == "förlust"


@pytest.mark.asyncio
async def test_validate_orgnr():
    text = await validate_orgnr("5567037485")
    assert "556703-7485" in text
    with pytest.raises(AllabolagError):
        await validate_orgnr("12")


def test_uses_bolagsapi_follows_key(monkeypatch):
    monkeypatch.setattr(settings, "bolagsapi_api_key", "")
    assert uses_bolagsapi() is False
    monkeypatch.setattr(settings, "bolagsapi_api_key", "secret")
    assert uses_bolagsapi() is True
    assert "search_companies" in COMPANY_TOOL_NAMES
    assert "lookup_company" in COMPANY_TOOL_NAMES


def test_expert_search_prompts_are_in_catalog():
    prompts = default_prompts("sv")
    assert "search_duckduckgo" in prompts["chat.expert.search_tools"]
    assert "search_wiki" in prompts["chat.expert.search_tools"]
    assert "search_duckduckgo" in prompts["panel.expert.tools"]
    assert "search_companies" in prompts["panel.expert.tools"]
    assert "Sök inte efter samma siffror" in prompts["panel.expert.tools"]
    assert "Slå inte upp" in prompts["panel.dd.expert.score"]
    assert "Sök inte efter nyckeltal du redan har fått" in prompts[
        "chat.expert.search_tools"
    ]


@pytest.mark.asyncio
async def test_expert_tool_loop_includes_search_tools():
    seen: list[list[str]] = []

    async def _tools(_messages: list, tools: list | None = None):
        if tools:
            seen.append(
                [item["function"]["name"] for item in tools if item.get("function")]
            )
        return SimpleNamespace(content="klart", tool_calls=None)

    set_tools_completer(_tools)
    try:
        reply = await complete_text_with_company_tools(
            [{"role": "user", "content": "kolla fakta"}]
        )
    finally:
        set_tools_completer(None)

    assert reply == "klart"
    assert seen
    assert "search_companies" in seen[0]
    assert "search_duckduckgo" in seen[0]
    assert "search_wiki" in seen[0]


@pytest.mark.asyncio
async def test_expert_tool_loop_respects_allowed_tools():
    seen: list[list[str]] = []

    async def _tools(_messages: list, tools: list | None = None):
        if tools:
            seen.append(
                [item["function"]["name"] for item in tools if item.get("function")]
            )
        return SimpleNamespace(content="klart", tool_calls=None)

    set_tools_completer(_tools)
    try:
        reply = await complete_text_with_company_tools(
            [{"role": "user", "content": "kolla fakta"}],
            allowed_tools=frozenset({"lookup_company"}),
        )
    finally:
        set_tools_completer(None)

    assert reply == "klart"
    assert seen == [["lookup_company"]]


@pytest.mark.asyncio
async def test_company_tool_loop_keeps_going_when_lookup_lacks_orgnr():
    turns = {"n": 0}

    async def _tools(messages: list, tools: list | None = None):
        turns["n"] += 1
        if turns["n"] == 1:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    SimpleNamespace(
                        id="call_1",
                        function=SimpleNamespace(
                            name="lookup_company",
                            arguments='{"name":"Johan Hammarin"}',
                        ),
                    )
                ],
            )
        blob = " ".join(str(row.get("content") or "") for row in messages)
        assert "requires orgnr" in blob
        return SimpleNamespace(content="Jag behöver organisationsnummer.", tool_calls=None)

    set_tools_completer(_tools)
    try:
        reply = await complete_text_with_company_tools(
            [{"role": "user", "content": "Vem är Johan Hammarin?"}],
            allowed_tools=frozenset({"lookup_company"}),
        )
    finally:
        set_tools_completer(None)

    assert reply == "Jag behöver organisationsnummer."
    assert turns["n"] == 2


@pytest.mark.asyncio
async def test_company_tool_loop_still_fails_loud_on_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "bolagsapi_api_key", "test-bolagsapi-key")

    class _RateLimited:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def list_tools(self):
            return [
                {
                    "name": "lookup_company",
                    "description": "Look up a company",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"orgnr": {"type": "string"}},
                    },
                }
            ]

        async def call_tool(self, name: str, arguments: dict):
            return "Rate limit exceeded"

    monkeypatch.setattr(
        "app.services.dd.company_mcp.BolagsapiMcpClient",
        lambda *args, **kwargs: _RateLimited(),
    )

    async def _tools(_messages: list, _tools: list | None = None):
        return SimpleNamespace(
            content="",
            tool_calls=[
                SimpleNamespace(
                    id="call_1",
                    function=SimpleNamespace(
                        name="lookup_company",
                        arguments='{"orgnr":"556703-7485"}',
                    ),
                )
            ],
        )

    set_tools_completer(_tools)
    try:
        with pytest.raises(CompanyMcpError, match="rate limit"):
            await complete_text_with_company_tools(
                [{"role": "user", "content": "Slå upp Spotify"}],
                allowed_tools=frozenset({"lookup_company"}),
            )
    finally:
        set_tools_completer(None)


def test_expert_chat_prompt_uses_expert_fields_not_politics():
    profile = EditablePersona(
        name="Eva Personanalys Svensson",
        kompetensomrade="Hitta information om personer i en bolagsstyrelse",
        yrkesbakgrund="18 år som bakgrundsutredare",
        beskrivning="Kartlägger styrelseledamöter",
        radgivningsstil="Rak och korrekt",
    )
    text = build_chat_system_prompt(
        profile,
        "character",
        prompts=default_prompts("sv"),
        profile_kind="expert",
    )
    assert "Hitta information om personer" in text
    assert "Kartlägger styrelseledamöter" in text
    assert "du är den här experten" in text
    assert "Parti:" not in text


@pytest.mark.asyncio
async def test_expert_library_chat_uses_company_tools():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    seen_tools: list[list[str]] = []

    async def _tools(messages: list, tools: list | None = None):
        if tools:
            seen_tools.append(
                [item["function"]["name"] for item in tools if item.get("function")]
            )
        blob = " ".join(str(row.get("content") or "") for row in messages)
        assert "search_companies" in blob
        assert "search_duckduckgo" in blob
        return SimpleNamespace(content="Jag slår upp Spotify AB.", tool_calls=None)

    set_tools_completer(_tools)
    try:
        async with factory() as session:
            await ensure_default_configurations(session)
            session.add(
                Persona(
                    id="e-fin",
                    customer_id=1,
                    kind="expert",
                    name="Finansexpert",
                    age=50,
                    occ="Analytiker",
                    district="Stockholm",
                    profile={"name": "Finansexpert", "yrke": "Analytiker"},
                )
            )
            await session.commit()
            parts: list[str] = []
            async for item in stream_library_chat_turn(
                session,
                persona_id="e-fin",
                mode="interview",
                message="Vad vet du om Spotify AB?",
            ):
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, PersonaChatResponse):
                    assert "Spotify" in item.reply
    finally:
        set_tools_completer(None)
        await engine.dispose()

    assert seen_tools
    assert "search_companies" in seen_tools[0]
    assert "lookup_company" in seen_tools[0]
    assert "search_duckduckgo" in seen_tools[0]
    assert "search_wiki" in seen_tools[0]
    assert "Jag slår upp Spotify AB." in "".join(parts)


@pytest.mark.asyncio
async def test_expert_library_chat_uses_configured_tools_only():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    seen_tools: list[list[str] | None] = []

    async def _tools(messages: list, tools: list | None = None):
        if tools:
            seen_tools.append(
                [item["function"]["name"] for item in tools if item.get("function")]
            )
        blob = " ".join(str(row.get("content") or "") for row in messages)
        assert "search_wiki" in blob
        assert "search_companies" not in blob
        return SimpleNamespace(content="Jag slår upp Wikipedia.", tool_calls=None)

    set_tools_completer(_tools)
    try:
        async with factory() as session:
            await ensure_default_configurations(session)
            session.add(
                Persona(
                    id="e-wiki",
                    customer_id=1,
                    kind="expert",
                    name="Wiki-expert",
                    age=50,
                    occ="Analytiker",
                    district="Stockholm",
                    profile={"name": "Wiki-expert"},
                    tools=["search_wiki"],
                )
            )
            await session.commit()
            async for item in stream_library_chat_turn(
                session,
                persona_id="e-wiki",
                mode="interview",
                message="Vad är Spotify?",
            ):
                if isinstance(item, PersonaChatResponse):
                    assert "Wikipedia" in item.reply
    finally:
        set_tools_completer(None)
        await engine.dispose()

    assert seen_tools == [["search_wiki"]]


@pytest.mark.asyncio
async def test_expert_library_chat_without_tools_skips_tool_loop():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    tool_calls = 0

    async def _tools(_messages: list, _tools: list | None = None):
        nonlocal tool_calls
        tool_calls += 1
        return SimpleNamespace(content="borde inte anropas", tool_calls=None)

    async def _complete(_messages, *, model=None):
        return "Inga verktyg här."

    set_tools_completer(_tools)
    set_text_completer(_complete)
    try:
        async with factory() as session:
            await ensure_default_configurations(session)
            session.add(
                Persona(
                    id="e-none",
                    customer_id=1,
                    kind="expert",
                    name="Utan verktyg",
                    age=50,
                    occ="Analytiker",
                    district="Stockholm",
                    profile={"name": "Utan verktyg"},
                    tools=[],
                )
            )
            await session.commit()
            async for item in stream_library_chat_turn(
                session,
                persona_id="e-none",
                mode="interview",
                message="Hej",
            ):
                if isinstance(item, PersonaChatResponse):
                    assert item.reply == "Inga verktyg här."
    finally:
        set_tools_completer(None)
        set_text_completer(None)
        await engine.dispose()

    assert tool_calls == 0
