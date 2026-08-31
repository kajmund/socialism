"""Allabolag.se company lookup via embedded Next.js page data.

Amounts on Allabolag cards are in tkr (thousands of SEK).
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.services.dd.bolagsapi_cache import get_cached, put_cached
from app.services.dd.bolagsapi_mcp import format_orgnr
from app.services.dd.schemas import (
    DdAccountFigure,
    DdAccountYear,
    DdCandidateCompany,
    DdOfficer,
    DdResultatFilter,
)

# Sweden Proff/Allabolag codes. "sek" amounts on the page are tkr.
_ACCOUNT_META: dict[str, tuple[str, str]] = {
    "ADI": ("Övriga rörelseintäkter", "sek"),
    "ADK": ("Övriga finansiella kostnader", "sek"),
    "ADR": ("Övrig omsättning", "sek"),
    "AK": ("Aktiekapital", "sek"),
    "ANT": ("Anställda", "antal"),
    "avk_eget_kapital": ("Avkastning eget kapital %", "pct"),
    "avk_totalt_kapital": ("Avkastning totalt kapital %", "pct"),
    "AWA": ("Aktiverat arbete för egen räkning", "sek"),
    "BE": ("Lagerförändring", "sek"),
    "CPE": ("Personalkostnader per anställd", "sek"),
    "DR": ("Årets resultat", "sek"),
    "EBITDA": ("EBITDA", "sek"),
    "EK": ("Avskrivningar och nedskrivningar", "sek"),
    "EKA": ("Soliditet %", "pct"),
    "FI": ("Finansiella intäkter", "sek"),
    "FK": ("Finansiella kostnader", "sek"),
    "FSD": ("Bokslutsdispositioner", "sek"),
    "GG": ("Skuldsättningsgrad", "tal"),
    "IAC": ("Jämförelsestörande poster", "sek"),
    "KB": ("Koncernbidrag", "sek"),
    "KBP": ("Kassa och bank", "sek"),
    "LG": ("Leverantörsskulder", "sek"),
    "loner_ovriga": ("Löner övriga", "sek"),
    "loner_styrelse_vd": ("Löner styrelse och VD", "sek"),
    "MIN": ("Minoritetsintressen", "sek"),
    "ORS": ("Resultat före skatt", "sek"),
    "resultat_e_avskrivningar": ("Rörelseresultat efter avskrivningar", "sek"),
    "resultat_e_finansnetto": ("Resultat efter finansnetto", "sek"),
    "RG": ("Kassalikviditet %", "pct"),
    "RPE": ("Omsättning per anställd", "sek"),
    "SAP": ("Avsättningar", "sek"),
    "SDI": ("Omsättning", "sek"),
    "SED": ("Summa tillgångar", "sek"),
    "SEK": ("Eget kapital", "sek"),
    "SF": ("Kundfordringar", "sek"),
    "SFA": ("Anläggningstillgångar", "sek"),
    "SGE": ("Summa eget kapital och skulder", "sek"),
    "SI": ("Nettoomsättning", "sek"),
    "SIA": ("Immateriella anläggningstillgångar", "sek"),
    "SIK": ("Fritt eget kapital", "sek"),
    "SKG": ("Kortfristiga skulder", "sek"),
    "SKGKI": ("Kortfristiga skulder till kreditinstitut", "sek"),
    "SKO": ("Skatt på årets resultat", "sek"),
    "SLG": ("Långfristiga skulder till kreditinstitut", "sek"),
    "SOM": ("Omsättningstillgångar", "sek"),
    "SUB": ("Föreslagen utdelning", "sek"),
    "summa_finansiella_anltillg": ("Finansiella anläggningstillgångar", "sek"),
    "summa_langfristiga_skulder": ("Långfristiga skulder", "sek"),
    "summa_rorelsekostnader": ("Rörelsekostnader", "sek"),
    "SV": ("Varulager", "sek"),
    "SVD": ("Materiella anläggningstillgångar", "sek"),
    "TR": ("Vinstmarginal %", "pct"),
    "UTR": ("Obeskattade reserver", "sek"),
}

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
_SEARCH_PATH = "https://www.allabolag.se/bransch-s%C3%B6k"
_COMPANY_PATH = "https://www.allabolag.se/foretag/{name}/{location}/{industry}/{company_id}"
_PERSON_SEARCH_PATH = "https://www.allabolag.se/befattningshavare"
_PERSON_PATH = "https://www.allabolag.se/befattning/{name}/-/{person_id}"
_STRUCTURE_PATH = "https://www.allabolag.se/api/company/legal/{orgnr}/corporateStructure"
_THROTTLE_MIN_S = 0.5
_THROTTLE_MAX_S = 1.0


class AllabolagError(RuntimeError):
    pass


class AllabolagNotFoundError(AllabolagError):
    pass


@dataclass(frozen=True)
class GroupCompany:
    namn: str
    orgnr: str
    parent_orgnr: str


def _slug(value: str) -> str:
    text = value.strip().casefold()
    for src, dst in (("å", "a"), ("ä", "a"), ("ö", "o"), ("é", "e")):
        text = text.replace(src, dst)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "-"


def _norm_person_name(name: str) -> str:
    return " ".join(name.split()).casefold()


async def _pause() -> None:
    await asyncio.sleep(random.uniform(_THROTTLE_MIN_S, _THROTTLE_MAX_S))


def extract_next_data(html: str) -> dict[str, Any]:
    match = _NEXT_DATA.search(html)
    if not match:
        raise AllabolagError("Allabolag page had no __NEXT_DATA__")
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise AllabolagError("Allabolag __NEXT_DATA__ was not JSON") from exc
    if not isinstance(parsed, dict):
        raise AllabolagError("Allabolag __NEXT_DATA__ was not an object")
    return parsed


def _tkr_to_sek(raw: object) -> int | None:
    if raw is None or raw == "":
        return None
    digits = re.sub(r"[^\d\-]", "", str(raw))
    if not digits or digits == "-":
        return None
    return int(digits) * 1000


def _int_or_none(raw: object) -> int | None:
    if raw is None or raw == "":
        return None
    text = str(raw).strip()
    if re.fullmatch(r"\d+\s*-\s*\d+", text):
        return None
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    return int(digits)


def _resultat_from_profit(raw: object) -> DdResultatFilter:
    amount = _tkr_to_sek(raw)
    if amount is None:
        return "oavsett"
    if amount > 0:
        return "vinst"
    if amount < 0:
        return "förlust"
    return "oavsett"


def _age_from_date(raw: object, today: date | None = None) -> int:
    text = str(raw or "").strip()
    match = re.search(r"(\d{4})", text)
    if not match:
        return 0
    current = today or datetime.now(UTC).date()
    return max(0, current.year - int(match.group(1)))


def _omrade(row: dict[str, Any]) -> str:
    location = row.get("location") if isinstance(row.get("location"), dict) else {}
    address = row.get("visitorAddress") if isinstance(row.get("visitorAddress"), dict) else {}
    for value in (
        location.get("municipality"),
        location.get("county"),
        address.get("postPlace"),
    ):
        text = str(value or "").strip()
        if text:
            return text.title()
    return ""


def _industry_names(row: dict[str, Any]) -> list[str]:
    names: list[str] = []
    current = row.get("currentIndustry") if isinstance(row.get("currentIndustry"), dict) else {}
    current_name = str(current.get("name") or "").strip()
    if current_name:
        names.append(current_name)
    industries = row.get("industries")
    if isinstance(industries, list):
        for item in industries:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name and name not in names:
                names.append(name)
    nace = row.get("naceIndustries")
    if isinstance(nace, list):
        for item in nace:
            name = str(item or "").strip()
            if name and name not in names:
                names.append(name)
    return names


def _description(row: dict[str, Any]) -> str:
    purpose = str(row.get("purpose") or "").strip()
    if purpose:
        return purpose
    return ", ".join(_industry_names(row))


def search_companies_from_next_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    store = (
        data.get("props", {})
        .get("pageProps", {})
        .get("hydrationData", {})
        .get("searchStore", {})
        .get("companies", {})
    )
    rows = store.get("companies")
    if not isinstance(rows, list):
        raise AllabolagError("Allabolag search payload had no companies list")
    return [row for row in rows if isinstance(row, dict) and row.get("orgnr")]


def company_from_next_data(data: dict[str, Any]) -> dict[str, Any]:
    page = data.get("props", {}).get("pageProps", {})
    company = page.get("company")
    if not isinstance(company, dict) or not company.get("orgnr"):
        raise AllabolagError("Allabolag company page had no company object")
    trademarks = page.get("trademarks")
    marks: list[Any] = []
    if isinstance(trademarks, dict) and isinstance(trademarks.get("trademarks"), list):
        marks = trademarks["trademarks"]
    elif isinstance(trademarks, list):
        marks = trademarks
    return {**company, "trademarks": marks}


def company_page_path(row: dict[str, Any]) -> str:
    company_id = str(row.get("companyId") or "").strip()
    if not company_id:
        raise AllabolagError("Allabolag company is missing companyId")
    name = _slug(str(row.get("name") or row.get("legalName") or "foretag"))
    location = _slug(_omrade(row) or "sverige")
    industries = _industry_names(row)
    industry = _slug(industries[0] if industries else "-")
    return _COMPANY_PATH.format(
        name=quote(name, safe="-"),
        location=quote(location, safe="-"),
        industry=quote(industry, safe="-"),
        company_id=quote(company_id, safe=""),
    )


def _registry_flags(row: dict[str, Any]) -> tuple[bool | None, bool | None, bool | None]:
    flags: dict[str, bool] = {}
    entries = row.get("registryStatusEntries")
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict) or not item.get("label"):
                continue
            flags[str(item["label"])] = bool(item.get("value"))
    fskatt = flags.get("registeredForPrepayment")
    moms = flags.get("registeredForVat")
    payroll = flags.get("registeredForPayrollTax")
    if moms is None and isinstance(row.get("registeredForVat"), bool):
        moms = row["registeredForVat"]
    if payroll is None and isinstance(row.get("registeredForPayrollTax"), bool):
        payroll = row["registeredForPayrollTax"]
    return fskatt, moms, payroll


def _officers(row: dict[str, Any]) -> list[DdOfficer]:
    roles = row.get("roles") if isinstance(row.get("roles"), dict) else {}
    groups = roles.get("roleGroups")
    out: list[DdOfficer] = []
    seen: set[tuple[str, str, str]] = set()
    if not isinstance(groups, list):
        return out
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("name") or "").strip()
        members = group.get("roles")
        if not isinstance(members, list):
            continue
        for member in members:
            if not isinstance(member, dict):
                continue
            namn = str(member.get("name") or "").strip()
            roll = str(member.get("role") or "").strip()
            if not namn:
                continue
            key = (namn, roll, group_name)
            if key in seen:
                continue
            seen.add(key)
            out.append(DdOfficer(namn=namn, roll=roll, grupp=group_name))
    return out


def _signatories(row: dict[str, Any]) -> list[str]:
    raw = row.get("signatories")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _pct(raw: object) -> str | None:
    if raw in (None, ""):
        return None
    return str(raw).strip()


def _figure_from_amount(code: str, raw: object) -> DdAccountFigure | None:
    if raw in (None, ""):
        return None
    namn, kind = _ACCOUNT_META.get(code, (code, "tal"))
    if kind == "sek":
        sek = _tkr_to_sek(raw)
        if sek is None:
            return None
        return DdAccountFigure(kod=code, namn=namn, enhet="sek", sek=sek)
    if kind == "antal":
        count = _int_or_none(raw)
        if count is None:
            return None
        return DdAccountFigure(kod=code, namn=namn, enhet="antal", tal=str(count))
    text = _pct(raw)
    if text is None:
        return None
    return DdAccountFigure(kod=code, namn=namn, enhet="pct" if kind == "pct" else "tal", tal=text)


def _account_years(row: dict[str, Any]) -> list[DdAccountYear]:
    accounts = row.get("companyAccounts")
    if not isinstance(accounts, list):
        return []
    years: list[DdAccountYear] = []
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        year = str(acc.get("year") or acc.get("period") or "").strip()
        figures = acc.get("accounts")
        if not year or not isinstance(figures, list):
            continue
        poster: list[DdAccountFigure] = []
        by_code: dict[str, object] = {}
        for item in figures:
            if not isinstance(item, dict) or not item.get("code"):
                continue
            code = str(item.get("code"))
            by_code[code] = item.get("amount")
            parsed = _figure_from_amount(code, item.get("amount"))
            if parsed is not None:
                poster.append(parsed)
        years.append(
            DdAccountYear(
                year=year,
                omsattning_sek=_tkr_to_sek(by_code.get("SDI")),
                resultat_sek=_tkr_to_sek(by_code.get("DR")),
                ebitda_sek=_tkr_to_sek(by_code.get("EBITDA")),
                utdelning_sek=_tkr_to_sek(by_code.get("SUB")),
                anstallda=_int_or_none(by_code.get("ANT")),
                eget_kapital_sek=_tkr_to_sek(by_code.get("SEK")),
                soliditet_pct=_pct(by_code.get("EKA")),
                poster=poster,
            )
        )
    return years


def _string_list(raw: object, *keys: str) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if text:
                out.append(text)
            continue
        if not isinstance(item, dict):
            continue
        parts = [str(item.get(key) or "").strip() for key in keys]
        text = " — ".join(part for part in parts if part)
        if text:
            out.append(text)
    return out


def _events(row: dict[str, Any]) -> list[str]:
    return _string_list(row.get("announcements"), "date", "text")


def _sites(row: dict[str, Any]) -> list[str]:
    return _string_list(row.get("businessUnits"), "name")


def _phone(row: dict[str, Any]) -> str:
    for key in ("phone", "legalPhone", "mobile"):
        text = str(row.get(key) or "").strip()
        if text and text != "0700000000":
            return text
    return ""


def _trademark_titles(row: dict[str, Any]) -> list[str]:
    raw = row.get("trademarks")
    items: list[Any] = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict) and isinstance(raw.get("trademarks"), list):
        items = raw["trademarks"]
    titles: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        kind = str(item.get("type") or "").strip()
        titles.append(f"{title} ({kind})" if kind else title)
    return titles


def _group_parent(row: dict[str, Any]) -> tuple[int | None, int | None, str]:
    structure = row.get("corporateStructure")
    if not isinstance(structure, dict):
        return None, None, ""
    companies = structure.get("numberOfCompanies")
    subsidiaries = structure.get("numberOfSubsidiaries")
    parent = str(structure.get("parentCompanyName") or "").strip()
    orgnr = str(structure.get("parentCompanyOrganisationNumber") or "").strip()
    if orgnr:
        formatted = format_orgnr(orgnr)
        parent = f"{parent} ({formatted})" if parent else formatted
    return (
        companies if isinstance(companies, int) else _int_or_none(companies),
        subsidiaries if isinstance(subsidiaries, int) else _int_or_none(subsidiaries),
        parent,
    )


def candidate_from_allabolag(
    row: dict[str, Any],
    *,
    today: date | None = None,
) -> DdCandidateCompany:
    orgnr = format_orgnr(str(row.get("orgnr") or ""))
    fskatt, moms, payroll = _registry_flags(row)
    companies, subsidiaries, parent = _group_parent(row)
    return DdCandidateCompany(
        id=orgnr,
        namn=str(row.get("name") or row.get("legalName") or orgnr).strip(),
        organisationsnummer=orgnr,
        alder_ar=_age_from_date(row.get("registrationDate") or row.get("foundationYear"), today),
        omrade=_omrade(row),
        resultat=_resultat_from_profit(row.get("profit")),
        omsattning_sek=_tkr_to_sek(row.get("revenue")),
        anstallda=_int_or_none(row.get("employees") or row.get("numberOfEmployees")),
        beskrivning=_description(row),
        fskatt=fskatt,
        moms=moms,
        arbetsgivaravgift=payroll,
        styrelse=_officers(row),
        firmateckning=_signatories(row),
        koncern_bolag=companies,
        koncern_dotter=subsidiaries,
        moderbolag=parent,
        varumarken=_trademark_titles(row),
        rakenskaper=_account_years(row),
        sni=_string_list(row.get("naceIndustries")),
        handelser=_events(row),
        arbetsstallen=_sites(row),
        telefon=_phone(row),
        foretagshypotek=row.get("mortgages") if isinstance(row.get("mortgages"), bool) else None,
        betalningsanmarkning=(
            row.get("paymentRemarks") if isinstance(row.get("paymentRemarks"), bool) else None
        ),
        gasell=row.get("gaselle") if isinstance(row.get("gaselle"), bool) else None,
    )


def _format_sek(sek: int | None) -> str:
    if sek is None:
        return "—"
    return f"{sek:,} SEK".replace(",", " ")


def _bool_sv(value: bool | None) -> str:
    if value is None:
        return "—"
    return "Ja" if value else "Nej"


def _format_figure(figure: DdAccountFigure) -> str:
    if figure.enhet == "sek":
        return f"- {figure.namn}: {_format_sek(figure.sek)}"
    if figure.enhet == "antal":
        return f"- {figure.namn}: {figure.tal or '—'}"
    if figure.enhet == "pct":
        return f"- {figure.namn}: {figure.tal or '—'}"
    return f"- {figure.namn}: {figure.tal or '—'}"


def _account_lines(row: dict[str, Any]) -> list[str]:
    years = _account_years(row)
    if not years:
        return []
    lines = ["## Räkenskaper"]
    for year in years:
        lines.append(f"### {year.year}")
        lines.append(f"- Omsättning: {_format_sek(year.omsattning_sek)}")
        lines.append(f"- Årets resultat: {_format_sek(year.resultat_sek)}")
        lines.append(f"- Föreslagen utdelning: {_format_sek(year.utdelning_sek)}")
        if year.ebitda_sek is not None:
            lines.append(f"- EBITDA: {_format_sek(year.ebitda_sek)}")
        if year.anstallda is not None:
            lines.append(f"- Anställda: {year.anstallda}")
        if year.eget_kapital_sek is not None:
            lines.append(f"- Eget kapital: {_format_sek(year.eget_kapital_sek)}")
        if year.soliditet_pct:
            lines.append(f"- Soliditet %: {year.soliditet_pct}")
        extra = [
            fig
            for fig in year.poster
            if fig.kod not in {"SDI", "DR", "SUB", "EBITDA", "ANT", "SEK", "EKA"}
        ]
        if extra:
            lines.append("- Övriga poster:")
            lines.extend(f"  {_format_figure(fig)}" for fig in extra)
    return lines


def format_search_markdown(rows: list[dict[str, Any]], *, today: date | None = None) -> str:
    if not rows:
        return "No companies found matching your search criteria."
    blocks: list[str] = []
    for row in rows:
        candidate = candidate_from_allabolag(row, today=today)
        industry = ", ".join(_industry_names(row))
        rest_bits = [part for part in (industry, candidate.omrade.upper() if candidate.omrade else "") if part]
        rest = " ".join(rest_bits)
        city = f" ({candidate.omrade})" if candidate.omrade else ""
        line = f"- **{candidate.namn}** [{candidate.organisationsnummer.replace('-', '')}]"
        if rest:
            line += f" - {rest}{city}"
        blocks.append(line)
        blocks.append(format_lookup_markdown(row, today=today))
    return "\n\n".join(blocks)


def format_lookup_markdown(row: dict[str, Any], *, today: date | None = None) -> str:
    candidate = candidate_from_allabolag(row, today=today)
    address = row.get("visitorAddress") if isinstance(row.get("visitorAddress"), dict) else {}
    address_line = ", ".join(
        part
        for part in (
            str(address.get("addressLine") or "").strip(),
            str(address.get("zipCode") or "").strip(),
            str(address.get("postPlace") or candidate.omrade).strip(),
            "SE",
        )
        if part
    )
    registered = str(row.get("registrationDate") or row.get("foundationDate") or "").strip()
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    status_label = str(status.get("status") or status.get("statusCode") or "").strip()
    company_type = row.get("companyType") if isinstance(row.get("companyType"), dict) else {}
    chair = row.get("contactPerson") if isinstance(row.get("contactPerson"), dict) else {}
    lines = [
        f"# {candidate.namn}",
        "",
        f"**Organization Number:** {candidate.organisationsnummer}",
    ]
    if registered:
        iso = registered.replace(".", "-")
        if re.fullmatch(r"\d{2}-\d{2}-\d{4}", iso):
            day, month, year = iso.split("-")
            iso = f"{year}-{month}-{day}"
        lines.append(f"**Registered:** {iso}")
    if address_line:
        lines.append(f"**Address:** {address_line}")
    if candidate.omsattning_sek is not None:
        lines.append(f"**Omsättning:** {candidate.omsattning_sek} SEK")
    if candidate.anstallda is not None:
        lines.append(f"**Anställda:** {candidate.anstallda}")
    lines.append(f"**Resultat:** {candidate.resultat}")
    if status_label:
        lines.append(f"**Status:** {status_label}")
    type_name = str(company_type.get("name") or "").strip()
    if type_name:
        lines.append(f"**Bolagsform:** {type_name}")
    chair_name = str(chair.get("name") or "").strip()
    if chair_name:
        role = str(chair.get("role") or "").strip()
        lines.append(f"**Kontakt:** {chair_name}" + (f" ({role})" if role else ""))
    if candidate.beskrivning:
        lines.extend(["", "## Business Description", candidate.beskrivning])
    lines.extend(
        [
            "",
            "## Registrering",
            f"- F-skatt: {_bool_sv(candidate.fskatt)}",
            f"- Moms: {_bool_sv(candidate.moms)}",
            f"- Arbetsgivaravgift: {_bool_sv(candidate.arbetsgivaravgift)}",
        ]
    )
    if candidate.koncern_bolag is not None or candidate.koncern_dotter is not None or candidate.moderbolag:
        group_bits = []
        if candidate.koncern_bolag is not None:
            group_bits.append(f"{candidate.koncern_bolag} bolag")
        if candidate.koncern_dotter is not None:
            group_bits.append(f"{candidate.koncern_dotter} dotterbolag")
        lines.extend(["", "## Koncern"])
        if group_bits:
            lines.append("- " + ", ".join(group_bits))
        if candidate.moderbolag:
            lines.append(f"- Moderbolag: {candidate.moderbolag}")
    if candidate.styrelse:
        lines.extend(["", "## Styrelse och roller"])
        for officer in candidate.styrelse:
            label = f"{officer.roll}: {officer.namn}" if officer.roll else officer.namn
            if officer.grupp:
                label = f"{label} ({officer.grupp})"
            lines.append(f"- {label}")
    if candidate.firmateckning:
        lines.extend(["", "## Firmateckning"])
        for item in candidate.firmateckning:
            lines.append(f"- {item}")
    if candidate.varumarken:
        lines.extend(["", "## Varumärken"])
        for mark in candidate.varumarken:
            lines.append(f"- {mark}")
    if candidate.sni:
        lines.extend(["", "## SNI", *[f"- {item}" for item in candidate.sni]])
    if candidate.arbetsstallen:
        lines.extend(["", "## Arbetsställen", *[f"- {item}" for item in candidate.arbetsstallen]])
    if candidate.handelser:
        lines.extend(["", "## Händelser", *[f"- {item}" for item in candidate.handelser]])
    if candidate.telefon:
        lines.append(f"**Telefon:** {candidate.telefon}")
    flags = []
    if candidate.foretagshypotek is not None:
        flags.append(f"- Företagshypotek: {_bool_sv(candidate.foretagshypotek)}")
    if candidate.betalningsanmarkning is not None:
        flags.append(f"- Betalningsanmärkning: {_bool_sv(candidate.betalningsanmarkning)}")
    if candidate.gasell is not None:
        flags.append(f"- Gasell: {_bool_sv(candidate.gasell)}")
    if flags:
        lines.extend(["", "## Övriga registeruppgifter", *flags])
    account_lines = _account_lines(row)
    if account_lines:
        lines.extend(["", *account_lines])
    return "\n".join(lines)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
    }


async def _get_html(url: str) -> str:
    cached = get_cached("allabolag_html", {"url": url})
    if cached is not None:
        return cached
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
        response = await http.get(url, headers=_headers())
    if response.status_code >= 400:
        raise AllabolagError(
            f"Allabolag HTTP {response.status_code} for {url}"
        )
    html = response.text
    if not html.strip():
        raise AllabolagError(f"Allabolag returned empty HTML for {url}")
    put_cached("allabolag_html", {"url": url}, html)
    return html


async def search_company_rows(query: str) -> list[dict[str, Any]]:
    text = query.strip()
    if not text:
        raise AllabolagError("Search query is required")
    url = f"{_SEARCH_PATH}?q={quote(text)}"
    html = await _get_html(url)
    return search_companies_from_next_data(extract_next_data(html))


async def search_companies(query: str) -> str:
    return format_search_markdown(await search_company_rows(query))


def people_from_search_next_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    block = data.get("props", {}).get("pageProps", {}).get("rolePersons")
    if not isinstance(block, dict):
        raise AllabolagError("Allabolag person search had no rolePersons")
    rows = block.get("businessPersons")
    if not isinstance(rows, list):
        raise AllabolagError("Allabolag person search had no businessPersons")
    return [
        row
        for row in rows
        if isinstance(row, dict) and row.get("personId") and row.get("name")
    ]


def roles_from_person_next_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    person = data.get("props", {}).get("pageProps", {}).get("rolePerson")
    if not isinstance(person, dict):
        raise AllabolagError("Allabolag person page had no rolePerson")
    roles = person.get("roles")
    if roles is None:
        return []
    if not isinstance(roles, list):
        raise AllabolagError("Allabolag person page had no roles list")
    return [row for row in roles if isinstance(row, dict)]


def companies_from_person_roles(roles: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in roles:
        raw = str(row.get("id") or "")
        digits = re.sub(r"\D", "", raw)
        if len(digits) != 10:
            continue
        orgnr = format_orgnr(digits)
        if orgnr in seen:
            continue
        namn = str(row.get("name") or orgnr).strip()
        seen.add(orgnr)
        out.append({"name": namn, "orgnr": orgnr})
    return out


def person_page_path(name: str, person_id: str) -> str:
    person_key = str(person_id).strip()
    if not person_key:
        raise AllabolagError("Allabolag person is missing personId")
    return _PERSON_PATH.format(
        name=quote(_slug(name), safe="-"),
        person_id=quote(person_key, safe=""),
    )


def _pick_person(people: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    wanted = _norm_person_name(name)
    matches = [
        row for row in people if _norm_person_name(str(row.get("name") or "")) == wanted
    ]
    if not matches:
        return None
    return max(matches, key=lambda row: int(row.get("numberOfRoles") or 0))


async def lookup_person_companies(name: str) -> list[dict[str, str]]:
    text = name.strip()
    if not text:
        raise AllabolagError("Person name is required")
    html = await _get_html(f"{_PERSON_SEARCH_PATH}?q={quote(text)}")
    person = _pick_person(people_from_search_next_data(extract_next_data(html)), text)
    if person is None:
        return []
    await _pause()
    page = await _get_html(person_page_path(str(person["name"]), str(person["personId"])))
    return companies_from_person_roles(roles_from_person_next_data(extract_next_data(page)))


async def lookup_company_row(orgnr: str) -> dict[str, Any]:
    formatted = format_orgnr(orgnr)
    html = await _get_html(f"{_SEARCH_PATH}?q={quote(formatted)}")
    rows = search_companies_from_next_data(extract_next_data(html))
    match = next(
        (row for row in rows if format_orgnr(str(row.get("orgnr") or "")) == formatted),
        None,
    )
    if match is None:
        raise AllabolagNotFoundError(f"Allabolag has no company for {formatted}")
    company_html = await _get_html(company_page_path(match))
    return company_from_next_data(extract_next_data(company_html))


async def lookup_company(orgnr: str) -> str:
    return format_lookup_markdown(await lookup_company_row(orgnr))


def companies_from_corporate_structure(payload: dict[str, Any]) -> list[GroupCompany]:
    tree = payload.get("tree")
    if not isinstance(tree, dict):
        raise AllabolagError("Allabolag corporate structure had no tree")
    out: list[GroupCompany] = []

    def walk(node: dict[str, Any], parent_orgnr: str) -> None:
        name = str(node.get("name") or "").strip()
        raw = str(node.get("organisationNumber") or "").strip()
        digits = re.sub(r"\D", "", raw)
        orgnr = format_orgnr(digits) if len(digits) == 10 else ""
        if name:
            out.append(GroupCompany(namn=name, orgnr=orgnr, parent_orgnr=parent_orgnr))
        next_parent = orgnr or parent_orgnr
        children = node.get("sub")
        if not isinstance(children, list):
            return
        for child in children:
            if isinstance(child, dict):
                walk(child, next_parent)

    walk(tree, "")
    return out


async def lookup_corporate_structure(orgnr: str) -> list[GroupCompany]:
    formatted = format_orgnr(orgnr)
    digits = re.sub(r"\D", "", formatted)
    if len(digits) != 10:
        raise AllabolagError(f"Invalid organization number: {orgnr}")
    cached = get_cached("allabolag_corporate_structure", {"orgnr": formatted})
    if cached is not None:
        try:
            payload = json.loads(cached)
        except json.JSONDecodeError as exc:
            raise AllabolagError("Cached Allabolag corporate structure was not JSON") from exc
        if not isinstance(payload, dict):
            raise AllabolagError("Cached Allabolag corporate structure was not an object")
        return companies_from_corporate_structure(payload)
    url = _STRUCTURE_PATH.format(orgnr=digits)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
        response = await http.get(
            url,
            headers={
                "User-Agent": _BROWSER_UA,
                "Accept": "application/json",
                "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
            },
        )
    if response.status_code == 404:
        return []
    if response.status_code >= 400:
        raise AllabolagError(f"Allabolag HTTP {response.status_code} for {url}")
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise AllabolagError("Allabolag corporate structure was not JSON") from exc
    if not isinstance(payload, dict):
        raise AllabolagError("Allabolag corporate structure was not an object")
    put_cached("allabolag_corporate_structure", {"orgnr": formatted}, response.text)
    return companies_from_corporate_structure(payload)


def _has_company_page_facts(candidate: DdCandidateCompany) -> bool:
    return any(year.poster for year in candidate.rakenskaper)


async def enrich_candidates(rows: list[DdCandidateCompany]) -> list[DdCandidateCompany]:
    out: list[DdCandidateCompany] = []
    for candidate in rows:
        if _has_company_page_facts(candidate):
            out.append(candidate)
            continue
        try:
            raw = await lookup_company_row(candidate.organisationsnummer)
        except AllabolagNotFoundError:
            out.append(candidate)
            continue
        detailed = candidate_from_allabolag(raw)
        out.append(
            detailed.model_copy(
                update={
                    "id": candidate.id,
                    "namn": candidate.namn or detailed.namn,
                    "beskrivning": detailed.beskrivning or candidate.beskrivning,
                }
            )
        )
    return out


async def validate_orgnr(orgnr: str) -> str:
    formatted = format_orgnr(orgnr)
    digits = re.sub(r"\D", "", formatted)
    if len(digits) not in {10, 12}:
        raise AllabolagError(f"Invalid organization number: {orgnr}")
    return f"Valid organization number: {formatted}"
