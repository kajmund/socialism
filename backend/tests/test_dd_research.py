"""Tests for deterministic DD research (group map, then person investigations)."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from app.services import jobs as jobs_service
from app.services.dd import research as research_mod
from app.services.dd.allabolag import AllabolagError, AllabolagNotFoundError, GroupCompany
from app.services.dd.research import (
    _host_matches,
    _name_stems,
    _pick_social_hit,
    _social_search_error,
    _social_search_miss,
    extract_orgnr,
    format_research_brief,
    run_dd_research,
    social_search_query,
)
from app.services.dd.schemas import (
    DdCandidateCompany,
    DdOfficer,
    DdResearchCompany,
    DdResearchDossier,
    DdResearchPerson,
)
from app.services.panel.structured_scoring import _candidate_brief


async def _empty_group(_orgnr: str) -> list[GroupCompany]:
    return []


def _candidate(**updates: object) -> DdCandidateCompany:
    data: dict[str, object] = {
        "id": "556000-0001",
        "namn": "Mål AB",
        "organisationsnummer": "556000-0001",
        "alder_ar": 10,
        "omrade": "Stockholm",
        "resultat": "vinst",
        "omsattning_sek": 5_000_000,
        "anstallda": 12,
        "styrelse": [DdOfficer(namn="Eva Ägare", roll="Ordförande", grupp="Styrelse")],
        "moderbolag": "Moder AB (556000-0002)",
    }
    data.update(updates)
    return DdCandidateCompany.model_validate(data)


def test_social_search_picks_on_site_hits() -> None:
    assert social_search_query("Eva Ägare", ("linkedin.com",)) == '"Eva Ägare" site:linkedin.com'
    assert social_search_query("Eva Ägare", ("x.com", "twitter.com")) == (
        '"Eva Ägare" (site:x.com OR site:twitter.com)'
    )
    assert _host_matches("https://www.linkedin.com/in/eva", ("linkedin.com",))
    assert _host_matches("https://x.com/eva", ("x.com", "twitter.com"))
    assert not _host_matches("https://example.test/eva", ("linkedin.com",))
    title, url = _pick_social_hit(
        [
            {"title": "Off site", "url": "https://example.test/eva"},
            {"title": "Eva Ägare", "url": "https://www.linkedin.com/in/eva"},
        ],
        ("linkedin.com",),
    )
    assert url == "https://www.linkedin.com/in/eva"
    assert title == "Eva Ägare"
    assert _social_search_miss(
        [{"error": "Inga DuckDuckGo-träffar. Prova en kortare eller mer konkret fråga."}]
    )
    assert _social_search_error(
        [{"error": "Inga DuckDuckGo-träffar. Prova en kortare eller mer konkret fråga."}]
    ) == ""
    assert _social_search_miss(
        [{"error": "duckduckgo search failed: No results found."}]
    )
    assert _social_search_error(
        [{"error": "duckduckgo search failed: No results found."}]
    ) == ""
    assert _social_search_error([{"error": "DuckDuckGo svarade 503"}]) == "DuckDuckGo svarade 503"


def _allabolag_row(
    name: str,
    orgnr: str,
    *,
    parent: tuple[str, str] | None = None,
    officers: list[tuple[str, str]] | None = None,
    subsidiaries: int | None = None,
    companies: int | None = None,
) -> dict[str, object]:
    structure: dict[str, object] = {}
    if parent is not None:
        structure["parentCompanyName"] = parent[0]
        structure["parentCompanyOrganisationNumber"] = parent[1]
    if subsidiaries is not None:
        structure["numberOfSubsidiaries"] = subsidiaries
    if companies is not None:
        structure["numberOfCompanies"] = companies
    return {
        "name": name,
        "orgnr": orgnr,
        "revenue": 1000,
        "employees": 5,
        "profit": 10,
        "corporateStructure": structure,
        "relatedCompanies": [{"name": "Syskon AB", "orgnr": "556000-0003"}],
        "roles": {
            "roleGroups": [
                {
                    "name": "Styrelse",
                    "roles": [{"name": namn, "role": roll} for namn, roll in (officers or [])],
                }
            ]
        },
    }


def test_stored_relaterat_companies_are_dropped() -> None:
    dossier = DdResearchDossier.model_validate(
        {
            "companies": [
                {"namn": "Mål AB", "orgnr": "556000-0001", "relation": "kandidat"},
                {"namn": "Syskon AB", "orgnr": "556000-0003", "relation": "relaterat"},
            ],
            "people": [],
            "leftover": [],
            "job_id": "job_old",
        }
    )
    assert [row.namn for row in dossier.companies] == ["Mål AB"]


def test_constructed_companies_are_kept() -> None:
    dossier = DdResearchDossier(
        companies=[
            DdResearchCompany(
                namn="Mål AB",
                orgnr="556000-0001",
                relation="kandidat",
            )
        ],
        leftover=["Allabolag anger 6 bolag i koncernen, kartlade 1"],
        job_id="job_live",
    )
    assert [row.namn for row in dossier.companies] == ["Mål AB"]


def test_extract_orgnr_from_parent() -> None:
    assert extract_orgnr("Hammarin Invest AB (556581-9975)") == "556581-9975"
    assert extract_orgnr("Inget nummer här") == ""


def test_name_stems_strip_legal_suffix() -> None:
    assert _name_stems("Ides Technology AB") == ["Ides Technology", "Ides"]
    assert _name_stems("Mål AB") == ["Mål"]


@pytest.mark.asyncio
async def test_research_maps_group_and_lists_people() -> None:
    async def lookup_row(orgnr: str) -> dict[str, object]:
        if "0001" in orgnr:
            return _allabolag_row(
                "Mål AB",
                "556000-0001",
                parent=("Moder AB", "556000-0002"),
                officers=[("Eva Ägare", "Ordförande")],
                subsidiaries=2,
            )
        if "0002" in orgnr:
            return _allabolag_row(
                "Moder AB",
                "556000-0002",
                officers=[("Eva Ägare", "Ordförande"), ("Bo Ledamot", "Ledamot")],
                companies=6,
            )
        if "0004" in orgnr:
            return _allabolag_row(
                "Mål AB",
                "556000-0004",
                parent=("Mål AB", "556000-0001"),
                officers=[("Bo Ledamot", "Ledamot")],
            )
        if "0003" in orgnr:
            raise AssertionError("related companies must not be looked up")
        raise AllabolagNotFoundError(orgnr)

    async def search_rows(query: str) -> list[dict[str, object]]:
        if query == "Mål AB":
            return [
                {"name": "Mål AB", "orgnr": "556000-0001"},
                {"name": "Mål AB", "orgnr": "556000-0004"},
            ]
        if query == "Moder AB":
            return [{"name": "Moder AB", "orgnr": "556000-0002"}]
        return []

    dossier = await run_dd_research(
        _candidate(),
        mode="group",
        job_id="job_test",
        lookup_row=lookup_row,
        search_rows=search_rows,
    )
    by_orgnr = {row.orgnr: row for row in dossier.companies}
    assert by_orgnr["556000-0001"].relation == "kandidat"
    assert by_orgnr["556000-0002"].relation == "moderbolag"
    assert by_orgnr["556000-0004"].relation == "dotterbolag"
    assert by_orgnr["556000-0001"].parent_orgnr == "556000-0002"
    assert by_orgnr["556000-0002"].parent_orgnr == ""
    assert by_orgnr["556000-0004"].parent_orgnr == "556000-0001"
    assert "556000-0003" not in by_orgnr
    assert any("Allabolag listar 6 bolag i koncernen, kartlade 3" in item for item in dossier.leftover)
    assert {person.namn for person in dossier.people} == {"Eva Ägare", "Bo Ledamot"}
    eva = next(person for person in dossier.people if person.namn == "Eva Ägare")
    assert len(eva.poster) == 2
    assert eva.web_hits == []
    assert eva.bolag == []
    brief = format_research_brief(dossier)
    assert "Bolag i koncernen" in brief
    assert "Eva Ägare" in brief
    assert "Syskon" not in brief


@pytest.mark.asyncio
async def test_research_maps_siblings_and_their_subsidiaries() -> None:
    async def lookup_row(orgnr: str) -> dict[str, object]:
        if "0001" in orgnr:
            return _allabolag_row(
                "Mål AB",
                "556000-0001",
                parent=("Moder AB", "556000-0002"),
                officers=[("Eva Ägare", "Ordförande")],
            )
        if "0002" in orgnr:
            return _allabolag_row(
                "Moder AB",
                "556000-0002",
                officers=[("Eva Ägare", "Ordförande")],
                companies=5,
            )
        if "0005" in orgnr:
            return _allabolag_row(
                "Moder Partner AB",
                "556000-0005",
                parent=("Moder AB", "556000-0002"),
                officers=[("Bo Ledamot", "Ledamot")],
            )
        if "0006" in orgnr:
            return _allabolag_row(
                "Moder Partner Dotter AB",
                "556000-0006",
                parent=("Moder Partner AB", "556000-0005"),
                officers=[("Bo Ledamot", "Ledamot")],
            )
        if "0003" in orgnr:
            raise AssertionError("related companies must not be looked up")
        raise AllabolagNotFoundError(orgnr)

    async def search_rows(query: str) -> list[dict[str, object]]:
        if query in {"Moder AB", "Moder"}:
            return [
                {"name": "Moder AB", "orgnr": "556000-0002"},
                {"name": "Moder Partner AB", "orgnr": "556000-0005"},
                {"name": "Alviks Biltvätt AB", "orgnr": "556000-0003"},
            ]
        if query in {"Moder Partner AB", "Moder Partner"}:
            return [
                {"name": "Moder Partner AB", "orgnr": "556000-0005"},
                {"name": "Moder Partner Dotter AB", "orgnr": "556000-0006"},
            ]
        if query in {"Mål AB", "Mål"}:
            return [{"name": "Mål AB", "orgnr": "556000-0001"}]
        return []

    dossier = await run_dd_research(
        _candidate(),
        mode="group",
        lookup_row=lookup_row,
        search_rows=search_rows,
    )
    by_orgnr = {row.orgnr: row for row in dossier.companies}
    assert by_orgnr["556000-0002"].relation == "moderbolag"
    assert by_orgnr["556000-0001"].relation == "kandidat"
    assert by_orgnr["556000-0005"].relation == "dotterbolag"
    assert by_orgnr["556000-0005"].parent_orgnr == "556000-0002"
    assert by_orgnr["556000-0006"].relation == "dotterbolag"
    assert by_orgnr["556000-0006"].parent_orgnr == "556000-0005"
    assert "556000-0003" not in by_orgnr


@pytest.mark.asyncio
async def test_research_investigates_selected_people() -> None:
    async def lookup_row(orgnr: str) -> dict[str, object]:
        if "0001" in orgnr:
            return _allabolag_row(
                "Mål AB",
                "556000-0001",
                parent=("Moder AB", "556000-0002"),
                officers=[("Eva Ägare", "Ordförande")],
            )
        if "0002" in orgnr:
            return _allabolag_row(
                "Moder AB",
                "556000-0002",
                officers=[("Eva Ägare", "Ordförande"), ("Bo Ledamot", "Ledamot")],
            )
        raise AllabolagNotFoundError(orgnr)

    async def lookup_person(query: str) -> list[dict[str, object]]:
        if query == "Eva Ägare":
            return [
                {"name": "Mål AB", "orgnr": "556000-0001"},
                {"name": "Eva Holding AB", "orgnr": "556000-0099"},
            ]
        raise AssertionError(f"unexpected person lookup: {query}")

    def web_search(query: str, number_of_result_pages: int = 3) -> list[dict[str, object]]:
        assert "Eva Ägare" in query
        if "linkedin.com" in query:
            return [{"title": "Eva Ägare", "url": "https://www.linkedin.com/in/eva"}]
        if "instagram.com" in query:
            return [{"error": "duckduckgo search failed: No results found."}]
        return [{"error": "Inga DuckDuckGo-träffar. Prova en kortare eller mer konkret fråga."}]

    async def group_search(query: str) -> list[dict[str, object]]:
        if query == "Mål AB":
            return [{"name": "Mål AB", "orgnr": "556000-0001"}]
        if query == "Moder AB":
            return [{"name": "Moder AB", "orgnr": "556000-0002"}]
        return []

    group = await run_dd_research(
        _candidate(),
        mode="group",
        lookup_row=lookup_row,
        search_rows=group_search,
    )
    dossier = await run_dd_research(
        _candidate(),
        mode="people",
        person_names=["Eva Ägare"],
        existing=group,
        lookup_person=lookup_person,
        web_search=web_search,
    )
    eva = next(person for person in dossier.people if person.namn == "Eva Ägare")
    bo = next(person for person in dossier.people if person.namn == "Bo Ledamot")
    assert [row.namn for row in eva.bolag] == ["Mål AB", "Eva Holding AB"]
    by_network = {hit.natverk: hit for hit in eva.web_hits}
    assert list(by_network) == ["LinkedIn", "Facebook", "Instagram", "X", "TikTok"]
    assert by_network["LinkedIn"].url == "https://www.linkedin.com/in/eva"
    assert by_network["Facebook"].url == ""
    assert all("Webbsök:" not in item for item in dossier.leftover)
    assert "Socialt: LinkedIn: Eva Ägare (https://www.linkedin.com/in/eva)" in format_research_brief(
        dossier
    )
    assert "ingen träff" not in format_research_brief(dossier)
    assert bo.bolag == []
    assert bo.web_hits == []
    assert all("Inga bolag för person" not in item for item in dossier.leftover)


@pytest.mark.asyncio
async def test_people_research_leftover_when_person_has_no_roles() -> None:
    group = DdResearchDossier(
        companies=[
            DdResearchCompany(
                namn="Mål AB",
                orgnr="556000-0001",
                relation="kandidat",
            )
        ],
        people=[DdResearchPerson(namn="Eva Ägare", roll="Ordförande")],
    )

    async def lookup_person(_name: str) -> list[dict[str, object]]:
        return []

    dossier = await run_dd_research(
        _candidate(),
        mode="people",
        person_names=["Eva Ägare"],
        existing=group,
        lookup_person=lookup_person,
        web_search=lambda *_args, **_kwargs: [],
    )
    assert any("Inga bolag för person: Eva Ägare" in item for item in dossier.leftover)


@pytest.mark.asyncio
async def test_people_research_keeps_companies_already_in_group() -> None:
    group = DdResearchDossier(
        companies=[
            DdResearchCompany(
                namn="Yoga Fremred AB",
                orgnr="559358-2603",
                relation="kandidat",
            )
        ],
        people=[DdResearchPerson(namn="Erik Nils Gustav Fremred", roll="Ledamot")],
    )

    async def lookup_person(_name: str) -> list[dict[str, object]]:
        return [
            {"name": "FA Consulting Group AB", "orgnr": "556795-8615"},
            {"name": "Devbrains AB", "orgnr": "559085-5473"},
            {"name": "Yoga Fremred AB", "orgnr": "559358-2603"},
            {"name": "Aktiebolaget Inte Dumt Alls", "orgnr": "559489-4759"},
        ]

    dossier = await run_dd_research(
        _candidate(),
        mode="people",
        person_names=["Erik Nils Gustav Fremred"],
        existing=group,
        lookup_person=lookup_person,
        web_search=lambda *_args, **_kwargs: [],
    )
    erik = next(person for person in dossier.people if person.namn == "Erik Nils Gustav Fremred")
    assert [row.namn for row in erik.bolag] == [
        "FA Consulting Group AB",
        "Devbrains AB",
        "Yoga Fremred AB",
        "Aktiebolaget Inte Dumt Alls",
    ]


@pytest.mark.asyncio
async def test_research_leftover_on_not_found() -> None:
    async def lookup_row(orgnr: str) -> dict[str, object]:
        raise AllabolagNotFoundError(orgnr)

    dossier = await run_dd_research(
        _candidate(),
        mode="group",
        lookup_row=lookup_row,
    )
    assert any("Bolag saknas" in item for item in dossier.leftover)
    assert {person.namn for person in dossier.people} == {"Eva Ägare"}
    assert all("sökträff" not in item for item in dossier.leftover)


@pytest.mark.asyncio
async def test_research_fails_loud_on_allabolag_error() -> None:
    async def lookup_row(orgnr: str) -> dict[str, object]:
        raise AllabolagError("Allabolag HTTP 429")

    with pytest.raises(AllabolagError, match="429"):
        await run_dd_research(
            _candidate(),
            mode="group",
            lookup_row=lookup_row,
        )


def test_candidate_brief_appends_research() -> None:
    dossier = DdResearchDossier(
        leftover=["Inget moderbolag på kandidaten"],
        job_id="job_1",
    )
    text = _candidate_brief(_candidate(), research=dossier)
    assert "Mål AB" in text
    assert "Researchdossier" in text
    assert "Inget moderbolag" in text


@pytest.mark.asyncio
async def test_research_job_writes_group_then_people(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def lookup_row(orgnr: str) -> dict[str, object]:
        return _allabolag_row(
            "Nordic Tech Solutions AB",
            orgnr,
            officers=[("Eva Ägare", "Ordförande")],
        )

    async def search_rows(query: str) -> list[dict[str, object]]:
        if "Eva" in query:
            return [{"name": "Eva Holding AB", "orgnr": "556000-0099"}]
        return []

    async def lookup_person(name: str) -> list[dict[str, object]]:
        if name == "Eva Ägare":
            return [{"name": "Eva Holding AB", "orgnr": "556000-0099"}]
        return []

    monkeypatch.setattr("app.services.dd.research.lookup_company_row", lookup_row)
    monkeypatch.setattr("app.services.dd.research.search_company_rows", search_rows)
    monkeypatch.setattr("app.services.dd.research.lookup_corporate_structure", _empty_group)
    monkeypatch.setattr("app.services.dd.research.lookup_person_companies", lookup_person)
    monkeypatch.setattr(
        "app.services.dd.research.search_duckduckgo",
        lambda query, number_of_result_pages=3: [
            {"title": "Träff", "url": "https://example.test"}
        ],
    )

    create = await client.post("/dd/campaigns", json={"title": "Research MVP"})
    assert create.status_code == 201
    campaign_id = create.json()["id"]
    sourced = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    assert sourced.status_code == 200
    candidate = sourced.json()["candidates"][0]
    candidate["styrelse"] = [
        {"namn": "Eva Ägare", "roll": "Ordförande", "grupp": "Styrelse"}
    ]
    patched = await client.patch(
        f"/dd/campaigns/{campaign_id}",
        json={"candidates": [candidate]},
    )
    assert patched.status_code == 200

    async def _run_next() -> None:
        done = asyncio.Event()

        def _schedule(job_id: str) -> None:
            async def _run() -> None:
                await jobs_service._run_job(job_id)
                done.set()

            asyncio.create_task(_run())

        jobs_service.set_schedule_hook(_schedule)
        return done

    done = await _run_next()
    started = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate['id']}/research",
        json={},
    )
    assert started.status_code == 202, started.text
    await asyncio.wait_for(done.wait(), timeout=10)

    campaign = await client.get(f"/dd/campaigns/{campaign_id}")
    people = campaign.json()["candidate_runs"][0]["research"]["people"]
    assert people
    assert people[0]["web_hits"] == []

    done = await _run_next()
    people_job = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate['id']}/research",
        json={"mode": "people", "person_names": ["Eva Ägare"]},
    )
    assert people_job.status_code == 202, people_job.text
    await asyncio.wait_for(done.wait(), timeout=10)
    jobs_service.set_schedule_hook(None)

    job = await client.get(f"/jobs/{people_job.json()['id']}")
    assert job.json()["status"] == "succeeded"
    assert job.json()["result"]["mode"] == "people"

    campaign = await client.get(f"/dd/campaigns/{campaign_id}")
    eva = campaign.json()["candidate_runs"][0]["research"]["people"][0]
    assert eva["bolag"]
    assert eva["web_hits"]


@pytest.mark.asyncio
async def test_people_research_requires_group(client: AsyncClient) -> None:
    create = await client.post("/dd/campaigns", json={"title": "No group"})
    campaign_id = create.json()["id"]
    sourced = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    candidate_id = sourced.json()["candidates"][0]["id"]
    resp = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/research",
        json={"mode": "people"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_group_research_caps_then_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(research_mod, "MAX_COMPANIES", 2)
    monkeypatch.setattr(research_mod, "MAX_GROUP_LOOKUPS", 2)

    async def lookup_row(orgnr: str) -> dict[str, object]:
        if "0001" in orgnr:
            return _allabolag_row(
                "Mål AB",
                "556000-0001",
                parent=("Moder AB", "556000-0002"),
                officers=[("Eva Ägare", "Ordförande")],
                companies=6,
            )
        if "0002" in orgnr:
            return _allabolag_row(
                "Moder AB",
                "556000-0002",
                officers=[("Eva Ägare", "Ordförande")],
                companies=6,
            )
        if "0004" in orgnr:
            return _allabolag_row(
                "Mål AB",
                "556000-0004",
                parent=("Mål AB", "556000-0001"),
                officers=[("Bo Ledamot", "Ledamot")],
            )
        raise AllabolagNotFoundError(orgnr)

    async def search_rows(query: str) -> list[dict[str, object]]:
        if query == "Mål AB":
            return [
                {"name": "Mål AB", "orgnr": "556000-0001"},
                {"name": "Mål AB", "orgnr": "556000-0004"},
            ]
        if query == "Moder AB":
            return [{"name": "Moder AB", "orgnr": "556000-0002"}]
        return []

    first = await run_dd_research(
        _candidate(),
        mode="group",
        lookup_row=lookup_row,
        search_rows=search_rows,
    )
    assert len(first.companies) == 2
    assert first.pending
    assert any("Kvar att kartlägga:" in item for item in first.leftover)

    second = await run_dd_research(
        _candidate(),
        mode="group",
        continue_group=True,
        existing=first,
        lookup_row=lookup_row,
        search_rows=search_rows,
    )
    by_orgnr = {row.orgnr: row for row in second.companies}
    assert len(second.companies) == 3
    assert by_orgnr["556000-0004"].relation == "dotterbolag"
    assert by_orgnr["556000-0004"].parent_orgnr == "556000-0001"
    assert second.pending == []
    assert {person.namn for person in second.people} == {"Eva Ägare", "Bo Ledamot"}


@pytest.mark.asyncio
async def test_continue_group_requires_pending(client: AsyncClient) -> None:
    create = await client.post("/dd/campaigns", json={"title": "No pending"})
    campaign_id = create.json()["id"]
    sourced = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    candidate_id = sourced.json()["candidates"][0]["id"]
    resp = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/research",
        json={"continue_group": True},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_group_remap_requires_clear(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def lookup_row(orgnr: str) -> dict[str, object]:
        return _allabolag_row("Mål AB", "556000-0001", officers=[("Eva Ägare", "Ordförande")])

    async def search_rows(_query: str) -> list[dict[str, object]]:
        return []

    async def _empty_group(_orgnr: str) -> list[object]:
        return []

    monkeypatch.setattr("app.services.dd.research.lookup_company_row", lookup_row)
    monkeypatch.setattr("app.services.dd.research.search_company_rows", search_rows)
    monkeypatch.setattr("app.services.dd.research.lookup_corporate_structure", _empty_group)

    create = await client.post("/dd/campaigns", json={"title": "Clear gate"})
    campaign_id = create.json()["id"]
    sourced = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    candidate_id = sourced.json()["candidates"][0]["id"]

    done = asyncio.Event()

    def _schedule(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule)
    started = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/research",
        json={},
    )
    assert started.status_code == 202, started.text
    await asyncio.wait_for(done.wait(), timeout=10)

    remap = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/research",
        json={},
    )
    assert remap.status_code == 400
    assert "Rensa" in remap.json()["detail"]

    cleared = await client.delete(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/research",
    )
    assert cleared.status_code == 204

    campaign = await client.get(f"/dd/campaigns/{campaign_id}")
    assert campaign.json()["candidate_runs"][0]["research"] is None

    done = asyncio.Event()
    started = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/research",
        json={},
    )
    assert started.status_code == 202, started.text
    await asyncio.wait_for(done.wait(), timeout=10)
    jobs_service.set_schedule_hook(None)

    campaign = await client.get(f"/dd/campaigns/{campaign_id}")
    assert campaign.json()["candidate_runs"][0]["research"]["companies"]


@pytest.mark.asyncio
async def test_people_reinvestigate_requires_clear(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def lookup_row(orgnr: str) -> dict[str, object]:
        return _allabolag_row("Mål AB", "556000-0001", officers=[("Eva Ägare", "Ordförande")])

    async def search_rows(_query: str) -> list[dict[str, object]]:
        return []

    async def lookup_person(name: str) -> list[dict[str, object]]:
        if name == "Eva Ägare":
            return [{"name": "Eva Holding AB", "orgnr": "556000-0099"}]
        return []

    monkeypatch.setattr("app.services.dd.research.lookup_company_row", lookup_row)
    monkeypatch.setattr("app.services.dd.research.search_company_rows", search_rows)
    monkeypatch.setattr("app.services.dd.research.lookup_corporate_structure", _empty_group)
    monkeypatch.setattr("app.services.dd.research.lookup_person_companies", lookup_person)
    monkeypatch.setattr(
        "app.services.dd.research.search_duckduckgo",
        lambda query, number_of_result_pages=3: [
            {"title": "Eva", "url": "https://www.linkedin.com/in/eva"}
        ],
    )

    create = await client.post("/dd/campaigns", json={"title": "People clear"})
    campaign_id = create.json()["id"]
    sourced = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    candidate = sourced.json()["candidates"][0]
    candidate["styrelse"] = [
        {"namn": "Eva Ägare", "roll": "Ordförande", "grupp": "Styrelse"}
    ]
    await client.patch(f"/dd/campaigns/{campaign_id}", json={"candidates": [candidate]})
    candidate_id = candidate["id"]

    async def _run_next() -> asyncio.Event:
        done = asyncio.Event()

        def _schedule(job_id: str) -> None:
            async def _run() -> None:
                await jobs_service._run_job(job_id)
                done.set()

            asyncio.create_task(_run())

        jobs_service.set_schedule_hook(_schedule)
        return done

    done = await _run_next()
    started = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/research",
        json={},
    )
    assert started.status_code == 202, started.text
    await asyncio.wait_for(done.wait(), timeout=10)

    done = await _run_next()
    people_job = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/research",
        json={"mode": "people", "person_names": ["Eva Ägare"]},
    )
    assert people_job.status_code == 202, people_job.text
    await asyncio.wait_for(done.wait(), timeout=10)
    jobs_service.set_schedule_hook(None)

    again = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/research",
        json={"mode": "people", "person_names": ["Eva Ägare"]},
    )
    assert again.status_code == 400
    assert "Rensa" in again.json()["detail"]
