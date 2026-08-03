"""Run a capped OASIS Twitter simulation for a körning.

Requires optional dependency group: `uv sync --extra oasis`.
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import Population, PopulationMember, Run
from app.database.session import SessionLocal
from app.schemas.domain import Injection, Tick
from app.serializers import utcnow
from app.services.district_context import format_area_block, list_district_contexts
from app.services.oasis_profiles import (
    build_run_profiles,
    injection_has_content,
    injector_key,
    write_twitter_profile_csv,
)

ARTIFACT_ROOT = Path("data/oasis")


class OasisUnavailable(RuntimeError):
    """Raised when camel-oasis is not installed or config is incomplete."""


def oasis_installed() -> bool:
    try:
        import oasis  # noqa: F401
    except ImportError:
        return False
    return True


def _artifact_dir(run_id: int) -> Path:
    path = ARTIFACT_ROOT / f"run_{run_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _injection_body(injection: Injection) -> str:
    """Post body only — author is the institutional injector account."""
    if injection.mode == "link" and injection.url.strip():
        body = injection.text.strip() or injection.sourceDomain.strip() or injection.url
        return f"{body}\n{injection.url.strip()}".strip()
    return injection.text.strip()


def _read_oasis_results(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"posts": [], "comments": []}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        posts = [
            dict(row)
            for row in conn.execute(
                "SELECT post_id, user_id, original_post_id, content, "
                "quote_content, num_likes, num_dislikes, num_shares, "
                "created_at FROM post ORDER BY post_id"
            )
        ]
        comments: list[dict[str, Any]] = []
        try:
            comments = [
                dict(row)
                for row in conn.execute(
                    "SELECT comment_id, post_id, user_id, content, "
                    "num_likes, num_dislikes, created_at FROM comment "
                    "ORDER BY comment_id"
                )
            ]
        except sqlite3.OperationalError:
            comments = []
    finally:
        conn.close()
    return {"posts": posts, "comments": comments}


async def run_oasis_simulation(
    *,
    run_id: int,
    members: list[PopulationMember],
    main_ticks: list[Tick],
    seed: str,
    area_blocks: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not oasis_installed():
        raise OasisUnavailable(
            "camel-oasis is not installed. Run: uv sync --extra oasis"
        )
    if not settings.deepseek_api_key:
        raise OasisUnavailable("DEEPSEEK_API_KEY is required for OASIS simulation")

    settings.apply_oasis_env()

    # Deferred: camel-oasis is an optional extra and may not be installed.
    import oasis
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType
    from oasis import ActionType, LLMAction, ManualAction, generate_twitter_agent_graph

    ticks = [t for t in main_ticks if not t.silent][: settings.oasis_max_ticks]
    profiles, key_to_index = build_run_profiles(
        members,
        ticks,
        max_agents=settings.oasis_max_agents,
        area_blocks=area_blocks,
    )
    population_indices = {i for i, p in enumerate(profiles) if p.role == "population"}
    if not population_indices:
        raise OasisUnavailable("Population has no members to simulate")

    art = _artifact_dir(run_id)
    profile_csv = write_twitter_profile_csv(profiles, art / "profiles.csv")
    db_path = art / "simulation.db"
    if db_path.exists():
        db_path.unlink()

    model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=settings.deepseek_model,
        url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
    )

    # Population reacts — no CREATE_POST (avoids copy-paste of injections as "egna" inlägg).
    available_actions = [
        ActionType.LIKE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.REPOST,
        ActionType.QUOTE_POST,
        ActionType.FOLLOW,
        ActionType.DO_NOTHING,
        ActionType.REFRESH,
    ]

    agent_graph = await generate_twitter_agent_graph(
        profile_path=str(profile_csv),
        model=model,
        available_actions=available_actions,
    )

    env = oasis.make(
        agent_graph=agent_graph,
        platform=oasis.DefaultPlatformType.TWITTER,
        database_path=str(db_path),
    )

    ticks_run = 0

    try:
        await env.reset()

        for tick in ticks:
            inject_actions: dict[Any, list[Any]] = {}
            for injection in tick.injections:
                if not injection_has_content(injection):
                    continue
                content = _injection_body(injection)
                if not content:
                    continue
                idx = key_to_index.get(injector_key(injection))
                if idx is None:
                    continue
                agent = env.agent_graph.get_agent(idx)
                inject_actions.setdefault(agent, []).append(
                    ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": content},
                    )
                )
            if inject_actions:
                await env.step(inject_actions)

            rounds = max(1, tick.rounds)
            for _ in range(rounds):
                llm_actions = {
                    agent: LLMAction()
                    for agent_id, agent in env.agent_graph.get_agents()
                    if agent_id in population_indices
                }
                if llm_actions:
                    await env.step(llm_actions)
            ticks_run += 1
    finally:
        await env.close()

    feed = _read_oasis_results(db_path)
    return {
        "engine": "oasis",
        "seed": seed,
        "agents": [
            {
                "index": i,
                "username": p.username,
                "member_name": p.member_name,
                "persona_id": p.persona_id,
                "role": p.role,
            }
            for i, p in enumerate(profiles)
        ],
        "ticks_run": ticks_run,
        "max_agents": settings.oasis_max_agents,
        "max_ticks": settings.oasis_max_ticks,
        "posts": feed["posts"],
        "comments": feed["comments"],
        "artifact_db": str(db_path),
        "profile_csv": str(profile_csv),
    }


async def simulate_run(session: AsyncSession, run: Run) -> dict[str, Any]:
    """Load population members and execute OASIS for this run."""
    result = await session.execute(
        select(Population)
        .options(
            selectinload(Population.members).selectinload(PopulationMember.persona)
        )
        .where(Population.id == run.population_id)
    )
    population = result.scalar_one()
    ticks = [Tick.model_validate(t) for t in (run.main_ticks or [])]
    districts = await list_district_contexts(session)
    centrum = next((d for d in districts if d.label.casefold() == "centrum"), None)
    area_blocks = {
        d.label: format_area_block(d, centrum=centrum) for d in districts
    }
    return await run_oasis_simulation(
        run_id=run.id,
        members=list(population.members),
        main_ticks=ticks,
        seed=run.seed,
        area_blocks=area_blocks,
    )


async def _cli_main(run_id: int) -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Run)
            .options(selectinload(Run.population))
            .where(Run.id == run_id)
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise SystemExit(f"Run {run_id} not found")
        run.status = "running"
        run.updated_at = utcnow()
        await session.commit()
        try:
            results = await simulate_run(session, run)
            run.status = "done"
            run.results = results
        except Exception as exc:
            run.status = "failed"
            run.results = {"engine": "oasis", "error": str(exc)}
            raise
        finally:
            run.updated_at = utcnow()
            await session.commit()
        print(f"Run {run_id} → {run.status}; posts={len((run.results or {}).get('posts', []))}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OASIS spike for a körning")
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(_cli_main(args.run_id))


if __name__ == "__main__":
    main()
