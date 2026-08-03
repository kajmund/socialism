"""Seed SQLite with demo data matching the frontend mock library."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.services.catalog_store import ensure_catalog_defaults
from app.database.models import Persona, Population, PopulationMember, Run
from app.database.session import SessionLocal, engine
from app.serializers import blank_profile, persona_initials


def _dt(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


PERSONAS: list[dict] = [
    {
        "id": "mh",
        "name": "Margareta Hellström",
        "age": 67,
        "occ": "Pensionerad undersköterska",
        "district": "Norra stadsdelen",
        "quote": "Vackra ord räcker inte — jag vill se det i pengar.",
        "origin": "population",
        "updated": "2026-07-24",
        "pops": ["Baslinjepopulation", "Kärnväljare"],
    },
    {
        "id": "hy",
        "name": "Hassan Youssef",
        "age": 29,
        "occ": "Lagerarbetare",
        "district": "Ytterområdet",
        "quote": "Ingen har frågat oss vad vi faktiskt tycker.",
        "origin": "population",
        "updated": "2026-07-23",
        "pops": ["Svängväljartest"],
    },
    {
        "id": "el",
        "name": "Eva Lindqvist",
        "age": 41,
        "occ": "Grundskollärare",
        "district": "Villaområdet",
        "quote": "Jag orkar inte med fler tomma vallöften om skolan.",
        "origin": "beskrivning",
        "updated": "2026-07-22",
        "pops": [],
    },
    {
        "id": "bk",
        "name": "Bengt Karlsson",
        "age": 58,
        "occ": "Taxichaufför",
        "district": "Innerstaden",
        "quote": "Säg vad det kostar, inte bara vad det ger.",
        "origin": "manuell",
        "updated": "2026-07-20",
        "pops": ["Baslinjepopulation"],
    },
    {
        "id": "fa",
        "name": "Fatima Al-Amin",
        "age": 34,
        "occ": "Barnmorska",
        "district": "Söderområdet",
        "quote": "Ett datum. Ett faktiskt startdatum — inte luddigt.",
        "origin": "demografi",
        "updated": "2026-07-19",
        "pops": ["Kärnväljare", "Svängväljartest", "Mediefokusgrupp"],
        "profile": {
            "name": "Fatima Al-Amin",
            "initials": "FA",
            "age": "34",
            "ort": "Klockaretorpet",
            "yrke": "Barnmorska, Vrinnevisjukhuset",
            "utbildning": "Högskola, vårdvetenskap",
            "livssituation": "Sambo, två barn",
            "lutning": "Vänster, stark",
            "sakfragor": "Vård, bostäder, skola",
            "fortroende": "Lågt (kommun) / Högt (vård)",
            "ton": "Direkt, otålig med floskler",
            "sprak": "Kort, konkret, fackspråk",
            "medievanor": "Instagram, FB-grupper",
            "parti": "Vänsterpartiet",
            "valdeltagande": "Röstar alltid",
        },
    },
    {
        "id": "sa",
        "name": "Sven Andersson",
        "age": 72,
        "occ": "Pensionär, f.d. verkstadsarbetare",
        "district": "Norra stadsdelen",
        "quote": "Förr höll man vad man lovade. Nu är allt floskler.",
        "origin": "population",
        "updated": "2026-07-18",
        "pops": ["Baslinjepopulation"],
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
        "pops": [],
    },
    {
        "id": "mn",
        "name": "Mikael Nilsson",
        "age": 46,
        "occ": "Egen företagare, bygg",
        "district": "Villaområdet",
        "quote": "Regelkrångel tar mer tid än själva jobbet.",
        "origin": "manuell",
        "updated": "2026-07-16",
        "pops": ["Svängväljartest"],
    },
    {
        "id": "yk",
        "name": "Yasmin Karlsson",
        "age": 19,
        "occ": "Studerande",
        "district": "Innerstaden",
        "quote": "Ingen av kandidaterna pratar om något jag känner igen mig i.",
        "origin": "demografi",
        "updated": "2026-07-14",
        "pops": [],
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
        "pops": ["Mediefokusgrupp"],
    },
    {
        "id": "kn",
        "name": "Karin Nilsson",
        "age": 38,
        "occ": "Butiksbiträde",
        "district": "Ytterområdet",
        "quote": "Jag röstar på den som pratar om min vardag, inte visioner.",
        "origin": "manuell",
        "updated": "2026-07-08",
        "pops": [],
    },
    {
        "id": "ib",
        "name": "Ingrid Berg",
        "age": 64,
        "occ": "Fd. sjuksköterska",
        "district": "Söderområdet",
        "quote": "Trygghet på äldre dar — visa mig vad det betyder i praktiken.",
        "origin": "population",
        "updated": "2026-07-03",
        "pops": ["Kärnväljare"],
    },
]

POPULATIONS: list[dict] = [
    {
        "name": "Baslinjepopulation",
        "size": 20,
        "versions": 1,
        "updated": "2026-07-24",
        "fp": [[35, 40, 25], [22, 38, 40], [30, 45, 25]],
    },
    {
        "name": "Svängväljartest",
        "size": 14,
        "versions": 2,
        "updated": "2026-07-21",
        "fp": [[45, 35, 20], [40, 30, 30], [20, 50, 30]],
    },
    {
        "name": "Stresstest opposition",
        "size": 18,
        "versions": 1,
        "updated": "2026-07-19",
        "fp": [[20, 50, 30], [55, 25, 20], [35, 35, 30]],
    },
    {
        "name": "Ung urban",
        "size": 12,
        "versions": 1,
        "updated": "2026-07-18",
        "fp": [[70, 22, 8], [30, 40, 30], [50, 30, 20]],
    },
    {
        "name": "Kärnväljare",
        "size": 24,
        "versions": 3,
        "updated": "2026-07-15",
        "fp": [[15, 45, 40], [60, 25, 15], [25, 40, 35]],
    },
    {
        "name": "Pilotgrupp",
        "size": 10,
        "versions": 1,
        "updated": "2026-07-12",
        "fp": [[33, 34, 33], [33, 34, 33], [33, 34, 33]],
    },
    {
        "name": "Mediefokusgrupp",
        "size": 16,
        "versions": 1,
        "updated": "2026-07-10",
        "fp": [[25, 55, 20], [30, 45, 25], [40, 30, 30]],
    },
    {
        "name": "Referensgrupp B",
        "size": 20,
        "versions": 1,
        "updated": "2026-07-05",
        "fp": [[30, 40, 30], [35, 35, 30], [34, 33, 33]],
    },
    {
        "name": "Utkast — ej klar",
        "size": 6,
        "versions": 1,
        "updated": "2026-07-02",
        "fp": [[50, 30, 20], [45, 35, 20], [30, 40, 30]],
    },
]

RUNS: list[dict] = [
    {
        "name": "Trygghetsbudskap — huvudtest",
        "status": "done",
        "population": "Kärnväljare",
        "seed": "7f3a1c9d",
        "updated": "2026-07-24",
        "main_ticks": [
            {
                "key": "t1",
                "day": 1,
                "silent": False,
                "injections": [
                    {
                        "key": "i1",
                        "type": "party_post",
                        "sender": "Socialdemokraterna",
                        "text": "Trygghet börjar i vardagen.",
                        "mode": "text",
                        "url": "",
                        "fetching": False,
                        "sourceDomain": "",
                        "isVideo": False,
                    }
                ],
                "rounds": 2,
                "measurements": ["opinion_snapshot"],
            }
        ],
        "branch": {
            "afterIndex": 0,
            "a": [
                {
                    "key": "ta1",
                    "day": 2,
                    "silent": False,
                    "injections": [],
                    "rounds": 1,
                    "measurements": ["sentiment_baseline"],
                }
            ],
            "b": [
                {
                    "key": "tb1",
                    "day": 2,
                    "silent": False,
                    "injections": [],
                    "rounds": 1,
                    "measurements": ["sentiment_baseline"],
                }
            ],
        },
    },
    {
        "name": "Kort vs. långt format",
        "status": "done",
        "population": "Svängväljartest",
        "seed": "b2e08a41",
        "updated": "2026-07-22",
        "main_ticks": [
            {
                "key": "t2",
                "day": 1,
                "silent": False,
                "injections": [],
                "rounds": 1,
                "measurements": ["opinion_snapshot"],
            }
        ],
        "branch": {
            "afterIndex": 0,
            "a": [{"key": "ta2", "day": 2, "silent": False, "injections": [], "rounds": 1, "measurements": []}],
            "b": [{"key": "tb2", "day": 2, "silent": False, "injections": [], "rounds": 1, "measurements": []}],
        },
    },
    {
        "name": "Baslinje — enkel injektion",
        "status": "done",
        "population": "Baslinjepopulation",
        "seed": "1d9c3f77",
        "updated": "2026-07-19",
        "main_ticks": [
            {
                "key": "t3",
                "day": 1,
                "silent": False,
                "injections": [],
                "rounds": 1,
                "measurements": ["opinion_snapshot"],
            }
        ],
        "branch": None,
    },
    {
        "name": "Reklampost — pilot",
        "status": "running",
        "population": "Mediefokusgrupp",
        "seed": "5a0e2b6c",
        "updated": "2026-07-26",
        "main_ticks": [
            {
                "key": "t4",
                "day": 1,
                "silent": False,
                "injections": [],
                "rounds": 1,
                "measurements": ["engagement_decay"],
            }
        ],
        "branch": None,
    },
    {
        "name": "Ton A/B — uppföljning",
        "status": "draft",
        "population": "Kärnväljare",
        "seed": "c48f119e",
        "updated": "2026-07-15",
        "main_ticks": [
            {
                "key": "t5",
                "day": 1,
                "silent": False,
                "injections": [],
                "rounds": 1,
                "measurements": ["opinion_snapshot"],
            }
        ],
        "branch": {
            "afterIndex": 0,
            "a": [],
            "b": [],
        },
    },
    {
        "name": "Stresstest — snabb sekvens",
        "status": "draft",
        "population": "Baslinjepopulation",
        "seed": "90ad4d23",
        "updated": "2026-07-11",
        "main_ticks": [
            {
                "key": "t6",
                "day": 1,
                "silent": False,
                "injections": [],
                "rounds": 1,
                "measurements": [],
            }
        ],
        "branch": None,
    },
]


def _ensure_data_dir() -> None:
    # Relative sqlite paths resolve from CWD (backend/).
    Path("data").mkdir(parents=True, exist_ok=True)


async def seed(*, reset: bool = True) -> None:
    _ensure_data_dir()
    async with SessionLocal() as session:
        catalog_added = await ensure_catalog_defaults(session)

        if reset:
            await session.execute(delete(Run))
            await session.execute(delete(PopulationMember))
            await session.execute(delete(Population))
            await session.execute(delete(Persona))
            await session.commit()

        existing = await session.execute(select(Persona).limit(1))
        if existing.scalar_one_or_none() is not None:
            print(
                "Database already has data; pass reset=True to wipe and reseed."
                + (f" Catalog: +{catalog_added} lists." if catalog_added else "")
            )
            return

        for row in PERSONAS:
            profile = row.get("profile")
            if profile is None:
                base = blank_profile(row["name"]).model_dump()
                base.update(
                    {
                        "initials": persona_initials(row["name"]),
                        "age": str(row["age"]),
                        "ort": row["district"],
                        "yrke": row["occ"],
                    }
                )
                profile = base
            session.add(
                Persona(
                    id=row["id"],
                    name=row["name"],
                    age=row["age"],
                    occ=row["occ"],
                    district=row["district"],
                    quote=row["quote"],
                    origin=row["origin"],
                    profile=profile,
                    updated_at=_dt(row["updated"]),
                )
            )
        await session.flush()

        pop_by_name: dict[str, Population] = {}
        for row in POPULATIONS:
            population = Population(
                name=row["name"],
                size=row["size"],
                versions=row["versions"],
                fingerprint=row["fp"],
                recipe={},
                updated_at=_dt(row["updated"]),
            )
            session.add(population)
            await session.flush()
            pop_by_name[population.name] = population

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

        await session.flush()

        for row in RUNS:
            population = pop_by_name[row["population"]]
            session.add(
                Run(
                    name=row["name"],
                    status=row["status"],
                    population_id=population.id,
                    seed=row["seed"],
                    start_date=date(2026, 7, 1),
                    main_ticks=row["main_ticks"],
                    branch=row["branch"],
                    updated_at=_dt(row["updated"]),
                )
            )

        await session.commit()
        print(
            f"Seeded {len(PERSONAS)} personas, {len(POPULATIONS)} populations, "
            f"{len(RUNS)} runs, catalog +{catalog_added} lists."
        )


async def main() -> None:
    await seed(reset=True)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
