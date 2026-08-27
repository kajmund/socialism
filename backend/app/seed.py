"""Seed SQLite with demo data matching the frontend mock library."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.database.models import Message, Persona, Population, PopulationMember, Run
from app.database.session import SessionLocal, engine
from app.schemas.domain import EditablePersona, new_message_id
from app.serializers import blank_profile, persona_initials
from app.services.kund_store import bolag_demo_customer_id, default_os_customer_id, default_os_project_id
from app.services.prompt_store import ensure_default_configurations


def _dt(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


def _profile(
    name: str,
    *,
    age: int,
    kön: str,
    ort: str,
    yrke: str,
    utbildning: str,
    livssituation: str,
    lutning: str,
    sakfragor: str,
    fortroende: str,
    ton: str,
    sprak: str,
    medievanor: str,
    parti: str,
    valdeltagande: str,
    anekdot: str,
) -> dict:
    base = blank_profile(name).model_dump()
    base.update(
        {
            "initials": persona_initials(name),
            "age": str(age),
            "kön": kön,
            "ort": ort,
            "yrke": yrke,
            "utbildning": utbildning,
            "livssituation": livssituation,
            "lutning": lutning,
            "sakfragor": sakfragor,
            "fortroende": fortroende,
            "ton": ton,
            "sprak": sprak,
            "medievanor": medievanor,
            "parti": parti,
            "valdeltagande": valdeltagande,
            "anekdot": anekdot,
        }
    )
    return EditablePersona.model_validate(base).model_dump()


def _recipe(
    size: int,
    *,
    seed: int,
    age_rows: list[tuple[str, str, int]],
    district_rows: list[tuple[str, str, int]],
    occ_rows: list[tuple[str, str, int]],
    lean_rows: list[tuple[str, str, int]],
) -> dict:
    return {
        "size": size,
        "entryMode": "manual",
        "freeText": "",
        "locale": "local",
        "seed": seed,
        "dist": {
            "age": {
                "label": "Ålder",
                "rows": [{"k": k, "l": l, "v": v} for k, l, v in age_rows],
            },
            "district": {
                "label": "Distrikt",
                "rows": [{"k": k, "l": l, "v": v} for k, l, v in district_rows],
            },
            "occ": {
                "label": "Yrke",
                "rows": [{"k": k, "l": l, "v": v} for k, l, v in occ_rows],
            },
            "lean": {
                "label": "Lutning",
                "rows": [{"k": k, "l": l, "v": v} for k, l, v in lean_rows],
            },
        },
    }


def _injection(
    *,
    key: str,
    type: str,
    sender: str,
    text: str,
    message_id: str | None = None,
    mode: str = "text",
    url: str = "",
    source_domain: str = "",
) -> dict:
    return {
        "key": key,
        "type": type,
        "sender": sender,
        "text": text,
        "mode": mode,
        "url": url,
        "fetching": False,
        "sourceDomain": source_domain,
        "isVideo": False,
        "message_id": message_id,
    }


def _tick(
    *,
    key: str,
    day: int,
    rounds: int = 1,
    measurements: list[str] | None = None,
    injections: list[dict] | None = None,
    silent: bool = False,
    interviews: list[dict] | None = None,
) -> dict:
    return {
        "key": key,
        "day": day,
        "silent": silent,
        "injections": injections or [],
        "rounds": rounds,
        "measurements": measurements or [],
        "interviews": interviews or [],
    }


PERSONAS: list[dict] = [
    {
        "id": "mh",
        "name": "Margareta Hellström",
        "age": 67,
        "occ": "Pensionerad undersköterska",
        "district": "Distrikt A",
        "quote": "Vackra ord räcker inte — jag vill se det i pengar.",
        "origin": "population",
        "updated": "2026-07-24",
        "pops": ["Baslinjepopulation", "Kärnväljare"],
        "profile": _profile(
            "Margareta Hellström",
            age=67,
            kön="Kvinna",
            ort="Distrikt A",
            yrke="Pensionerad undersköterska",
            utbildning="Gymnasium",
            livssituation="Gift, vuxna barn",
            lutning="Mitt-vänster",
            sakfragor="Vård och skola",
            fortroende="Lågt för kommunen / Högt för sjukvården",
            ton="Uppgiven men engagerad",
            sprak="Kort och konkret",
            medievanor="Lokal nyhetskälla",
            parti="Socialdemokraterna",
            valdeltagande="Röstar alltid",
            anekdot="Igår mötte jag en gammal kollega från vårdcentralen i Distrikt A.",
        ),
    },
    {
        "id": "hy",
        "name": "Hassan Youssef",
        "age": 29,
        "occ": "Lagerarbetare",
        "district": "Distrikt B",
        "quote": "Ingen har frågat oss vad vi faktiskt tycker.",
        "origin": "population",
        "updated": "2026-07-23",
        "pops": ["Svängväljartest", "Stresstest opposition"],
        "profile": _profile(
            "Hassan Youssef",
            age=29,
            kön="Man",
            ort="Distrikt B",
            yrke="Lagerarbetare",
            utbildning="Gymnasium",
            livssituation="Sambo, barn",
            lutning="Mitt",
            sakfragor="Ekonomi och jobb",
            fortroende="Blandat, skeptisk generellt",
            ton="Direkt och kort i tonen",
            sprak="Vardagligt, många skämt",
            medievanor="Instagram, FB-grupper",
            parti="Osäker väljare",
            valdeltagande="Röstar oftast",
            anekdot="Förra veckan stod jag i kö vid busshållplatsen i Distrikt B i regnet.",
        ),
    },
    {
        "id": "el",
        "name": "Eva Lindqvist",
        "age": 41,
        "occ": "Grundskollärare",
        "district": "Distrikt C",
        "quote": "Jag orkar inte med fler tomma vallöften om skolan.",
        "origin": "beskrivning",
        "updated": "2026-07-22",
        "pops": ["Ung urban", "Referensgrupp B"],
        "profile": _profile(
            "Eva Lindqvist",
            age=41,
            kön="Kvinna",
            ort="Distrikt C",
            yrke="Grundskollärare",
            utbildning="Högskola",
            livssituation="Sambo, barn",
            lutning="Vänster",
            sakfragor="Vård och skola",
            fortroende="Lågt för kommunen",
            ton="Sarkastisk och otålig",
            sprak="Långa resonemang",
            medievanor="Lokal nyhetskälla",
            parti="Miljöpartiet",
            valdeltagande="Röstar alltid",
            anekdot="Min syster brukar fråga om skolan när hon ringer från Distrikt C.",
        ),
    },
    {
        "id": "bk",
        "name": "Bengt Karlsson",
        "age": 58,
        "occ": "Taxichaufför",
        "district": "Centrum",
        "quote": "Säg vad det kostar, inte bara vad det ger.",
        "origin": "manuell",
        "updated": "2026-07-20",
        "pops": ["Baslinjepopulation", "Stresstest opposition"],
        "profile": _profile(
            "Bengt Karlsson",
            age=58,
            kön="Man",
            ort="Centrum",
            yrke="Taxichaufför",
            utbildning="Grundskola",
            livssituation="Ensamhushåll",
            lutning="Mitt-höger",
            sakfragor="Ekonomi och jobb",
            fortroende="Blandat, skeptisk generellt",
            ton="Cynisk mot politiker",
            sprak="Kort och konkret",
            medievanor="Regional TV",
            parti="Moderaterna",
            valdeltagande="Röstar oftast",
            anekdot="En kund i Centrum berättade nyligen om sex timmars akutväntan.",
        ),
    },
    {
        "id": "fa",
        "name": "Fatima Al-Amin",
        "age": 34,
        "occ": "Barnmorska",
        "district": "Distrikt D",
        "quote": "Ett datum. Ett faktiskt startdatum — inte luddigt.",
        "origin": "demografi",
        "updated": "2026-07-19",
        "pops": ["Kärnväljare", "Svängväljartest", "Mediefokusgrupp"],
        "profile": _profile(
            "Fatima Al-Amin",
            age=34,
            kön="Kvinna",
            ort="Distrikt D",
            yrke="Barnmorska",
            utbildning="Högskola",
            livssituation="Sambo, barn",
            lutning="Vänster",
            sakfragor="Vård och skola",
            fortroende="Lågt för kommunen / Högt för sjukvården",
            ton="Direkt och kort i tonen",
            sprak="Blandar in fackspråk",
            medievanor="Instagram, FB-grupper",
            parti="Vänsterpartiet",
            valdeltagande="Röstar alltid",
            anekdot="Igår mötte jag en kollega från förlossningen vid affären i Distrikt D.",
        ),
    },
    {
        "id": "sa",
        "name": "Sven Andersson",
        "age": 72,
        "occ": "Pensionär, f.d. verkstadsarbetare",
        "district": "Distrikt A",
        "quote": "Förr höll man vad man lovade. Nu är allt floskler.",
        "origin": "population",
        "updated": "2026-07-18",
        "pops": ["Baslinjepopulation", "Pilotgrupp"],
        "profile": _profile(
            "Sven Andersson",
            age=72,
            kön="Man",
            ort="Distrikt A",
            yrke="Pensionär, f.d. verkstadsarbetare",
            utbildning="Grundskola",
            livssituation="Gift, vuxna barn",
            lutning="Mitt-vänster",
            sakfragor="Bostäder och trygghet",
            fortroende="Lågt för kommunen",
            ton="Uppgiven men engagerad",
            sprak="Kort och konkret",
            medievanor="Lokal nyhetskälla",
            parti="Socialdemokraterna",
            valdeltagande="Röstar alltid",
            anekdot="Min kusin från verkstan skickade bilder från lunchrummet igår.",
        ),
    },
    {
        "id": "ab",
        "name": "Amanda Berg",
        "age": 23,
        "occ": "Undersköterska, timvikariat",
        "district": "Centrum",
        "quote": "Jag är trött på att höra att vi är unga och otåliga.",
        "origin": "beskrivning",
        "updated": "2026-07-17",
        "pops": ["Ung urban", "Pilotgrupp"],
        "profile": _profile(
            "Amanda Berg",
            age=23,
            kön="Kvinna",
            ort="Centrum",
            yrke="Undersköterska",
            utbildning="Gymnasium",
            livssituation="Bor med föräldrar",
            lutning="Mitt",
            sakfragor="Vård och skola",
            fortroende="Högt för sjukvården",
            ton="Optimistisk och pratglad",
            sprak="Vardagligt, många skämt",
            medievanor="Instagram, FB-grupper",
            parti="Osäker väljare",
            valdeltagande="Osäker om hen röstar",
            anekdot="Som boende med föräldrar hänger jag ofta vid biblioteket i Centrum.",
        ),
    },
    {
        "id": "mn",
        "name": "Mikael Nilsson",
        "age": 46,
        "occ": "Egen företagare, bygg",
        "district": "Distrikt C",
        "quote": "Regelkrångel tar mer tid än själva jobbet.",
        "origin": "manuell",
        "updated": "2026-07-16",
        "pops": ["Svängväljartest", "Referensgrupp B"],
        "profile": _profile(
            "Mikael Nilsson",
            age=46,
            kön="Man",
            ort="Distrikt C",
            yrke="Egen företagare",
            utbildning="Gymnasium",
            livssituation="Sambo, barn",
            lutning="Höger",
            sakfragor="Ekonomi och jobb",
            fortroende="Blandat, skeptisk generellt",
            ton="Sarkastisk och otålig",
            sprak="Kort och konkret",
            medievanor="Lite/ingen media",
            parti="Moderaterna",
            valdeltagande="Röstar oftast",
            anekdot="En granne i Distrikt C berättade nyligen om sitt barns fotbollsmatch.",
        ),
    },
    {
        "id": "yk",
        "name": "Yasmin Karlsson",
        "age": 19,
        "occ": "Studerande",
        "district": "Centrum",
        "quote": "Ingen av kandidaterna pratar om något jag känner igen mig i.",
        "origin": "demografi",
        "updated": "2026-07-14",
        "pops": ["Ung urban", "Utkast — ej klar"],
        "profile": _profile(
            "Yasmin Karlsson",
            age=19,
            kön="Kvinna",
            ort="Centrum",
            yrke="Studerande",
            utbildning="Gymnasium",
            livssituation="Bor med föräldrar",
            lutning="Mitt",
            sakfragor="Miljö och klimat",
            fortroende="Blandat, skeptisk generellt",
            ton="Optimistisk och pratglad",
            sprak="Vardagligt, många skämt",
            medievanor="Instagram, FB-grupper",
            parti="Osäker väljare",
            valdeltagande="Osäker om hen röstar",
            anekdot="Förra veckan stod jag i kö vid busshållplatsen i Centrum i regnet.",
        ),
    },
    {
        "id": "as",
        "name": "Anders Svensson",
        "age": 52,
        "occ": "Handläggare, kommunen",
        "district": "Centrum",
        "quote": "Jag ser båda sidor av budgeten — det gör mig skeptisk till löften.",
        "origin": "population",
        "updated": "2026-07-12",
        "pops": ["Mediefokusgrupp", "Referensgrupp B"],
        "profile": _profile(
            "Anders Svensson",
            age=52,
            kön="Man",
            ort="Centrum",
            yrke="Handläggare",
            utbildning="Högskola",
            livssituation="Sambo, inga barn",
            lutning="Mitt",
            sakfragor="Bostäder och trygghet",
            fortroende="Blandat, skeptisk generellt",
            ton="Direkt och kort i tonen",
            sprak="Långa resonemang",
            medievanor="Lokal nyhetskälla",
            parti="Centerpartiet",
            valdeltagande="Röstar alltid",
            anekdot="Igår mötte jag en kollega från kommunen vid affären i Centrum.",
        ),
    },
    {
        "id": "kn",
        "name": "Karin Nilsson",
        "age": 38,
        "occ": "Butiksbiträde",
        "district": "Distrikt B",
        "quote": "Jag röstar på den som pratar om min vardag, inte visioner.",
        "origin": "manuell",
        "updated": "2026-07-08",
        "pops": ["Pilotgrupp", "Utkast — ej klar", "Stresstest opposition"],
        "profile": _profile(
            "Karin Nilsson",
            age=38,
            kön="Kvinna",
            ort="Distrikt B",
            yrke="Butiksbiträde",
            utbildning="Gymnasium",
            livssituation="Ensamhushåll",
            lutning="Mitt",
            sakfragor="Ekonomi och jobb",
            fortroende="Lågt för kommunen",
            ton="Uppgiven men engagerad",
            sprak="Kort och konkret",
            medievanor="Regional TV",
            parti="Osäker väljare",
            valdeltagande="Röstar oftast",
            anekdot="Min syster brukar fråga om vardagen när hon ringer från Distrikt B.",
        ),
    },
    {
        "id": "ib",
        "name": "Ingrid Berg",
        "age": 64,
        "occ": "Fd. sjuksköterska",
        "district": "Distrikt D",
        "quote": "Trygghet på äldre dar — visa mig vad det betyder i praktiken.",
        "origin": "population",
        "updated": "2026-07-03",
        "pops": ["Kärnväljare", "Mediefokusgrupp"],
        "profile": _profile(
            "Ingrid Berg",
            age=64,
            kön="Kvinna",
            ort="Distrikt D",
            yrke="Fd. sjuksköterska",
            utbildning="Högskola",
            livssituation="Gift, vuxna barn",
            lutning="Mitt-vänster",
            sakfragor="Vård och skola",
            fortroende="Högt för sjukvården",
            ton="Uppgiven men engagerad",
            sprak="Blandar in fackspråk",
            medievanor="Lokal nyhetskälla",
            parti="Socialdemokraterna",
            valdeltagande="Röstar alltid",
            anekdot="Igår mötte jag en kollega från vården vid affären i Distrikt D.",
        ),
    },
]

POPULATIONS: list[dict] = [
    {
        "name": "Baslinjepopulation",
        "versions": 1,
        "updated": "2026-07-24",
        "fp": [[35, 40, 25], [22, 38, 40], [30, 45, 25]],
        "recipe": _recipe(
            3,
            seed=101,
            age_rows=[("a65", "65+", 40), ("a45", "45–64", 35), ("a25", "25–44", 25)],
            district_rows=[
                ("a", "Distrikt A", 50),
                ("c", "Centrum", 50),
            ],
            occ_rows=[
                ("vard", "Vård/omsorg", 40),
                ("ovrigt", "Övrigt", 35),
                ("tjanst", "Tjänsteman", 25),
            ],
            lean_rows=[
                ("mvanster", "Mitt-vänster", 45),
                ("mhoger", "Mitt-höger", 30),
                ("mitt", "Mitt", 25),
            ],
        ),
    },
    {
        "name": "Svängväljartest",
        "versions": 2,
        "updated": "2026-07-21",
        "fp": [[45, 35, 20], [40, 30, 30], [20, 50, 30]],
        "recipe": _recipe(
            3,
            seed=102,
            age_rows=[("a25", "25–44", 45), ("a45", "45–64", 35), ("a18", "18–24", 20)],
            district_rows=[
                ("b", "Distrikt B", 40),
                ("d", "Distrikt D", 30),
                ("c", "Distrikt C", 30),
            ],
            occ_rows=[
                ("industri", "Industri/lager", 40),
                ("vard", "Vård/omsorg", 30),
                ("foretag", "Företagare", 30),
            ],
            lean_rows=[
                ("mitt", "Mitt", 50),
                ("vanster", "Vänster", 20),
                ("hoger", "Höger", 30),
            ],
        ),
    },
    {
        "name": "Stresstest opposition",
        "versions": 1,
        "updated": "2026-07-19",
        "fp": [[20, 50, 30], [55, 25, 20], [35, 35, 30]],
        "recipe": _recipe(
            3,
            seed=103,
            age_rows=[("a25", "25–44", 40), ("a45", "45–64", 40), ("a65", "65+", 20)],
            district_rows=[
                ("b", "Distrikt B", 55),
                ("c", "Centrum", 25),
                ("a", "Distrikt A", 20),
            ],
            occ_rows=[
                ("industri", "Industri/lager", 35),
                ("handel", "Handel", 35),
                ("tjanst", "Tjänsteman", 30),
            ],
            lean_rows=[
                ("hoger", "Höger", 40),
                ("mhoger", "Mitt-höger", 35),
                ("mitt", "Mitt", 25),
            ],
        ),
    },
    {
        "name": "Ung urban",
        "versions": 1,
        "updated": "2026-07-18",
        "fp": [[70, 22, 8], [30, 40, 30], [50, 30, 20]],
        "recipe": _recipe(
            3,
            seed=104,
            age_rows=[("a18", "18–24", 50), ("a25", "25–44", 40), ("a45", "45–64", 10)],
            district_rows=[
                ("c", "Centrum", 70),
                ("d", "Distrikt C", 20),
                ("o", "Övriga", 10),
            ],
            occ_rows=[
                ("stud", "Studerande", 40),
                ("vard", "Vård/omsorg", 30),
                ("utbildning", "Utbildning", 30),
            ],
            lean_rows=[
                ("vanster", "Vänster", 40),
                ("mitt", "Mitt", 40),
                ("mvanster", "Mitt-vänster", 20),
            ],
        ),
    },
    {
        "name": "Kärnväljare",
        "versions": 3,
        "updated": "2026-07-15",
        "fp": [[15, 45, 40], [60, 25, 15], [25, 40, 35]],
        "recipe": _recipe(
            3,
            seed=105,
            age_rows=[("a65", "65+", 40), ("a45", "45–64", 35), ("a25", "25–44", 25)],
            district_rows=[
                ("a", "Distrikt A", 40),
                ("d", "Distrikt D", 40),
                ("c", "Centrum", 20),
            ],
            occ_rows=[
                ("vard", "Vård/omsorg", 60),
                ("ovrigt", "Övrigt", 25),
                ("tjanst", "Tjänsteman", 15),
            ],
            lean_rows=[
                ("mvanster", "Mitt-vänster", 45),
                ("vanster", "Vänster", 40),
                ("mitt", "Mitt", 15),
            ],
        ),
    },
    {
        "name": "Pilotgrupp",
        "versions": 1,
        "updated": "2026-07-12",
        "fp": [[33, 34, 33], [33, 34, 33], [33, 34, 33]],
        "recipe": _recipe(
            3,
            seed=106,
            age_rows=[("a25", "25–44", 34), ("a45", "45–64", 33), ("a65", "65+", 33)],
            district_rows=[
                ("a", "Distrikt A", 34),
                ("b", "Distrikt B", 33),
                ("c", "Centrum", 33),
            ],
            occ_rows=[
                ("vard", "Vård/omsorg", 34),
                ("handel", "Handel", 33),
                ("ovrigt", "Övrigt", 33),
            ],
            lean_rows=[
                ("mitt", "Mitt", 34),
                ("mvanster", "Mitt-vänster", 33),
                ("mhoger", "Mitt-höger", 33),
            ],
        ),
    },
    {
        "name": "Mediefokusgrupp",
        "versions": 1,
        "updated": "2026-07-10",
        "fp": [[25, 55, 20], [30, 45, 25], [40, 30, 30]],
        "recipe": _recipe(
            3,
            seed=107,
            age_rows=[("a25", "25–44", 40), ("a45", "45–64", 40), ("a65", "65+", 20)],
            district_rows=[
                ("d", "Distrikt D", 40),
                ("c", "Centrum", 40),
                ("a", "Distrikt A", 20),
            ],
            occ_rows=[
                ("vard", "Vård/omsorg", 45),
                ("tjanst", "Tjänsteman", 30),
                ("ovrigt", "Övrigt", 25),
            ],
            lean_rows=[
                ("vanster", "Vänster", 35),
                ("mvanster", "Mitt-vänster", 35),
                ("mitt", "Mitt", 30),
            ],
        ),
    },
    {
        "name": "Referensgrupp B",
        "versions": 1,
        "updated": "2026-07-05",
        "fp": [[30, 40, 30], [35, 35, 30], [34, 33, 33]],
        "recipe": _recipe(
            3,
            seed=108,
            age_rows=[("a25", "25–44", 40), ("a45", "45–64", 40), ("a18", "18–24", 20)],
            district_rows=[
                ("c", "Distrikt C", 40),
                ("centrum", "Centrum", 35),
                ("b", "Distrikt B", 25),
            ],
            occ_rows=[
                ("utbildning", "Utbildning", 35),
                ("foretag", "Företagare", 35),
                ("tjanst", "Tjänsteman", 30),
            ],
            lean_rows=[
                ("mitt", "Mitt", 40),
                ("vanster", "Vänster", 30),
                ("hoger", "Höger", 30),
            ],
        ),
    },
    {
        "name": "Utkast — ej klar",
        "versions": 1,
        "updated": "2026-07-02",
        "fp": [[50, 30, 20], [45, 35, 20], [30, 40, 30]],
        "recipe": _recipe(
            2,
            seed=109,
            age_rows=[("a18", "18–24", 50), ("a25", "25–44", 30), ("a45", "45–64", 20)],
            district_rows=[
                ("c", "Centrum", 50),
                ("b", "Distrikt B", 30),
                ("o", "Övriga", 20),
            ],
            occ_rows=[
                ("stud", "Studerande", 50),
                ("handel", "Handel", 30),
                ("ovrigt", "Övrigt", 20),
            ],
            lean_rows=[
                ("mitt", "Mitt", 60),
                ("vanster", "Vänster", 20),
                ("mhoger", "Mitt-höger", 20),
            ],
        ),
    },
    {
        "name": "Prompt benchmark (full)",
        "versions": 1,
        "updated": "2026-08-18",
        "fp": [[35, 40, 25], [30, 35, 35], [30, 45, 25]],
        "recipe": _recipe(
            12,
            seed=110,
            age_rows=[("a25", "25–44", 35), ("a45", "45–64", 40), ("a65", "65+", 25)],
            district_rows=[
                ("a", "Distrikt A", 30),
                ("b", "Distrikt B", 25),
                ("c", "Centrum", 25),
                ("d", "Distrikt D", 20),
            ],
            occ_rows=[
                ("vard", "Vård/omsorg", 35),
                ("tjanst", "Tjänsteman", 25),
                ("industri", "Industri/lager", 20),
                ("ovrigt", "Övrigt", 20),
            ],
            lean_rows=[
                ("vanster", "Vänster", 25),
                ("mvanster", "Mitt-vänster", 25),
                ("mitt", "Mitt", 25),
                ("mhoger", "Mitt-höger", 15),
                ("hoger", "Höger", 10),
            ],
        ),
    },
]

# Stable ids so runs can reference budskap via message_id.
MSG_TRYGGHET = "msg-trygghet-vardagen"
MSG_KORT = "msg-kort-format"
MSG_LANG = "msg-langt-format"
MSG_REKLAM = "msg-reklampost"
MSG_NYHET = "msg-vardcentral"

MESSAGES: list[dict] = [
    {
        "id": MSG_TRYGGHET,
        "type": "post",
        "title": "Trygghet i vardagen",
        "body": (
            "Trygghet börjar i vardagen — i kommunen och i hela Sverige. "
            "Vi investerar i äldreomsorg nära dig, med fler undersköterskor "
            "och kortare väntetider på akuten."
        ),
        "source_url": None,
        "metadata": {"variant": "narrative", "sender": "Socialdemokraterna"},
        "created": "2026-07-18",
    },
    {
        "id": MSG_KORT,
        "type": "post",
        "title": "Kort format — tre punkter",
        "body": (
            "Tre konkreta löften: 200 nya undersköterskor, kortare akutköer, "
            "och mer personal i hemtjänsten. Inga floskler — bara siffror."
        ),
        "source_url": None,
        "metadata": {"variant": "concise", "sender": "Socialdemokraterna"},
        "created": "2026-07-20",
    },
    {
        "id": MSG_LANG,
        "type": "post",
        "title": "Långt format — principer",
        "body": (
            "Vi måste investera i äldreomsorgen. Sverige förtjänar trygghet på "
            "äldre dar och en värdig omsorg för alla. Solidaritet är ingen slogan "
            "— det är hur vi bygger ett samhälle där ingen lämnas efter."
        ),
        "source_url": None,
        "metadata": {"variant": "analytical", "sender": "Socialdemokraterna"},
        "created": "2026-07-20",
    },
    {
        "id": MSG_REKLAM,
        "type": "post",
        "title": "Reklampost — lokal räckvidd",
        "body": (
            "Har du väntat för länge på vård? Vi hör dig. Följ vår kampanj "
            "för mer personal i kommunen — och dela vidare till någon som berörs."
        ),
        "source_url": None,
        "metadata": {"variant": "narrative", "sender": "@partihandle"},
        "created": "2026-07-25",
    },
    {
        "id": MSG_NYHET,
        "type": "news",
        "title": "Kommunen planerar ny vårdcentral",
        "body": (
            "Kommunen utreder en ny vårdcentral i södra stadsdelarna. "
            "Beslut väntas under hösten enligt lokalnyheterna."
        ),
        "source_url": "https://example.com/nyheter/vardcentral",
        "metadata": {"sender": "Lokalnyheterna", "sourceDomain": "example.com"},
        "created": "2026-07-21",
    },
]

RUNS: list[dict] = [
    {
        "name": "Trygghetsbudskap — huvudtest",
        "status": "done",
        "population": "Kärnväljare",
        "seed": "7f3a1c9d",
        "updated": "2026-07-24",
        "oasis_options": {"platform": "twitter", "allow_population_create_post": True},
        "main_ticks": [
            _tick(
                key="t1",
                day=1,
                rounds=2,
                measurements=["opinion_snapshot"],
                injections=[
                    _injection(
                        key="i1",
                        type="party_post",
                        sender="Socialdemokraterna",
                        text=(
                            "Trygghet börjar i vardagen — i kommunen och i hela Sverige. "
                            "Vi investerar i äldreomsorg nära dig."
                        ),
                        message_id=MSG_TRYGGHET,
                    )
                ],
                interviews=[
                    {
                        "key": "iv1",
                        "persona_id": "mh",
                        "prompt": "Vad tänker du efter att ha sett partiers inlägg om trygghet?",
                    }
                ],
            )
        ],
        "branch": {
            "afterIndex": 0,
            "mode": "ab",
            "a": [
                _tick(
                    key="ta1",
                    day=2,
                    rounds=1,
                    measurements=["sentiment_baseline"],
                    injections=[
                        _injection(
                            key="ia1",
                            type="party_post",
                            sender="Socialdemokraterna",
                            text=MESSAGES[1]["body"],
                            message_id=MSG_KORT,
                        )
                    ],
                )
            ],
            "b": [
                _tick(
                    key="tb1",
                    day=2,
                    rounds=1,
                    measurements=["sentiment_baseline"],
                    injections=[
                        _injection(
                            key="ib1",
                            type="party_post",
                            sender="Socialdemokraterna",
                            text=MESSAGES[2]["body"],
                            message_id=MSG_LANG,
                        )
                    ],
                )
            ],
        },
    },
    {
        "name": "Kort vs. långt format",
        "status": "done",
        "population": "Svängväljartest",
        "seed": "b2e08a41",
        "updated": "2026-07-22",
        "oasis_options": {"platform": "twitter", "allow_population_create_post": True},
        "main_ticks": [
            _tick(
                key="t2",
                day=1,
                rounds=1,
                measurements=["opinion_snapshot"],
                injections=[
                    _injection(
                        key="i2",
                        type="news_post",
                        sender="Lokalnyheterna",
                        text=MESSAGES[4]["body"],
                        message_id=MSG_NYHET,
                        mode="link",
                        url="https://example.com/nyheter/vardcentral",
                        source_domain="example.com",
                    )
                ],
            )
        ],
        "branch": {
            "afterIndex": 0,
            "mode": "ab",
            "a": [
                _tick(
                    key="ta2",
                    day=2,
                    rounds=1,
                    injections=[
                        _injection(
                            key="ia2",
                            type="party_post",
                            sender="Socialdemokraterna",
                            text=MESSAGES[1]["body"],
                            message_id=MSG_KORT,
                        )
                    ],
                )
            ],
            "b": [
                _tick(
                    key="tb2",
                    day=2,
                    rounds=1,
                    injections=[
                        _injection(
                            key="ib2",
                            type="party_post",
                            sender="Socialdemokraterna",
                            text=MESSAGES[2]["body"],
                            message_id=MSG_LANG,
                        )
                    ],
                )
            ],
        },
    },
    {
        "name": "Baslinje — enkel injektion",
        "status": "done",
        "population": "Baslinjepopulation",
        "seed": "1d9c3f77",
        "updated": "2026-07-19",
        "oasis_options": {"platform": "twitter", "allow_population_create_post": True},
        "main_ticks": [
            _tick(
                key="t3",
                day=1,
                rounds=1,
                measurements=["opinion_snapshot"],
                injections=[
                    _injection(
                        key="i3",
                        type="party_post",
                        sender="Socialdemokraterna",
                        text=MESSAGES[0]["body"],
                        message_id=MSG_TRYGGHET,
                    )
                ],
            )
        ],
        "branch": None,
    },
    {
        "name": "Reklampost — pilot",
        "status": "running",
        "population": "Mediefokusgrupp",
        "seed": "5a0e2b6c",
        "updated": "2026-07-26",
        "oasis_options": {"platform": "twitter", "allow_population_create_post": False},
        "main_ticks": [
            _tick(
                key="t4",
                day=1,
                rounds=1,
                measurements=["engagement_decay"],
                injections=[
                    _injection(
                        key="i4",
                        type="ad_post",
                        sender="@partihandle",
                        text=MESSAGES[3]["body"],
                        message_id=MSG_REKLAM,
                    )
                ],
            )
        ],
        "branch": None,
    },
    {
        "name": "Ton A/B — uppföljning",
        "status": "draft",
        "population": "Kärnväljare",
        "seed": "c48f119e",
        "updated": "2026-07-15",
        "oasis_options": {"platform": "twitter", "allow_population_create_post": True},
        "main_ticks": [
            _tick(
                key="t5",
                day=1,
                rounds=1,
                measurements=["opinion_snapshot"],
                injections=[
                    _injection(
                        key="i5",
                        type="party_post",
                        sender="Socialdemokraterna",
                        text=MESSAGES[0]["body"],
                        message_id=MSG_TRYGGHET,
                    )
                ],
            )
        ],
        "branch": {
            "afterIndex": 0,
            "mode": "stimulus_control",
            "a": [
                _tick(
                    key="ta5",
                    day=2,
                    rounds=1,
                    injections=[
                        _injection(
                            key="ia5",
                            type="party_post",
                            sender="Socialdemokraterna",
                            text=MESSAGES[1]["body"],
                            message_id=MSG_KORT,
                        )
                    ],
                )
            ],
            "b": [
                _tick(
                    key="tb5",
                    day=2,
                    silent=True,
                    rounds=1,
                )
            ],
        },
    },
    {
        "name": "Stresstest — snabb sekvens",
        "status": "draft",
        "population": "Baslinjepopulation",
        "seed": "90ad4d23",
        "updated": "2026-07-11",
        "oasis_options": {"platform": "reddit", "allow_population_create_post": True},
        "main_ticks": [
            _tick(
                key="t6",
                day=1,
                rounds=1,
                injections=[
                    _injection(
                        key="i6a",
                        type="party_post",
                        sender="Socialdemokraterna",
                        text=MESSAGES[1]["body"],
                        message_id=MSG_KORT,
                    )
                ],
            ),
            _tick(
                key="t6b",
                day=2,
                rounds=1,
                injections=[
                    _injection(
                        key="i6b",
                        type="news_post",
                        sender="Lokalnyheterna",
                        text=MESSAGES[4]["body"],
                        message_id=MSG_NYHET,
                        mode="link",
                        url="https://example.com/nyheter/vardcentral",
                        source_domain="example.com",
                    )
                ],
            ),
        ],
        "branch": None,
    },
    {
        "name": "Prompt benchmark — volym",
        "status": "done",
        "population": "Prompt benchmark (full)",
        "seed": "prompt-bench-vol",
        "updated": "2026-08-18",
        "oasis_options": {"platform": "twitter", "allow_population_create_post": True},
        "main_ticks": [
            _tick(
                key="pb1",
                day=1,
                rounds=3,
                measurements=["opinion_snapshot"],
                injections=[
                    _injection(
                        key="ipb1",
                        type="party_post",
                        sender="Socialdemokraterna",
                        text=MESSAGES[0]["body"],
                        message_id=MSG_TRYGGHET,
                    )
                ],
            ),
            _tick(
                key="pb2",
                day=2,
                rounds=3,
                measurements=["engagement_decay"],
                injections=[
                    _injection(
                        key="ipb2",
                        type="party_post",
                        sender="Socialdemokraterna",
                        text=MESSAGES[1]["body"],
                        message_id=MSG_KORT,
                    )
                ],
            ),
        ],
        "branch": None,
    },
]


def _ensure_data_dir() -> None:
    # Relative sqlite paths resolve from CWD (backend/).
    Path("data").mkdir(parents=True, exist_ok=True)


def _assert_profiles_complete() -> None:
    required = set(EditablePersona.model_fields)
    for row in PERSONAS:
        profile = row["profile"]
        missing = sorted(k for k in required if k not in profile)
        empty = sorted(
            k
            for k, value in profile.items()
            if isinstance(value, str) and value.strip() in ("", "—", "-")
        )
        if missing or empty:
            raise RuntimeError(
                f"Seed persona {row['id']} has incomplete profile "
                f"(missing={missing}, empty={empty})"
            )


async def seed(*, reset: bool = True) -> None:
    _ensure_data_dir()
    _assert_profiles_complete()
    async with SessionLocal() as session:
        config_added = await ensure_default_configurations(session)

        if reset:
            await session.execute(delete(Run))
            await session.execute(delete(PopulationMember))
            await session.execute(delete(Population))
            await session.execute(delete(Persona))
            await session.execute(delete(Message))
            await session.commit()

        existing = await session.execute(select(Persona).limit(1))
        if existing.scalar_one_or_none() is not None:
            print(
                "Database already has data; pass reset=True to wipe and reseed."
                + (
                    f" Configurations/catalog: +{config_added}."
                    if config_added
                    else ""
                )
            )
            return

        customer_id = await default_os_customer_id(session)
        project_id = await default_os_project_id(session)
        for row in PERSONAS:
            session.add(
                Persona(
                    id=row["id"],
                    customer_id=customer_id,
                    name=row["name"],
                    age=row["age"],
                    occ=row["occ"],
                    district=row["district"],
                    quote=row["quote"],
                    origin=row["origin"],
                    profile=row["profile"],
                    updated_at=_dt(row["updated"]),
                )
            )
        await session.flush()

        for row in MESSAGES:
            session.add(
                Message(
                    id=row["id"],
                    project_id=project_id,
                    type=row["type"],
                    title=row["title"],
                    body=row["body"],
                    source_url=row["source_url"],
                    metadata_=row["metadata"],
                    created_at=_dt(row["created"]),
                )
            )
        await session.flush()

        pop_by_name: dict[str, Population] = {}
        for row in POPULATIONS:
            recipe = dict(row["recipe"])
            population = Population(
                name=row["name"],
                size=int(recipe["size"]),
                versions=row["versions"],
                fingerprint=row["fp"],
                recipe=recipe,
                updated_at=_dt(row["updated"]),
            )
            session.add(population)
            await session.flush()
            pop_by_name[population.name] = population

        member_counts: dict[str, int] = {name: 0 for name in pop_by_name}
        for row in PERSONAS:
            for pop_name in row["pops"]:
                population = pop_by_name[pop_name]
                session.add(
                    PopulationMember(
                        population_id=population.id,
                        persona_id=row["id"],
                        name=row["name"],
                        initials=persona_initials(row["name"]),
                        age=row["age"],
                        occ=row["occ"],
                        district=row["district"],
                        trait=row["quote"],
                    )
                )
                member_counts[pop_name] += 1

        bench_pop = pop_by_name.get("Prompt benchmark (full)")
        if bench_pop is not None:
            for row in PERSONAS:
                session.add(
                    PopulationMember(
                        population_id=bench_pop.id,
                        persona_id=row["id"],
                        name=row["name"],
                        initials=persona_initials(row["name"]),
                        age=row["age"],
                        occ=row["occ"],
                        district=row["district"],
                        trait=row["quote"],
                    )
                )
            member_counts["Prompt benchmark (full)"] = len(PERSONAS)

        await session.flush()

        for name, population in pop_by_name.items():
            count = member_counts[name]
            population.size = count
            if isinstance(population.recipe, dict):
                population.recipe = {**population.recipe, "size": count}

        await session.flush()

        for row in RUNS:
            population = pop_by_name[row["population"]]
            session.add(
                Run(
                    name=row["name"],
                    status=row["status"],
                    project_id=project_id,
                    population_id=population.id,
                    seed=row["seed"],
                    start_date=date(2026, 7, 1),
                    main_ticks=row["main_ticks"],
                    branch=row["branch"],
                    oasis_options=row.get("oasis_options") or {},
                    updated_at=_dt(row["updated"]),
                )
            )

        await session.commit()
        print(
            f"Seeded {len(PERSONAS)} personas, {len(POPULATIONS)} populations, "
            f"{len(RUNS)} runs, {len(MESSAGES)} messages, "
            f"configurations/catalog +{config_added}."
        )


async def main() -> None:
    await seed(reset=True)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
