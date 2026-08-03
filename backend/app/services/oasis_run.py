"""Run a capped OASIS Twitter simulation for a körning.

Requires optional dependency group: `uv sync --extra oasis`.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import Population, PopulationMember, Run
from app.database.session import SessionLocal
from app.schemas.domain import Injection, OasisRunOptions, Tick
from app.serializers import utcnow
from app.services.district_context import format_area_block, list_district_contexts
from app.services.oasis_profiles import (
    build_run_profiles,
    injection_has_content,
    injector_key,
    write_twitter_profile_csv,
)
from app.services.oasis_swedish import apply_swedish_social_environment_prompts
from app.services.run_measurements import build_measurements

ARTIFACT_ROOT = Path("data/oasis")

# Twitter population actions as names (no camel-oasis import required for tests).
_BASE_POPULATION_ACTIONS: tuple[str, ...] = (
    "LIKE_POST",
    "DISLIKE_POST",
    "UNLIKE_POST",
    "UNDO_DISLIKE_POST",
    "CREATE_COMMENT",
    "LIKE_COMMENT",
    "DISLIKE_COMMENT",
    "UNLIKE_COMMENT",
    "UNDO_DISLIKE_COMMENT",
    "REPOST",
    "QUOTE_POST",
    "FOLLOW",
    "UNFOLLOW",
    "MUTE",
    "UNMUTE",
    "SEARCH_USER",
    "SEARCH_POSTS",
    "REPORT_POST",
    "TREND",
    "DO_NOTHING",
    "REFRESH",
)


class OasisUnavailable(RuntimeError):
    """Raised when camel-oasis is not installed or config is incomplete."""


def oasis_installed() -> bool:
    try:
        import oasis  # noqa: F401
    except ImportError:
        return False
    return True


def parse_oasis_options(raw: dict | None) -> OasisRunOptions:
    return OasisRunOptions.model_validate(raw or {})


def population_action_names(*, allow_population_create_post: bool = False) -> list[str]:
    """Return ActionType names available to population agents."""
    names = list(_BASE_POPULATION_ACTIONS)
    if allow_population_create_post:
        names.insert(0, "CREATE_POST")
    return names


def _artifact_dir(run_id: int, variant_id: str = "main") -> Path:
    path = ARTIFACT_ROOT / f"run_{run_id}" / variant_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_ticks(raw: list | None) -> list[Tick]:
    return [Tick.model_validate(t) for t in (raw or [])]


def variant_plans(run: Run) -> list[tuple[str, str, list[Tick]]]:
    """Return (variant_id, label, ticks) for each simulation to run.

    Without a branch: one plan over main_ticks.
    With a branch: Version A and B, each = stem (through afterIndex) + branch ticks.
    """
    main = _parse_ticks(run.main_ticks)
    branch = run.branch
    if not branch:
        return [("main", "Huvudtidslinje", main)]

    if isinstance(branch, dict):
        after = int(branch.get("afterIndex") or 0)
        a_raw = branch.get("a") or []
        b_raw = branch.get("b") or []
    else:
        after = branch.afterIndex
        a_raw = branch.a
        b_raw = branch.b

    stem = main[: max(0, after + 1)]
    return [
        ("a", "Version A", stem + _parse_ticks(a_raw)),
        ("b", "Version B", stem + _parse_ticks(b_raw)),
    ]


def previous_attempts(results: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize stored results into an attempts list (newest first)."""
    if not results:
        return []
    attempts = results.get("attempts")
    if isinstance(attempts, list):
        return [a for a in attempts if isinstance(a, dict)]

    if isinstance(results.get("variants"), list):
        return [
            {
                "id": "legacy",
                "finished_at": None,
                "seed": results.get("seed"),
                "engine": results.get("engine"),
                "variants": results["variants"],
                "error": results.get("error"),
            }
        ]

    if (
        results.get("posts") is not None
        or results.get("comments") is not None
        or results.get("error")
        or results.get("agents") is not None
    ):
        return [
            {
                "id": "legacy",
                "finished_at": None,
                "seed": results.get("seed"),
                "engine": results.get("engine"),
                "error": results.get("error"),
                "variants": [
                    {
                        "id": "main",
                        "label": "Huvudtidslinje",
                        "error": results.get("error"),
                        "ticks_run": results.get("ticks_run"),
                        "agents": results.get("agents") or [],
                        "posts": results.get("posts") or [],
                        "comments": results.get("comments") or [],
                        "artifact_db": results.get("artifact_db"),
                        "profile_csv": results.get("profile_csv"),
                    }
                ],
            }
        ]
    return []


