"""Shared helpers for manual OASIS smoke tests."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Population, PopulationMember, Run


def _tick(
    *,
    key: str,
    day: int,
    text: str | None = None,
    silent: bool = False,
) -> dict:
    injections: list[dict] = []
    if text is not None:
        injections.append(
            {
                "key": f"i-{key}",
                "type": "party_post",
                "sender": "Socialdemokraterna",
                "text": text,
                "mode": "text",
                "url": "",
                "fetching": False,
                "sourceDomain": "",
                "isVideo": False,
                "message_id": None,
            }
        )
    return {
        "key": key,
        "day": day,
        "silent": silent,
        "injections": injections,
        "rounds": 1,
        "measurements": [],
        "interviews": [],
    }


async def seed_smoke_run(
    session: AsyncSession,
    *,
    platform: str = "twitter",
) -> Run:
    """Minimal 5-persona, 2-tick, 1-injection körning for live OASIS smoke."""
    districts = ("Centrum", "Norra", "Södra", "Östra", "Västra")
    pop = Population(
        name="Smoke-population",
        size=5,
        versions=1,
        fingerprint=[[100, 0, 0]],
        recipe={"size": 5, "dist": {}, "seed": "smoke"},
    )
    session.add(pop)
    await session.flush()

    for index, district in enumerate(districts):
        session.add(
            PopulationMember(
                population_id=pop.id,
                persona_id=None,
                name=f"Smoke Agent {index + 1}",
                initials=f"S{index + 1}",
                age=30 + index,
                occ="Analytiker",
                district=district,
                trait="nyfiken",
            )
        )

    run = Run(
        name="OASIS smoke harness",
        status="running",
        population_id=pop.id,
        seed="smoke-harness",
        start_date=date(2026, 8, 1),
        main_ticks=[
            _tick(
                key="t1",
                day=1,
                text=(
                    "Trygghet börjar i vardagen — vi investerar i äldreomsorg "
                    "och välfärd nära dig."
                ),
            ),
            _tick(key="t2", day=2, text=None),
        ],
        branch=None,
        oasis_options={
            "platform": platform,
            "allow_population_create_post": False,
        },
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run
