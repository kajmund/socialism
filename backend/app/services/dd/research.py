"""Deterministic DD research — group map first, then optional person investigations."""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from app.services.dd.allabolag import (
    AllabolagNotFoundError,
    GroupCompany,
    candidate_from_allabolag,
    lookup_company_row,
    lookup_corporate_structure,
    lookup_person_companies,
    search_company_rows,
)
from app.services.dd.bolagsapi_mcp import format_orgnr
from app.services.dd.schemas import (
    DdCandidateCompany,
    DdResearchCompany,
    DdResearchDossier,
    DdResearchMode,
    DdResearchPending,
    DdResearchPerson,
    DdResearchPersonCompany,
    DdResearchPersonSeat,
    DdResearchRelation,
    DdResearchWebHit,
)
from app.services.oasis_agent_tools import search_duckduckgo

MAX_COMPANIES = 25
MAX_GROUP_SEARCHES = 25
MAX_GROUP_LOOKUPS = 25
MAX_PEOPLE_ROSTER = 40
MAX_INVESTIGATIONS = 8
MAX_PERSON_COMPANIES = 25
MAX_WEB_HITS = 1
THROTTLE_MIN_S = 0.5
THROTTLE_MAX_S = 1.0

_ORGNR_IN_TEXT = re.compile(r"(\d{6}-?\d{4}|\d{10}|\d{12})")
_LEGAL_SUFFIX = re.compile(
    r"\b(ab|hb|kb|ef|aktiebolag|handelsbolag|kommanditbolag)\b(?:\s*\(publ\))?",
    re.IGNORECASE,
)
_PEOPLE_LEFTOVER_PREFIXES = (
    "Webbsök:",
    "Inga bolag för person:",
    "Kap: hoppade person",
    "Fler uppdrag:",
)
_GROUP_LEFTOVER_REFRESH = (
    "Kvar att kartlägga:",
    "Allabolag anger ",
    "Allabolag listar ",
    "Allabolag hade ingen koncern",
    "Merinfo listar ",
)

SearchRows = Callable[[str], Awaitable[list[dict[str, Any]]]]
LookupRow = Callable[[str], Awaitable[dict[str, Any]]]
LookupPerson = Callable[[str], Awaitable[list[dict[str, Any]]]]
WebSearch = Callable[[str, int], list[dict[str, Any]]]
FetchGroup = Callable[[str], Awaitable[list[GroupCompany]]]

SOCIAL_NETWORKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("LinkedIn", ("linkedin.com",)),
    ("Facebook", ("facebook.com", "fb.com")),
    ("Instagram", ("instagram.com",)),
    ("X", ("x.com", "twitter.com")),
    ("TikTok", ("tiktok.com",)),
)


class DdResearchError(RuntimeError):
    """Research cannot start — missing group dossier or bad mode."""


def extract_orgnr(text: str) -> str:
    match = _ORGNR_IN_TEXT.search(text or "")
    if not match:
        return ""
    formatted = format_orgnr(match.group(1))
    digits = re.sub(r"\D", "", formatted)
    if len(digits) != 10:
        return ""
    return formatted


def _norm_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def _format_sek(sek: int | None) -> str | None:
    if sek is None:
        return None
    return f"{sek:,} SEK".replace(",", " ")


def _name_slot(
    namn: str,
    relation: DdResearchRelation,
    *,
    orgnr: str = "",
    parent_orgnr: str = "",
) -> DdResearchCompany:
    return DdResearchCompany(
        namn=namn,
        orgnr=orgnr,
        parent_orgnr=parent_orgnr,
        relation=relation,
    )


