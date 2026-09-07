from __future__ import annotations

import pytest

from app.services.rattsunderlag.lagen_nu_mock import MockLagenNuClient
from app.services.rattsunderlag.research import run_rattsunderlag_research
from app.services.rattsunderlag.schemas import SearchPlan


@pytest.mark.asyncio
async def test_research_attributes_only_retrieved_sources(client_db):
    _http, factory = client_db

    async def planner(_fraga: str, _prompts: dict[str, str]) -> SearchPlan:
        return SearchPlan(queries=["upphandling"])

    async def summarizer(_fraga: str, _kallor: str, _prompts: dict[str, str]) -> str:
        return (
            "Leverantörer ska behandlas lika. [[ref:2016:1145]] "
            "Ett påhittat mål styr inte. [[ref:NJA 1999 s. 1]]"
        )

    async with factory() as session:
        result = await run_rattsunderlag_research(
            fraga="Gäller likabehandling i LOU?",
            customer_id=1,
            language="sv",
            session=session,
            client=MockLagenNuClient(),
            planner=planner,
            summarizer=summarizer,
        )

    assert result.lagtext[0].sfs_id == "2016:1145"
    assert result.praxis[0].referens == "HFD 2019 ref. 65"
    assert result.forarbeten[0].referens == "prop. 2015/16:195"
    assert result.claims[0].source_refs == ["2016:1145"]
    assert "NJA 1999 s. 1" not in result.sammanfattning
    assert "[[ref:" not in result.sammanfattning
    assert result.unanswered
    assert result.sourcing_status == "partial"


@pytest.mark.asyncio
async def test_research_abbreviations_do_not_orphan_citations(client_db):
    _http, factory = client_db

    async def planner(_fraga: str, _prompts: dict[str, str]) -> SearchPlan:
        return SearchPlan(queries=["upphandling"])

    async def summarizer(_fraga: str, _kallor: str, _prompts: dict[str, str]) -> str:
        return (
            "Enligt 4 kap. 1 § LOU ska myndigheten behandla leverantörer lika. "
            "[[ref:2016:1145]]"
        )

    async with factory() as session:
        result = await run_rattsunderlag_research(
            fraga="Gäller likabehandling i LOU?",
            customer_id=1,
            language="sv",
            session=session,
            client=MockLagenNuClient(),
            planner=planner,
            summarizer=summarizer,
        )

    assert "[[ref:" not in result.sammanfattning
    assert result.unanswered == []
    assert result.claims[0].source_refs == ["2016:1145"]
    assert "4 kap. 1 §" in result.claims[0].text
    assert result.sourcing_status == "complete"


@pytest.mark.asyncio
async def test_research_no_sources_does_not_invent(client_db):
    _http, factory = client_db

    async def planner(_fraga: str, _prompts: dict[str, str]) -> SearchPlan:
        return SearchPlan(queries=["xyzzy-no-hit"])

    async def summarizer(_fraga: str, _kallor: str, _prompts: dict[str, str]) -> str:
        raise AssertionError("summarizer must not run when there are no sources")

    async with factory() as session:
        result = await run_rattsunderlag_research(
            fraga="Finns det en lag om xyzzy?",
            customer_id=1,
            language="sv",
            session=session,
            client=MockLagenNuClient(),
            planner=planner,
            summarizer=summarizer,
        )

    assert result.lagtext == []
    assert result.praxis == []
    assert result.forarbeten == []
    assert result.sourcing_status == "no_sources_found"
    assert "fabricerats" in result.sammanfattning