def _injection_body(injection: Injection) -> str:
    """Post body only — author is the institutional injector account."""
    if injection.mode == "link" and injection.url.strip():
        body = injection.text.strip() or injection.sourceDomain.strip() or injection.url
        return f"{body}\n{injection.url.strip()}".strip()
    return injection.text.strip()


def _table_rows(
    conn: sqlite3.Connection, sql: str
) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in conn.execute(sql)]
    except sqlite3.OperationalError:
        return []


def _action_histogram(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in trace:
        action = str(row.get("action") or "").strip()
        if action:
            counts[action] += 1
    return [{"action": a, "count": c} for a, c in counts.most_common()]


def _read_oasis_results(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "posts": [],
            "comments": [],
            "follows": [],
            "mutes": [],
            "reports": [],
            "trace": [],
            "action_histogram": [],
        }
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        posts = _table_rows(
            conn,
            "SELECT post_id, user_id, original_post_id, content, "
            "quote_content, num_likes, num_dislikes, num_shares, "
            "created_at FROM post ORDER BY post_id",
        )
        comments = _table_rows(
            conn,
            "SELECT comment_id, post_id, user_id, content, "
            "num_likes, num_dislikes, created_at FROM comment "
            "ORDER BY comment_id",
        )

        likes_by_post: dict[int, list[int]] = {}
        for row in _table_rows(
            conn, "SELECT user_id, post_id FROM like ORDER BY like_id"
        ):
            likes_by_post.setdefault(int(row["post_id"]), []).append(
                int(row["user_id"])
            )

        dislikes_by_post: dict[int, list[int]] = {}
        for row in _table_rows(
            conn, "SELECT user_id, post_id FROM dislike ORDER BY dislike_id"
        ):
            dislikes_by_post.setdefault(int(row["post_id"]), []).append(
                int(row["user_id"])
            )

        comment_likes_by_id: dict[int, list[int]] = {}
        for row in _table_rows(
            conn,
            "SELECT user_id, comment_id FROM comment_like "
            "ORDER BY comment_like_id",
        ):
            comment_likes_by_id.setdefault(int(row["comment_id"]), []).append(
                int(row["user_id"])
            )

        comment_dislikes_by_id: dict[int, list[int]] = {}
        for row in _table_rows(
            conn,
            "SELECT user_id, comment_id FROM comment_dislike "
            "ORDER BY comment_dislike_id",
        ):
            comment_dislikes_by_id.setdefault(
                int(row["comment_id"]), []
            ).append(int(row["user_id"]))

        # Shares = reposts + quotes (rows that point at an original post).
        shares_by_post: dict[int, list[dict[str, Any]]] = {}
        for post in posts:
            original_id = post.get("original_post_id")
            if original_id is None:
                continue
            quote = (post.get("quote_content") or "").strip()
            shares_by_post.setdefault(int(original_id), []).append(
                {
                    "user_id": int(post["user_id"]),
                    "kind": "quote" if quote else "repost",
                    "share_post_id": int(post["post_id"]),
                }
            )

        for post in posts:
            pid = int(post["post_id"])
            post["liked_by"] = likes_by_post.get(pid, [])
            post["disliked_by"] = dislikes_by_post.get(pid, [])
            post["shared_by"] = shares_by_post.get(pid, [])

        for comment in comments:
            cid = int(comment["comment_id"])
            comment["liked_by"] = comment_likes_by_id.get(cid, [])
            comment["disliked_by"] = comment_dislikes_by_id.get(cid, [])

        follows = _table_rows(
            conn,
            "SELECT follow_id, follower_id, followee_id, created_at FROM follow "
            "ORDER BY follow_id",
        )
        mutes = _table_rows(
            conn,
            "SELECT mute_id, muter_id, mutee_id, created_at FROM mute "
            "ORDER BY mute_id",
        )
        reports = _table_rows(
            conn,
            "SELECT report_id, user_id, post_id, report_reason, created_at "
            "FROM report ORDER BY report_id",
        )
        trace = _table_rows(
            conn,
            "SELECT user_id, created_at, action, info FROM trace "
            "ORDER BY created_at, user_id",
        )
    finally:
        conn.close()
    return {
        "posts": posts,
        "comments": comments,
        "follows": follows,
        "mutes": mutes,
        "reports": reports,
        "trace": trace,
        "action_histogram": _action_histogram(trace),
    }

async def run_oasis_simulation(
    *,
    run_id: int,
    members: list[PopulationMember],
    ticks: list[Tick],
    seed: str,
    variant_id: str = "main",
    area_blocks: dict[str, str] | None = None,
    oasis_options: OasisRunOptions | None = None,
) -> dict[str, Any]:
    if not oasis_installed():
        raise OasisUnavailable(
            "camel-oasis is not installed. Run: uv sync --extra oasis"
        )
    if not settings.deepseek_api_key:
        raise OasisUnavailable("DEEPSEEK_API_KEY is required for OASIS simulation")

    options = oasis_options or OasisRunOptions()
    allow_create = options.allow_population_create_post
    settings.apply_oasis_env()

    # Deferred: camel-oasis is an optional extra and may not be installed.
    import oasis
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType
    from oasis import ActionType, LLMAction, ManualAction, generate_twitter_agent_graph

    apply_swedish_social_environment_prompts()
    # All configured ticks run: silent = no injection that day, population still reacts.
    active_ticks = list(ticks)
    profiles, key_to_index = build_run_profiles(
        members,
        active_ticks,
        area_blocks=area_blocks,
        allow_create_post=allow_create,
    )
    population_indices = {i for i, p in enumerate(profiles) if p.role == "population"}
    if not population_indices:
        raise OasisUnavailable("Population has no members to simulate")

    art = _artifact_dir(run_id, variant_id)
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

    available_actions = [
        ActionType[name]
        for name in population_action_names(
            allow_population_create_post=allow_create
        )
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

        for tick in active_ticks:
            if not tick.silent:
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
        "agent_count": len(profiles),
        "configured_ticks": len(active_ticks),
        "posts": feed["posts"],
        "comments": feed["comments"],
        "follows": feed["follows"],
        "mutes": feed["mutes"],
        "reports": feed["reports"],
        "trace": feed["trace"],
        "action_histogram": feed["action_histogram"],
        "artifact_db": str(db_path),
        "profile_csv": str(profile_csv),
        "oasis_options": options.model_dump(),
    }


def build_empty_attempt(
    run: Run, *, engine: str, error: str | None = None
) -> dict[str, Any]:
    plans = variant_plans(run)
    return {
        "id": f"att_{secrets.token_hex(4)}",
        "finished_at": utcnow().isoformat(),
        "seed": run.seed,
        "engine": engine,
        "error": error,
        "variants": [
            {
                "id": vid,
                "label": label,
                "error": error,
                "ticks_run": 0,
                "agents": [],
                "posts": [],
                "comments": [],
                "measurements": build_measurements(ticks, ticks_run=0),
            }
            for vid, label, ticks in plans
        ],
    }


def merge_attempt(
    previous: dict[str, Any] | None,
    attempt: dict[str, Any],
    *,
    engine: str,
) -> dict[str, Any]:
    return {
        "engine": engine,
        "seed": attempt.get("seed"),
        "attempts": [attempt, *previous_attempts(previous)],
    }


def attempt_all_failed(attempt: dict[str, Any]) -> bool:
    variants = attempt.get("variants") or []
    if not variants:
        return bool(attempt.get("error"))
    return all(v.get("error") for v in variants)


def remove_attempt(
    results: dict[str, Any] | None, attempt_id: str
) -> dict[str, Any] | None:
    """Drop one attempt from stored results. Returns None if none remain."""
    attempts = previous_attempts(results)
    remaining = [a for a in attempts if str(a.get("id")) != attempt_id]
    if len(remaining) == len(attempts):
        raise KeyError(attempt_id)
    if not remaining:
        return None
    engine = remaining[0].get("engine") or (results or {}).get("engine") or "oasis"
    return {
        "engine": engine,
        "seed": remaining[0].get("seed") or (results or {}).get("seed"),
        "attempts": remaining,
    }


async def simulate_run(session: AsyncSession, run: Run) -> dict[str, Any]:
    """Load population members and execute OASIS for each variant (main or A/B)."""
    result = await session.execute(
        select(Population)
        .options(
            selectinload(Population.members).selectinload(PopulationMember.persona)
        )
        .where(Population.id == run.population_id)
    )
    population = result.scalar_one()
    districts = await list_district_contexts(session)
    centrum = next((d for d in districts if d.label.casefold() == "centrum"), None)
    area_blocks = {
        d.label: format_area_block(d, centrum=centrum) for d in districts
    }

    members = list(population.members)
    member_districts: dict[str, str] = {}
    for member in members:
        if member.persona_id:
            member_districts[member.persona_id] = member.district
        if member.name:
            member_districts[member.name] = member.district

    options = parse_oasis_options(
        run.oasis_options if isinstance(run.oasis_options, dict) else None
    )
    plans = variant_plans(run)
    variants_out: list[dict[str, Any]] = []

    for variant_id, label, ticks in plans:
        try:
            sim = await run_oasis_simulation(
                run_id=run.id,
                members=members,
                ticks=ticks,
                seed=run.seed,
                variant_id=variant_id,
                area_blocks=area_blocks,
                oasis_options=options,
            )
            agents = sim.get("agents") or []
            posts = sim.get("posts") or []
            comments = sim.get("comments") or []
            follows = sim.get("follows") or []
            mutes = sim.get("mutes") or []
            reports = sim.get("reports") or []
            trace = sim.get("trace") or []
            action_histogram = sim.get("action_histogram") or []
            ticks_run = int(sim.get("ticks_run") or 0)
            variants_out.append(
                {
                    "id": variant_id,
                    "label": label,
                    "error": None,
                    "ticks_run": ticks_run,
                    "agents": agents,
                    "posts": posts,
                    "comments": comments,
                    "follows": follows,
                    "mutes": mutes,
                    "reports": reports,
                    "trace": trace,
                    "action_histogram": action_histogram,
                    "artifact_db": sim.get("artifact_db"),
                    "profile_csv": sim.get("profile_csv"),
                    "agent_count": sim.get("agent_count"),
                    "configured_ticks": sim.get("configured_ticks"),
                    "oasis_options": sim.get("oasis_options"),
                    "measurements": build_measurements(
                        ticks,
                        posts=posts,
                        comments=comments,
                        agents=agents,
                        follows=follows,
                        member_districts=member_districts,
                        ticks_run=ticks_run,
                    ),
                }
            )
        except OasisUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — keep other variants; record this failure
            variants_out.append(
                {
                    "id": variant_id,
                    "label": label,
                    "error": str(exc) or exc.__class__.__name__,
                    "ticks_run": 0,
                    "agents": [],
                    "posts": [],
                    "comments": [],
                    "follows": [],
                    "mutes": [],
                    "reports": [],
                    "trace": [],
                    "action_histogram": [],
                    "measurements": build_measurements(ticks, ticks_run=0),
                }
            )

    all_failed = bool(variants_out) and all(v.get("error") for v in variants_out)
    attempt = {
        "id": f"att_{secrets.token_hex(4)}",
        "finished_at": utcnow().isoformat(),
        "seed": run.seed,
        "engine": "oasis",
        "error": "Alla varianter misslyckades" if all_failed else None,
        "variants": variants_out,
    }
    prev = run.results if isinstance(run.results, dict) else None
    return merge_attempt(prev, attempt, engine="oasis")


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
            attempts = results.get("attempts") or []
            latest = attempts[0] if attempts else {}
            run.status = "failed" if attempt_all_failed(latest) else "done"
            run.results = results
        except Exception as exc:
            attempt = build_empty_attempt(run, engine="oasis", error=str(exc))
            run.status = "failed"
            run.results = merge_attempt(
                run.results if isinstance(run.results, dict) else None,
                attempt,
                engine="oasis",
            )
            raise
        finally:
            run.updated_at = utcnow()
            await session.commit()
        latest = (run.results or {}).get("attempts", [{}])[0]
        posts = sum(len(v.get("posts") or []) for v in (latest.get("variants") or []))
        print(f"Run {run_id} → {run.status}; posts={posts}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OASIS spike for a körning")
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(_cli_main(args.run_id))


if __name__ == "__main__":
    main()