def _company_slot(
    candidate: DdCandidateCompany,
    relation: DdResearchRelation,
    *,
    parent_orgnr: str = "",
) -> DdResearchCompany:
    figures: list[str] = []
    oms = _format_sek(candidate.omsattning_sek)
    if oms is not None:
        figures.append(f"Omsättning: {oms}")
    if candidate.anstallda is not None:
        figures.append(f"Anställda: {candidate.anstallda}")
    for year in candidate.rakenskaper:
        resultat = _format_sek(year.resultat_sek)
        if resultat is not None:
            figures.append(f"Resultat {year.year}: {resultat}")
            break
    return DdResearchCompany(
        namn=candidate.namn,
        orgnr=candidate.organisationsnummer,
        parent_orgnr=parent_orgnr,
        relation=relation,
        nyckeltal=figures,
        styrelse=[
            f"{officer.namn} ({officer.roll})" if officer.roll else officer.namn
            for officer in candidate.styrelse
            if officer.namn.strip()
        ],
    )


def format_research_brief(dossier: DdResearchDossier) -> str:
    lines = ["## Researchdossier"]
    if dossier.companies:
        lines.append("")
        lines.append("### Bolag i koncernen")
        for company in dossier.companies:
            orgnr = f" ({company.orgnr})" if company.orgnr else ""
            lines.append(f"- {company.namn}{orgnr} — {company.relation}")
            if company.parent_orgnr:
                lines.append(f"  Ingår under: {company.parent_orgnr}")
            if company.nyckeltal:
                lines.append(f"  Nyckeltal: {'; '.join(company.nyckeltal)}")
            if company.styrelse:
                lines.append(f"  Styrelse: {'; '.join(company.styrelse)}")
    if dossier.pending:
        lines.append("")
        lines.append("### Kvar att kartlägga")
        for row in dossier.pending:
            label = f"{row.namn} ({row.orgnr})" if row.namn else row.orgnr
            lines.append(f"- {label}")
    if dossier.people:
        lines.append("")
        lines.append("### Personer")
        for person in dossier.people:
            roll = f" ({person.roll})" if person.roll else ""
            lines.append(f"- {person.namn}{roll}")
            if person.poster:
                seats = ", ".join(
                    f"{seat.namn} ({seat.roll})" if seat.roll else seat.namn
                    for seat in person.poster
                )
                lines.append(f"  I koncernen: {seats}")
            if person.bolag:
                others = ", ".join(
                    f"{row.namn} ({row.orgnr})" if row.orgnr else row.namn
                    for row in person.bolag
                )
                lines.append(f"  Uppdrag: {others}")
            found = [
                f"{hit.natverk}: {hit.title} ({hit.url})" if hit.title else f"{hit.natverk}: {hit.url}"
                for hit in person.web_hits
                if hit.url
            ]
            if found:
                lines.append(f"  Socialt: {'; '.join(found)}")
    if dossier.leftover:
        lines.append("")
        lines.append("### Inte hittat")
        for item in dossier.leftover:
            lines.append(f"- {item}")
    return "\n".join(lines)


async def _lookup_company(
    orgnr: str,
    label: str,
    leftover: list[str],
    lookup_row: LookupRow,
) -> DdCandidateCompany | None:
    try:
        raw = await lookup_row(orgnr)
    except AllabolagNotFoundError:
        leftover.append(f"Bolag saknas: {label}")
        return None
    return candidate_from_allabolag(raw)


def _collect_people(
    loaded: list[tuple[DdResearchRelation, DdCandidateCompany]],
    leftover: list[str],
) -> list[DdResearchPerson]:
    by_name: dict[str, DdResearchPerson] = {}
    for _relation, company in loaded:
        for officer in company.styrelse:
            name = officer.namn.strip()
            if not name:
                leftover.append("Styrelseledamot utan namn")
                continue
            key = _norm_name(name)
            seat = DdResearchPersonSeat(
                namn=company.namn,
                orgnr=company.organisationsnummer,
                roll=officer.roll,
            )
            existing = by_name.get(key)
            if existing is None:
                by_name[key] = DdResearchPerson(namn=name, roll=officer.roll, poster=[seat])
                continue
            if officer.roll and not existing.roll:
                existing.roll = officer.roll
            if not any(
                row.orgnr == seat.orgnr and row.roll == seat.roll for row in existing.poster
            ):
                existing.poster.append(seat)
    people = list(by_name.values())
    if len(people) > MAX_PEOPLE_ROSTER:
        for extra in people[MAX_PEOPLE_ROSTER:]:
            leftover.append(f"Kap: hoppade person {extra.namn}")
        people = people[:MAX_PEOPLE_ROSTER]
    if loaded and not people:
        leftover.append("Ingen styrelse i koncernbolagen")
    return people


