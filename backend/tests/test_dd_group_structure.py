"""Allabolag corporate-structure tree and group-research integration."""

from __future__ import annotations

import pytest

from app.services.dd.allabolag import (
    AllabolagError,
    AllabolagNotFoundError,
    GroupCompany,
    companies_from_corporate_structure,
)
from app.services.dd.research import run_dd_research
from tests.test_dd_research import _allabolag_row, _candidate


def test_companies_from_corporate_structure_flattens_tree() -> None:
    rows = companies_from_corporate_structure(
        {
            "tree": {
                "name": "Akind Universe AB",
                "organisationNumber": "5569448805",
                "countryCode": "SE",
                "sub": [
                    {
                        "name": "Academic Work Group AB",
                        "organisationNumber": "5568584188",
                        "countryCode": "SE",
                        "sub": [
                            {
                                "name": "ACADEMIC WORK NORWAY AS",
                                "organisationNumber": None,
                                "countryCode": "NO",
                                "sub": [],
                            }
                        ],
                    },
                    {
                        "name": "Crowd Collective Linköping AB",
                        "organisationNumber": "5593342586",
                        "countryCode": "SE",
                        "sub": [],
                    },
                ],
            }
        }
    )
    by_name = {row.namn: row for row in rows}
    assert by_name["Akind Universe AB"].orgnr == "556944-8805"
    assert by_name["Akind Universe AB"].parent_orgnr == ""
    assert by_name["Academic Work Group AB"].parent_orgnr == "556944-8805"
    assert by_name["ACADEMIC WORK NORWAY AS"].orgnr == ""
    assert by_name["ACADEMIC WORK NORWAY AS"].parent_orgnr == "556858-4188"
    assert by_name["Crowd Collective Linköping AB"].parent_orgnr == "556944-8805"


@pytest.mark.asyncio
async def test_research_keeps_group_siblings_outside_name_search() -> None:
    async def lookup_row(orgnr: str) -> dict[str, object]:
        if "0001" in orgnr:
            return _allabolag_row(
                "Mål AB",
                "556000-0001",
                parent=("Moder AB", "556000-0002"),
            )
        if "0002" in orgnr:
            return _allabolag_row("Moder AB", "556000-0002", companies=4)
        if "0008" in orgnr:
            return _allabolag_row(
                "Academic Work Group AB",
                "556000-0008",
                parent=("Moder AB", "556000-0002"),
            )
        raise AllabolagNotFoundError(orgnr)

    async def search_rows(query: str) -> list[dict[str, object]]:
        if query in {"Mål AB", "Mål"}:
            return [{"name": "Mål AB", "orgnr": "556000-0001"}]
        if query in {"Moder AB", "Moder"}:
            return [{"name": "Moder AB", "orgnr": "556000-0002"}]
        return []

    async def fetch_group(_orgnr: str) -> list[GroupCompany]:
        return [
            GroupCompany("Moder AB", "556000-0002", ""),
            GroupCompany("Mål AB", "556000-0001", "556000-0002"),
            GroupCompany("Academic Work Group AB", "556000-0008", "556000-0002"),
            GroupCompany("Academic Work Norway A/S", "", "556000-0008"),
        ]

    dossier = await run_dd_research(
        _candidate(),
        mode="group",
        lookup_row=lookup_row,
        search_rows=search_rows,
        fetch_group=fetch_group,
    )
    by_name = {row.namn: row for row in dossier.companies}
    assert by_name["Academic Work Group AB"].relation == "dotterbolag"
    assert by_name["Academic Work Group AB"].parent_orgnr == "556000-0002"
    assert by_name["Academic Work Norway A/S"].orgnr == ""
    assert by_name["Academic Work Norway A/S"].parent_orgnr == "556000-0008"
    assert dossier.group_size == 4


@pytest.mark.asyncio
async def test_research_keeps_roster_name_when_lookup_misses() -> None:
    async def lookup_row(orgnr: str) -> dict[str, object]:
        if "0001" in orgnr:
            return _allabolag_row("Mål AB", "556000-0001", parent=("Moder AB", "556000-0002"))
        if "0002" in orgnr:
            return _allabolag_row("Moder AB", "556000-0002")
        raise AllabolagNotFoundError(orgnr)

    async def search_rows(_query: str) -> list[dict[str, object]]:
        return []

    async def fetch_group(_orgnr: str) -> list[GroupCompany]:
        return [
            GroupCompany("Moder AB", "556000-0002", ""),
            GroupCompany("Mål AB", "556000-0001", "556000-0002"),
            GroupCompany("Academic Work Group AB", "556000-0008", "556000-0002"),
        ]

    dossier = await run_dd_research(
        _candidate(),
        mode="group",
        lookup_row=lookup_row,
        search_rows=search_rows,
        fetch_group=fetch_group,
    )
    academic = next(row for row in dossier.companies if row.namn == "Academic Work Group AB")
    assert academic.orgnr == "556000-0008"
    assert academic.parent_orgnr == "556000-0002"
    assert all("Bolag saknas" not in item for item in dossier.leftover)


@pytest.mark.asyncio
async def test_research_fails_loud_on_structure_error() -> None:
    async def lookup_row(orgnr: str) -> dict[str, object]:
        return _allabolag_row("Mål AB", orgnr)

    async def search_rows(_query: str) -> list[dict[str, object]]:
        return []

    async def fetch_group(_orgnr: str) -> list[GroupCompany]:
        raise AllabolagError("Allabolag HTTP 403")

    with pytest.raises(AllabolagError, match="403"):
        await run_dd_research(
            _candidate(),
            mode="group",
            lookup_row=lookup_row,
            search_rows=search_rows,
            fetch_group=fetch_group,
        )
