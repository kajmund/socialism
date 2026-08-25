"""Run an OASIS Twitter or Reddit simulation for a körning.

Requires optional dependency group: `uv sync --extra oasis`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import secrets
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import Population, PopulationMember, Run
from app.database.session import SessionLocal
from app.schemas.domain import Injection, OasisPlatform, OasisRunOptions, Tick
from app.serializers import utcnow
from app.services.district_context import format_area_block, list_district_contexts
from app.services.lexical_convergence import analyze_lexical_convergence
from app.services.oasis_agent_tools import apply_population_agent_tools
from app.services.oasis_engagement import (
    StimulusEngagement,
    build_agent_strata_from_members,
    comment_ids_from_trace,
    comment_post_ids,
    injector_post_ids_after,
    make_round_rng,
    max_post_id as _engagement_max_post_id,
    read_trace_since,
    sample_fraction,
    stratified_agent_sample,
    trace_row_count,
)
from app.services.oasis_clock import OasisScenarioClock
from app.services.oasis_profiles import (
    build_run_profiles,
    injection_body,
    injection_has_content,
    injector_key,
)
from app.services.simulation.platforms import get_platform_driver
from app.services.oasis_swedish import (
    apply_swedish_social_environment_prompts,
    set_oasis_user_display_names,
)
from app.services.oasis_tool_trace import (
    clear_oasis_tool_trace,
    drain_oasis_reasoning_trace,
    drain_oasis_tool_trace,
    set_oasis_tool_trace_tick,
)
from app.services.simulation.agent_tool_policy import CamelCommentToolPolicy
from app.services.simulation.artifact.reader import (
    OasisArtifactReader,
    created_at_to_sort_key,
    read_oasis_results,
)
from app.services.simulation.llm_runtime import camel_llm_runtime
from app.services.run_log import (
    capture_run_log,
    run_attempt_log_dir,
    run_variant_log_path,
    write_run_log_note,
)
from app.services.run_live_progress import reset_live_progress
from app.services.run_trace_enrich import (
    activity_items_from_trace_rows,
    enrich_trace_rows,
)
from app.realtime.run_broadcast import run_broadcast
from app.services.run_measurements import build_measurements
from app.services.simulation.action_catalog import population_action_names

ARTIFACT_ROOT = Path("data/oasis")
DEFAULT_SIMULATION_START = date(2026, 8, 1)


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


def resolve_tick_interviews(
    interviews: list,
    profiles: list,
) -> list[tuple[int, str]]:
    """Map planned TickInterview rows to (agent_index, prompt).

    Skips missing persona_id, empty prompts, and injector agents.
    """
    persona_to_index: dict[str, int] = {}
    for i, profile in enumerate(profiles):
        persona_id = getattr(profile, "persona_id", None)
        role = getattr(profile, "role", "population")
        if persona_id and role == "population":
            persona_to_index[str(persona_id)] = i

    out: list[tuple[int, str]] = []
    for interview in interviews or []:
        persona_id = getattr(interview, "persona_id", None) or (
            interview.get("persona_id") if isinstance(interview, dict) else None
        )
        prompt = getattr(interview, "prompt", None) or (
            interview.get("prompt") if isinstance(interview, dict) else None
        )
        if not persona_id or not prompt:
            continue
        text = str(prompt).strip()
        if not text:
            continue
        idx = persona_to_index.get(str(persona_id))
        if idx is None:
            continue
        out.append((idx, text))
    return out


def _parse_simulation_start(raw: str | None) -> date:
    if raw and raw.strip():
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            pass
    return DEFAULT_SIMULATION_START


def _created_at_to_sort_key(value: Any) -> int | None:
    """Backward-compatible alias — prefer simulation.artifact.created_at_to_sort_key."""
    return created_at_to_sort_key(value)


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
        raw_after = branch.get("afterIndex", 0)
        after = int(raw_after) if raw_after is not None else 0
        a_raw = branch.get("a") or []
        b_raw = branch.get("b") or []
    else:
        after = branch.afterIndex
        a_raw = branch.a
        b_raw = branch.b

    mode = branch.get("mode", "ab") if isinstance(branch, dict) else getattr(branch, "mode", "ab")
    if mode == "stimulus_control":
        label_a, label_b = "Med stimulus", "Kontroll (ingen injektion)"
    else:
        label_a, label_b = "Version A", "Version B"

    stem = main[: max(0, after + 1)]
    return [
        ("a", label_a, stem + _parse_ticks(a_raw)),
        ("b", label_b, stem + _parse_ticks(b_raw)),
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


def _max_event_time(db_path: Path) -> int:
    """Highest created_at seen in OASIS artifact (trace/post), or -1."""
    return OasisArtifactReader(db_path).max_event_time()


def _injection_texts_labeled(ticks: list[Tick]) -> list[tuple[str, str]]:
    """(source_label, body) for non-silent injections — used in convergence analysis."""
    out: list[tuple[str, str]] = []
    for tick in ticks:
        if tick.silent:
            continue
        for injection in tick.injections:
            if not injection_has_content(injection):
                continue
            body = injection_body(injection)
            if body:
                out.append((tick.key, body))
    return out


async def _prepare_injection_content(injection: Injection) -> str:
    return injection_body(injection)


def _read_oasis_results(db_path: Path) -> dict[str, Any]:
    """Backward-compatible alias — prefer OasisArtifactReader.export_variant_payload()."""
    return read_oasis_results(db_path)


async def run_oasis_simulation(
    *,
    run_id: int,
    members: list[PopulationMember],
    ticks: list[Tick],
    seed: str,
    variant_id: str = "main",
    attempt_id: str,
    area_blocks: dict[str, str] | None = None,
    oasis_options: OasisRunOptions | None = None,
    simulation_start: date | None = None,
) -> dict[str, Any]:
    if not oasis_installed():
        raise OasisUnavailable(
            "camel-oasis is not installed. Run: uv sync --extra oasis"
        )
    if not settings.deepseek_api_key:
        raise OasisUnavailable("DEEPSEEK_API_KEY is required for OASIS simulation")

    options = oasis_options or OasisRunOptions()
    allow_create = options.allow_population_create_post
    platform = options.platform
    settings.apply_oasis_env()

    # Deferred: camel-oasis is an optional extra and may not be installed.
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType
    from oasis import ActionType, LLMAction, ManualAction

    from app.services import jobs as jobs_service
    from app.services.prompt_store import (
        MissingActiveConfigurationError,
        get_active_configuration,
        require_active_prompts,
    )

    factory = jobs_service.job_session_factory()
    async with factory() as prompt_session:
        # OASIS simulates Swedish political messaging — active config must be sv.
        active = await get_active_configuration(prompt_session)
        if active is None:
            raise MissingActiveConfigurationError(
                "No active prompt configuration. Activate one under Konfigurationer."
            )
        if active.language != "sv":
            raise MissingActiveConfigurationError(
                f"Active configuration '{active.name}' (id={active.id}) is language "
                f"'{active.language}', but OASIS requires Swedish (sv). "
                "Activate a sv configuration under Konfigurationer."
            )
        prompts = await require_active_prompts(prompt_session)

    apply_swedish_social_environment_prompts(prompts)

    with camel_llm_runtime():
        clear_oasis_tool_trace()
        # All configured ticks run: silent = no injection that day, population still reacts.
        active_ticks = list(ticks)
        profiles, key_to_index = build_run_profiles(
            members,
            active_ticks,
            prompts=prompts,
            area_blocks=area_blocks,
            allow_create_post=allow_create,
            platform=platform,
            oasis_options=options,
        )
        # OASIS feed only exposes user_id; map to member names for correct attribution.
        set_oasis_user_display_names(
            {i: p.member_name for i, p in enumerate(profiles)}
        )
        population_indices = {
            i for i, p in enumerate(profiles) if p.role == "population"
        }
        if not population_indices:
            raise OasisUnavailable("Population has no members to simulate")

        agents_payload = [
            {
                "index": i,
                "username": p.username,
                "member_name": p.member_name,
                "persona_id": p.persona_id,
                "role": p.role,
            }
            for i, p in enumerate(profiles)
        ]
        await run_broadcast.publish(
            (run_id, variant_id),
            {
                "type": "run.attempt_started",
                "attempt_id": attempt_id,
                "agents": agents_payload,
            },
        )

        art = _artifact_dir(run_id, variant_id)
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
                allow_population_create_post=allow_create,
                platform=platform,
            )
        ]

        sim_start = simulation_start or DEFAULT_SIMULATION_START
        driver = get_platform_driver(platform)
        setup = await driver.setup(
            profiles=profiles,
            art=art,
            db_path=db_path,
            model=model,
            available_actions=available_actions,
            sim_start=sim_start,
        )
        env = setup.env
        agent_graph = setup.agent_graph
        scenario_clock = setup.scenario_clock
        profile_path = setup.profile_path
        profile_csv = setup.profile_csv
        profile_json = setup.profile_json

        apply_population_agent_tools(agent_graph, population_indices, options)

        injector_indices = {
            i for i, p in enumerate(profiles) if p.role == "injector"
        }
        agent_strata = build_agent_strata_from_members(members, population_indices)
        engagement = StimulusEngagement()
        comment_policy = CamelCommentToolPolicy()
        comment_policy.register_population_agents(agent_graph, population_indices)

        ticks_run = 0
        tick_markers: list[dict[str, Any]] = []
        prev_end = -1

        try:
            await env.reset()

            for tick_index, tick in enumerate(active_ticks):
                await run_broadcast.publish(
                    (run_id, variant_id),
                    {
                        "type": "tick.started",
                        "run_id": run_id,
                        "variant_id": variant_id,
                        "tick_index": tick_index,
                        "day": tick.day,
                        "silent": tick.silent,
                        "key": tick.key,
                        "rounds": tick.rounds,
                    },
                )
                if scenario_clock is not None:
                    scenario_clock.set_day_index(max(0, tick.day - 1))
                time_start = prev_end + 1
                new_posts: frozenset[int] = frozenset()
                if not tick.silent:
                    max_post_before = _engagement_max_post_id(db_path)
                    inject_actions: dict[Any, list[Any]] = {}
                    for injection in tick.injections:
                        if not injection_has_content(injection):
                            continue
                        content = await _prepare_injection_content(injection)
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
                        new_posts = injector_post_ids_after(
                            db_path,
                            injector_indices=injector_indices,
                            after_post_id=max_post_before,
                        )
                if new_posts:
                    engagement.reset_for_stimulus(new_posts)
                else:
                    engagement.end_gating()

                rounds = max(1, tick.rounds)
                set_oasis_tool_trace_tick(tick_index)
                for round_index in range(rounds):
                    eligible = engagement.eligible_agents(population_indices)
                    selected = stratified_agent_sample(
                        eligible,
                        strata=agent_strata,
                        fraction=sample_fraction(round_index),
                        rng=make_round_rng(seed, tick_index, round_index),
                    )
                    if not selected:
                        continue
                    trace_before = trace_row_count(db_path)
                    llm_actions: dict[Any, Any] = {}
                    for agent_id in selected:
                        agent = env.agent_graph.get_agent(agent_id)
                        comment_policy.set_comment_allowed(
                            agent,
                            agent_id,
                            allowed=engagement.may_comment(agent_id),
                        )
                        llm_actions[agent] = LLMAction()
                    await env.step(llm_actions)
                    new_trace = read_trace_since(db_path, trace_before)
                    comment_map = comment_post_ids(
                        db_path, comment_ids_from_trace(new_trace)
                    )
                    engagement.record_trace_rows(
                        new_trace, comment_to_post=comment_map
                    )
                    trace_after = trace_row_count(db_path)
                    progress_entry = {
                        "tick_index": tick_index,
                        "round_index": round_index,
                        "trace_start": trace_before,
                        "trace_end": trace_after,
                    }
                    factory = jobs_service.job_session_factory()
                    if factory is not None:
                        async with factory() as progress_session:
                            from app.services.run_live_progress import (
                                append_live_progress_entry,
                            )

                            await append_live_progress_entry(
                                progress_session,
                                run_id=run_id,
                                variant_id=variant_id,
                                entry=progress_entry,
                            )
                    enriched = enrich_trace_rows(db_path, new_trace)
                    await run_broadcast.publish(
                        (run_id, variant_id),
                        {
                            "type": "round.activity",
                            "run_id": run_id,
                            "variant_id": variant_id,
                            "tick_index": tick_index,
                            "round_index": round_index,
                            "items": activity_items_from_trace_rows(enriched),
                        },
                    )

                # Planned interviews after reactions — agent has no future-tick context.
                interview_actions: dict[Any, list[Any]] = {}
                for agent_idx, prompt in resolve_tick_interviews(
                    tick.interviews, profiles
                ):
                    agent = env.agent_graph.get_agent(agent_idx)
                    interview_actions.setdefault(agent, []).append(
                        ManualAction(
                            action_type=ActionType.INTERVIEW,
                            action_args={"prompt": prompt},
                        )
                    )
                if interview_actions:
                    await env.step(interview_actions)

                end = _max_event_time(db_path)
                time_end = end if end >= time_start else time_start - 1
                tick_marker = {
                    "tick_index": tick_index,
                    "day": tick.day,
                    "silent": tick.silent,
                    "key": tick.key,
                    "rounds": tick.rounds,
                    "time_start": time_start,
                    "time_end": time_end,
                }
                tick_markers.append(tick_marker)
                await run_broadcast.publish(
                    (run_id, variant_id),
                    {
                        "type": "tick.completed",
                        "run_id": run_id,
                        "variant_id": variant_id,
                        **tick_marker,
                    },
                )
                prev_end = max(prev_end, end)
                ticks_run += 1
        finally:
            await env.close()

        feed = _read_oasis_results(db_path)
        agent_tools = drain_oasis_tool_trace()
        agent_reasoning = drain_oasis_reasoning_trace()
        return {
            "engine": "oasis",
            "seed": seed,
            "platform": platform,
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
            "tick_markers": tick_markers,
            "agent_count": len(profiles),
            "configured_ticks": len(active_ticks),
            "posts": feed["posts"],
            "comments": feed["comments"],
            "follows": feed["follows"],
            "mutes": feed["mutes"],
            "reports": feed["reports"],
            "trace": feed["trace"],
            "action_histogram": feed["action_histogram"],
            "agent_tools": agent_tools,
            "agent_reasoning": agent_reasoning,
            "artifact_db": str(db_path),
            "profile_path": str(profile_path),
            "profile_csv": profile_csv,
            "profile_json": profile_json,
            "oasis_options": options.model_dump(),
        }


def build_empty_attempt(
    run: Run, *, engine: str, error: str | None = None
) -> dict[str, Any]:
    plans = variant_plans(run)
    attempt_id = f"att_{secrets.token_hex(4)}"
    log_dir = run_attempt_log_dir(run.id, attempt_id)
    variants: list[dict[str, Any]] = []
    for vid, label, ticks in plans:
        log_path = run_variant_log_path(run.id, attempt_id, vid)
        note = (
            f"engine={engine}\nvariant={vid}\n"
            + (f"error={error}\n" if error else "status=empty_attempt\n")
        )
        write_run_log_note(log_path, note)
        variants.append(
            {
                "id": vid,
                "label": label,
                "error": error,
                "ticks_run": 0,
                "agents": [],
                "posts": [],
                "comments": [],
                "measurements": build_measurements(ticks, ticks_run=0),
                "log_path": str(log_path),
            }
        )
    return {
        "id": attempt_id,
        "finished_at": utcnow().isoformat(),
        "seed": run.seed,
        "engine": engine,
        "error": error,
        "log_dir": str(log_dir),
        "variants": variants,
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


def _failed_variant(
    *,
    variant_id: str,
    label: str,
    ticks: list[Tick],
    error: str,
    log_path: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": variant_id,
        "label": label,
        "error": error,
        "ticks_run": 0,
        "tick_markers": [],
        "agents": [],
        "posts": [],
        "comments": [],
        "follows": [],
        "mutes": [],
        "reports": [],
        "trace": [],
        "action_histogram": [],
        "agent_tools": [],
        "agent_reasoning": [],
        "measurements": build_measurements(ticks, ticks_run=0),
    }
    if log_path:
        out["log_path"] = log_path
    return out


async def _simulate_variant(
    *,
    run: Run,
    members: list[PopulationMember],
    member_districts: dict[str, str],
    area_blocks: dict[str, str],
    options: OasisRunOptions,
    attempt_id: str,
    variant_id: str,
    label: str,
    ticks: list[Tick],
) -> dict[str, Any]:
    """Run one variant. OasisUnavailable propagates; other errors become variant.error."""
    log_path = run_variant_log_path(run.id, attempt_id, variant_id)
    log = logging.getLogger(__name__)
    with capture_run_log(log_path):
        log.info(
            "Simulating run_id=%s attempt=%s variant=%s (%s) ticks=%s",
            run.id,
            attempt_id,
            variant_id,
            label,
            len(ticks),
        )
        try:
            sim = await run_oasis_simulation(
                run_id=run.id,
                members=members,
                ticks=ticks,
                seed=run.seed,
                variant_id=variant_id,
                attempt_id=attempt_id,
                area_blocks=area_blocks,
                oasis_options=options,
                simulation_start=(
                    run.start_date
                    if isinstance(run.start_date, date)
                    else _parse_simulation_start(None)
                ),
            )
        except OasisUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — keep other variants; record this failure
            log.exception("Variant %s failed: %s", variant_id, exc)
            error = str(exc) or exc.__class__.__name__
            await run_broadcast.publish(
                (run.id, variant_id),
                {
                    "type": "variant.failed",
                    "run_id": run.id,
                    "variant_id": variant_id,
                    "error": error,
                },
            )
            result = _failed_variant(
                variant_id=variant_id,
                label=label,
                ticks=ticks,
                error=error,
                log_path=str(log_path),
            )
            await run_broadcast.publish(
                (run.id, variant_id),
                {
                    "type": "run.attempt_finished",
                    "run_id": run.id,
                    "variant_id": variant_id,
                    "attempt_id": attempt_id,
                    "error": error,
                },
            )
            return result

        agents = sim.get("agents") or []
        posts = sim.get("posts") or []
        comments = sim.get("comments") or []
        follows = sim.get("follows") or []
        mutes = sim.get("mutes") or []
        reports = sim.get("reports") or []
        trace = sim.get("trace") or []
        action_histogram = sim.get("action_histogram") or []
        agent_tools = sim.get("agent_tools") or []
        agent_reasoning = sim.get("agent_reasoning") or []
        tick_markers = sim.get("tick_markers") or []
        ticks_run = int(sim.get("ticks_run") or 0)
        log.info(
            "Variant %s done: ticks_run=%s posts=%s comments=%s",
            variant_id,
            ticks_run,
            len(posts),
            len(comments),
        )
        result_payload = {
            "id": variant_id,
            "label": label,
            "error": None,
            "ticks_run": ticks_run,
            "tick_markers": tick_markers,
            "agents": agents,
            "posts": posts,
            "comments": comments,
            "follows": follows,
            "mutes": mutes,
            "reports": reports,
            "trace": trace,
            "action_histogram": action_histogram,
            "agent_tools": agent_tools,
            "agent_reasoning": agent_reasoning,
            "artifact_db": sim.get("artifact_db"),
            "profile_path": sim.get("profile_path"),
            "profile_csv": sim.get("profile_csv"),
            "profile_json": sim.get("profile_json"),
            "platform": sim.get("platform"),
            "agent_count": sim.get("agent_count"),
            "configured_ticks": sim.get("configured_ticks"),
            "oasis_options": sim.get("oasis_options"),
            "log_path": str(log_path),
            "measurements": build_measurements(
                ticks,
                posts=posts,
                comments=comments,
                agents=agents,
                follows=follows,
                member_districts=member_districts,
                ticks_run=ticks_run,
            ),
            "quality_warnings": analyze_lexical_convergence(
                posts=posts,
                comments=comments,
                agents=agents,
                injection_texts=_injection_texts_labeled(ticks),
            ),
        }
        from app.services import jobs as jobs_service
        from app.services.run_watch import snapshot_live_feed_rounds

        factory = jobs_service.job_session_factory()
        async with factory() as progress_session:
            progress_row = await progress_session.execute(
                select(Run).where(Run.id == run.id)
            )
            fresh = progress_row.scalar_one()
            result_payload["live_feed"] = {
                "rounds": snapshot_live_feed_rounds(fresh, variant_id),
            }
        await run_broadcast.publish(
            (run.id, variant_id),
            {
                "type": "run.attempt_finished",
                "run_id": run.id,
                "variant_id": variant_id,
                "attempt_id": attempt_id,
                "error": None,
            },
        )
        return result_payload


async def simulate_run(session: AsyncSession, run: Run) -> dict[str, Any]:
    """Load population members and execute OASIS for each variant (main or A/B).

    A/B (and stimulus/control) variants run concurrently — each uses its own
    artifact directory under data/oasis/run_{id}/{a|b}/. Per-attempt logs live
    under data/oasis/run_{id}/attempts/{attempt_id}/{variant}.log.
    """
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
    attempt_id = f"att_{secrets.token_hex(4)}"
    log_dir = run_attempt_log_dir(run.id, attempt_id)
    log_dir.mkdir(parents=True, exist_ok=True)
    variant_ids = [variant_id for variant_id, _, _ in plans]
    await reset_live_progress(session, run, variant_ids)
    for variant_id in variant_ids:
        await run_broadcast.publish(
            (run.id, variant_id),
            {
                "type": "run.attempt_started",
                "attempt_id": attempt_id,
            },
        )
    variants_out = list(
        await asyncio.gather(
            *[
                _simulate_variant(
                    run=run,
                    members=members,
                    member_districts=member_districts,
                    area_blocks=area_blocks,
                    options=options,
                    attempt_id=attempt_id,
                    variant_id=variant_id,
                    label=label,
                    ticks=ticks,
                )
                for variant_id, label, ticks in plans
            ]
        )
    )

    all_failed = bool(variants_out) and all(v.get("error") for v in variants_out)
    attempt = {
        "id": attempt_id,
        "finished_at": utcnow().isoformat(),
        "seed": run.seed,
        "engine": "oasis",
        "error": "Alla varianter misslyckades" if all_failed else None,
        "log_dir": str(log_dir),
        "variants": variants_out,
    }
    await session.refresh(run)
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