def _keep_group_leftover(items: list[str]) -> list[str]:
    return [item for item in items if not item.startswith(_PEOPLE_LEFTOVER_PREFIXES)]


def _fresh_group_leftover(items: list[str]) -> list[str]:
    return [
        item
        for item in _keep_group_leftover(items)
        if not item.startswith(_GROUP_LEFTOVER_REFRESH)
    ]


def social_search_query(name: str, domains: tuple[str, ...]) -> str:
    quoted = f'"{name.strip()}"'
    sites = " OR ".join(f"site:{domain}" for domain in domains)
    if " OR " in sites:
        return f"{quoted} ({sites})"
    return f"{quoted} {sites}"


def _host_matches(url: str, domains: tuple[str, ...]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _is_empty_search_error(error: str) -> bool:
    text = error.strip().lower()
    if not text:
        return False
    if text.startswith("inga duckduckgo-träffar"):
        return True
    return "no results found" in text


def _social_search_miss(hits: list[dict[str, Any]]) -> bool:
    if not hits:
        return True
    return _is_empty_search_error(str(hits[0].get("error") or ""))


def _social_search_error(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return ""
    error = str(hits[0].get("error") or "")
    if error and not _is_empty_search_error(error):
        return error
    return ""


def _pick_social_hit(
    hits: list[dict[str, Any]],
    domains: tuple[str, ...],
) -> tuple[str, str]:
    for hit in hits:
        url = str(hit.get("url") or "").strip()
        if not url or not _host_matches(url, domains):
            continue
        title = str(hit.get("title") or "").strip()
        return title, url
    return "", ""


async def _search_social_profiles(
    name: str,
    web_fn: WebSearch,
    leftover: list[str],
    *,
    live: bool,
) -> list[DdResearchWebHit]:
    out: list[DdResearchWebHit] = []
    for network, domains in SOCIAL_NETWORKS:
        if live:
            await _allabolag_pause()
        raw = web_fn(social_search_query(name, domains), MAX_WEB_HITS)
        error = _social_search_error(raw)
        if error:
            leftover.append(f"Webbsök: {name}: {network}: {error}")
            out.append(DdResearchWebHit(natverk=network))
            continue
        if _social_search_miss(raw):
            out.append(DdResearchWebHit(natverk=network))
            continue
        title, url = _pick_social_hit(raw, domains)
        out.append(DdResearchWebHit(title=title, url=url, natverk=network))
    return out


async def _allabolag_pause() -> None:
    await asyncio.sleep(random.uniform(THROTTLE_MIN_S, THROTTLE_MAX_S))


def _merge_people(
    existing: list[DdResearchPerson],
    incoming: list[DdResearchPerson],
) -> list[DdResearchPerson]:
    by_name = {_norm_name(person.namn): person.model_copy() for person in existing}
    for person in incoming:
        key = _norm_name(person.namn)
        current = by_name.get(key)
        if current is None:
            by_name[key] = person.model_copy()
            continue
        if person.roll and not current.roll:
            current.roll = person.roll
        for seat in person.poster:
            if not any(row.orgnr == seat.orgnr and row.roll == seat.roll for row in current.poster):
                current.poster.append(seat)
    people = list(by_name.values())
    if len(people) > MAX_PEOPLE_ROSTER:
        people = people[:MAX_PEOPLE_ROSTER]
    return people


def _same_company_name(hit_name: str, query: str) -> bool:
    return _norm_name(hit_name) == _norm_name(query)


def _name_stems(name: str) -> list[str]:
    stripped = " ".join(_LEGAL_SUFFIX.sub(" ", name).split())
    stems: list[str] = []
    if stripped and _norm_name(stripped) != _norm_name(name):
        stems.append(stripped)
    first = stripped.split()[0] if stripped else ""
    if len(first) >= 3 and _norm_name(first) not in {_norm_name(name), _norm_name(stripped)}:
        stems.append(first)
    return stems


def _first_stem(name: str) -> str:
    stripped = " ".join(_LEGAL_SUFFIX.sub(" ", name).split())
    parts = stripped.split()
    return _norm_name(parts[0]) if parts else ""


def _shares_stem(hit_name: str, *names: str) -> bool:
    hit = _first_stem(hit_name)
    if len(hit) < 3:
        return False
    return any(_first_stem(name) == hit for name in names if name)


def _walk_root(orgnr: str, parents: dict[str, str], known: set[str]) -> str:
    seen: set[str] = set()
    current = orgnr
    while current and current not in seen:
        seen.add(current)
        parent = parents.get(current, "")
        if not parent or parent not in known:
            return current
        current = parent
    return orgnr


def _chains_to_root(orgnr: str, root_orgnr: str, parents: dict[str, str]) -> bool:
    seen: set[str] = set()
    current = orgnr
    while current and current not in seen:
        if current == root_orgnr:
            return True
        seen.add(current)
        current = parents.get(current, "")
    return False


def _relation_for(orgnr: str, seed_orgnr: str, root_orgnr: str) -> DdResearchRelation:
    if orgnr == seed_orgnr:
        return "kandidat"
    if orgnr == root_orgnr:
        return "moderbolag"
    return "dotterbolag"


async def run_dd_group_research(
    candidate: DdCandidateCompany,
    *,
    job_id: str = "",
    lookup_row: LookupRow | None = None,
    search_rows: SearchRows | None = None,
    fetch_group: FetchGroup | None = None,
    existing: DdResearchDossier | None = None,
    continue_group: bool = False,
) -> DdResearchDossier:
    live = lookup_row is None and search_rows is None
    lookup_fn = lookup_company_row if lookup_row is None else lookup_row
    search_fn = search_company_rows if search_rows is None else search_rows
    leftover: list[str] = []
    loaded: dict[str, DdCandidateCompany] = {}
    parents: dict[str, str] = {}
    pending: list[str] = []
    queued: set[str] = set()
    searched_names: set[str] = set()
    pending_names: dict[str, str] = {}
    newly_loaded: list[DdCandidateCompany] = []
    lookups = 0
    existing_slots: dict[str, DdResearchCompany] = {}
    nameless: list[DdResearchCompany] = []
    roster_miss: list[GroupCompany] = []

    def enqueue(orgnr: str, namn: str = "", *, front: bool = False) -> None:
        formatted = format_orgnr(orgnr) if orgnr else ""
        digits = re.sub(r"\D", "", formatted)
        if len(digits) != 10 or formatted in loaded or formatted in queued:
            if formatted in queued and namn and not pending_names.get(formatted):
                pending_names[formatted] = namn
            return
        queued.add(formatted)
        if front:
            pending.insert(0, formatted)
        else:
            pending.append(formatted)
        if namn:
            pending_names[formatted] = namn

    def known_group() -> set[str]:
        return set(existing_slots) | set(loaded)

    def should_keep(found_orgnr: str, parent_orgnr: str) -> bool:
        if found_orgnr == format_orgnr(candidate.organisationsnummer):
            return True
        if found_orgnr in existing_slots:
            return True
        if found_orgnr in roster_orgnrs:
            return True
        known = known_group()
        if parent_orgnr and parent_orgnr in known:
            return True
        if found_orgnr in {parents.get(orgnr, "") for orgnr in known}:
            return True
        return found_orgnr == extract_orgnr(candidate.moderbolag)

    roster_rows: list[GroupCompany] = []
    if continue_group:
        if existing is None:
            raise DdResearchError("Kör koncernkartan först")
        leftover = _fresh_group_leftover(existing.leftover)
        existing_slots = {
            format_orgnr(row.orgnr): row for row in existing.companies if row.orgnr
        }
        nameless = [row.model_copy() for row in existing.companies if not row.orgnr]
        for row in existing.companies:
            orgnr = format_orgnr(row.orgnr)
            if not orgnr:
                continue
            queued.add(orgnr)
            parents[orgnr] = format_orgnr(row.parent_orgnr) if row.parent_orgnr else ""
        for name in existing.searched_names:
            if name:
                searched_names.add(name)
        for row in existing.pending:
            enqueue(row.orgnr, row.namn)
        if not pending:
            raise DdResearchError("Inga fler bolag att kartlägga")
    else:
        enqueue(candidate.organisationsnummer, candidate.namn)
        seed_parent = extract_orgnr(candidate.moderbolag)
        if seed_parent:
            enqueue(seed_parent)
        if fetch_group is not None:
            roster_rows = await fetch_group(candidate.organisationsnummer)
        elif live:
            roster_rows = await lookup_corporate_structure(candidate.organisationsnummer)
        if not roster_rows and (fetch_group is not None or live):
            leftover.append(f"Allabolag hade ingen koncern för {candidate.organisationsnummer}")

    roster_orgnrs = {format_orgnr(row.orgnr) for row in roster_rows if row.orgnr}
    roster_parents = {
        format_orgnr(row.orgnr): format_orgnr(row.parent_orgnr)
        for row in roster_rows
        if row.orgnr
    }
    roster_names = {format_orgnr(row.orgnr): row.namn for row in roster_rows if row.orgnr}
    for row in roster_rows:
        if row.orgnr:
            enqueue(row.orgnr, row.namn)

    batch_start = len(existing_slots)

    while (
        pending
        and (len(loaded) + len(existing_slots) - batch_start) < MAX_COMPANIES
        and lookups < MAX_GROUP_LOOKUPS
    ):
        orgnr = pending.pop(0)
        queued.discard(orgnr)
        pending_names.pop(orgnr, None)
        lookups += 1
        if live:
            await _allabolag_pause()
        found = await _lookup_company(orgnr, orgnr, leftover, lookup_fn)
        if found is None:
            if orgnr in roster_names:
                if leftover and leftover[-1].startswith("Bolag saknas:"):
                    leftover.pop()
                roster_miss.append(
                    GroupCompany(
                        namn=roster_names[orgnr],
                        orgnr=orgnr,
                        parent_orgnr=roster_parents.get(orgnr, ""),
                    )
                )
            continue
        found_orgnr = format_orgnr(found.organisationsnummer)
        if found_orgnr == format_orgnr(candidate.organisationsnummer):
            found = found.model_copy(
                update={"id": candidate.id, "namn": candidate.namn or found.namn}
            )
        if found_orgnr in existing_slots:
            continue
        parent_orgnr = extract_orgnr(found.moderbolag)
        if found_orgnr in roster_parents:
            parent_orgnr = roster_parents[found_orgnr]
        if not should_keep(found_orgnr, parent_orgnr):
            continue
        loaded[found_orgnr] = found
        newly_loaded.append(found)
        parents[found_orgnr] = parent_orgnr
        if parent_orgnr:
            enqueue(parent_orgnr, front=True)
        queries = [found.namn, *_name_stems(found.namn)]
        for query in queries:
            name_key = _norm_name(query)
            if (
                not name_key
                or name_key in searched_names
                or len(searched_names) >= MAX_GROUP_SEARCHES
            ):
                continue
            searched_names.add(name_key)
            if live:
                await _allabolag_pause()
            known_names = (
                [found.namn]
                + [row.namn for row in loaded.values()]
                + [row.namn for row in existing_slots.values()]
            )
            for row in await search_fn(query):
                hit_name = str(row.get("name") or row.get("legalName") or "").strip()
                hit_orgnr = str(row.get("orgnr") or "")
                same = _same_company_name(hit_name, found.namn)
                if not same and not _shares_stem(hit_name, query, *known_names):
                    continue
                enqueue(hit_orgnr, hit_name, front=same)

    seed_orgnr = format_orgnr(candidate.organisationsnummer)
    if not continue_group and seed_orgnr and seed_orgnr not in loaded:
        parents[seed_orgnr] = roster_parents.get(
            seed_orgnr, extract_orgnr(candidate.moderbolag)
        )
        loaded[seed_orgnr] = candidate
        newly_loaded.append(candidate)

    for row in roster_miss:
        parents.setdefault(row.orgnr, row.parent_orgnr)
    if roster_rows:
        for row in roster_rows:
            if not row.orgnr:
                nameless.append(
                    _name_slot(row.namn, "dotterbolag", parent_orgnr=row.parent_orgnr)
                )

    known = set(existing_slots) | set(loaded) | {row.orgnr for row in roster_miss}
    root_orgnr = _walk_root(seed_orgnr, parents, known) if seed_orgnr else ""
    kept_new = [
        company
        for orgnr, company in loaded.items()
        if orgnr == seed_orgnr or _chains_to_root(orgnr, root_orgnr, parents)
    ]
    skipped = len(loaded) - len(kept_new)
    if skipped:
        leftover.append(f"Hoppade {skipped} bolag utanför kandidatens koncern")

    new_slots = [
        _company_slot(
            company,
            _relation_for(format_orgnr(company.organisationsnummer), seed_orgnr, root_orgnr),
            parent_orgnr=parents.get(format_orgnr(company.organisationsnummer), ""),
        )
        for company in kept_new
    ]
    for row in roster_miss:
        if row.orgnr != seed_orgnr and not _chains_to_root(row.orgnr, root_orgnr, parents):
            continue
        new_slots.append(
            _name_slot(
                row.namn,
                _relation_for(row.orgnr, seed_orgnr, root_orgnr),
                orgnr=row.orgnr,
                parent_orgnr=parents.get(row.orgnr, ""),
            )
        )
    companies = list(existing_slots.values())
    seen = set(existing_slots)
    for slot in new_slots:
        key = format_orgnr(slot.orgnr)
        if key in seen:
            continue
        seen.add(key)
        companies.append(slot)
    seen_names = {_norm_name(row.namn) for row in companies if not row.orgnr}
    for slot in nameless:
        key = _norm_name(slot.namn)
        if key in seen_names:
            continue
        seen_names.add(key)
        companies.append(slot)
    companies.sort(key=lambda row: (row.relation != "moderbolag", row.relation != "kandidat", row.namn))

    group_size = existing.group_size if existing is not None else None
    if roster_rows:
        group_size = len(roster_rows)
    else:
        expected = next((row.koncern_bolag for row in kept_new if row.koncern_bolag), None)
        if expected:
            group_size = expected
    if group_size and group_size > len(companies):
        leftover.append(f"Allabolag listar {group_size} bolag i koncernen, kartlade {len(companies)}")
    if (
        not continue_group
        and seed_orgnr
        and seed_orgnr in loaded
        and not extract_orgnr(loaded[seed_orgnr].moderbolag)
        and len(companies) == 1
    ):
        leftover.append("Inget moderbolag på kandidaten")

    pending_rows = [
        DdResearchPending(orgnr=orgnr, namn=pending_names.get(orgnr, ""))
        for orgnr in pending
    ]
    if pending_rows:
        leftover.append(f"Kvar att kartlägga: {len(pending_rows)} bolag")

    new_people = _collect_people(
        [
            (
                _relation_for(format_orgnr(company.organisationsnummer), seed_orgnr, root_orgnr),
                company,
            )
            for company in kept_new
        ],
        leftover,
    )
    people = (
        _merge_people(existing.people, new_people)
        if continue_group and existing is not None
        else new_people
    )
    return DdResearchDossier(
        companies=companies,
        people=people,
        leftover=leftover,
        pending=pending_rows,
        searched_names=sorted(searched_names),
        group_size=group_size,
        job_id=job_id,
    )


async def run_dd_people_research(
    dossier: DdResearchDossier,
    person_names: list[str],
    *,
    job_id: str = "",
    lookup_person: LookupPerson | None = None,
    web_search: WebSearch | None = None,
) -> DdResearchDossier:
    lookup_fn = lookup_person_companies if lookup_person is None else lookup_person
    web_fn = search_duckduckgo if web_search is None else web_search
    live = lookup_person is None
    leftover = _keep_group_leftover(dossier.leftover)
    by_name = {_norm_name(person.namn): person for person in dossier.people}
    if not by_name:
        leftover.append("Ingen personlista — kartlägg koncernen först")
        return dossier.model_copy(update={"leftover": leftover, "job_id": job_id})

    selected: list[DdResearchPerson]
    if person_names:
        selected = []
        for raw_name in person_names:
            person = by_name.get(_norm_name(raw_name))
            if person is None:
                leftover.append(f"Personen finns inte i koncernlistan: {raw_name}")
                continue
            selected.append(person)
    else:
        selected = list(dossier.people)

    skipped = selected[MAX_INVESTIGATIONS:]
    selected = selected[:MAX_INVESTIGATIONS]
    for extra in skipped:
        leftover.append(f"Kap: hoppade person {extra.namn}")

    updated = {key: person.model_copy() for key, person in by_name.items()}
    for person in selected:
        name = person.namn.strip()
        if live:
            await _allabolag_pause()
        rows = await lookup_fn(name)
        others: list[DdResearchPersonCompany] = []
        if not rows:
            leftover.append(f"Inga bolag för person: {name}")
        for row in rows:
            orgnr = format_orgnr(str(row.get("orgnr") or ""))
            digits = re.sub(r"\D", "", orgnr)
            if len(digits) != 10:
                continue
            namn = str(row.get("name") or row.get("legalName") or orgnr).strip()
            others.append(DdResearchPersonCompany(namn=namn, orgnr=orgnr))
        if len(others) > MAX_PERSON_COMPANIES:
            leftover.append(
                f"Fler uppdrag: {name} har {len(others)} bolag, tog {MAX_PERSON_COMPANIES}"
            )
            others = others[:MAX_PERSON_COMPANIES]
        web_hits = await _search_social_profiles(name, web_fn, leftover, live=live)
        current = updated[_norm_name(name)]
        updated[_norm_name(name)] = current.model_copy(
            update={"bolag": others, "web_hits": web_hits}
        )

    people = [updated[_norm_name(person.namn)] for person in dossier.people]
    return dossier.model_copy(update={"people": people, "leftover": leftover, "job_id": job_id})


async def run_dd_research(
    candidate: DdCandidateCompany,
    *,
    mode: DdResearchMode = "group",
    person_names: list[str] | None = None,
    existing: DdResearchDossier | None = None,
    continue_group: bool = False,
    job_id: str = "",
    search_rows: SearchRows | None = None,
    lookup_row: LookupRow | None = None,
    web_search: WebSearch | None = None,
    fetch_group: FetchGroup | None = None,
    lookup_person: LookupPerson | None = None,
) -> DdResearchDossier:
    if mode == "group":
        return await run_dd_group_research(
            candidate,
            job_id=job_id,
            lookup_row=lookup_row,
            search_rows=search_rows,
            fetch_group=fetch_group,
            existing=existing,
            continue_group=continue_group,
        )
    if mode == "people":
        if existing is None:
            raise DdResearchError("Kör koncernkartan först")
        return await run_dd_people_research(
            existing,
            person_names or [],
            job_id=job_id,
            lookup_person=lookup_person,
            web_search=web_search,
        )
    raise DdResearchError(f"Unsupported research mode: {mode}")


__all__ = [
    "MAX_COMPANIES",
    "MAX_INVESTIGATIONS",
    "MAX_PEOPLE_ROSTER",
    "DdResearchError",
    "extract_orgnr",
    "format_research_brief",
    "run_dd_research",
]
