"""Read-only app data snapshots for the help chat assistant."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    Configuration,
    Job,
    Message,
    Persona,
    Population,
    Report,
    Run,
    SsrAnchorSet,
)
from app.schemas.domain import HelpViewContext, OasisRunOptions
from app.services.catalog_items import coerce_catalog_items
from app.services.catalog_store import get_catalog_list
from app.services.okf_corpus import manual_context
from app.services.run_log import read_run_log_tail, tail_run_log_file
from app.services.run_results import list_attempts

_HELP_LOG_TAIL_LINES = 50
_RECENT_JOBS_LIMIT = 8
_AGENT_TOOLS_LIMIT = 12
_QUALITY_WARNINGS_LIMIT = 5


async def build_help_context(
    session: AsyncSession,
    *,
    view: HelpViewContext | None,
    query: str,
) -> str:
    sections: list[str] = []
    if view is not None:
        sections.append(_format_view(view))
        entity = await _load_view_entity(session, view)
        if entity:
            sections.append(entity)
    sections.append(await _load_library_snapshot(session))
    sections.append(f"# Manual (OKF)\n\n{manual_context(query)}")
    return "\n\n".join(sections)


def _format_view(view: HelpViewContext) -> str:
    lines = [
        "# Current view (injected from UI)",
        f"- Label: {view.label}",
        f"- View key: {view.view_key}",
        f"- Path: {view.path}",
    ]
    if view.params:
        params = ", ".join(f"{key}={value}" for key, value in sorted(view.params.items()))
        lines.append(f"- Route params: {params}")
    if view.search:
        search = ", ".join(f"{key}={value}" for key, value in sorted(view.search.items()))
        lines.append(f"- Query params: {search}")
    return "\n".join(lines)


def _clip(text: str | None, limit: int) -> str:
    if not text:
        return ""
    cleaned = text.replace("\n", " ").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _format_job_line(job: Job) -> str:
    line = f"  - id={job.id} · {job.kind} · {job.status} · {job.label or '(no label)'}"
    if job.error:
        line += f"\n    error: {_clip(job.error, 800)}"
    return line


def _format_agent_tools(tools: list[Any] | None) -> list[str]:
    if not tools:
        return ["  - (none recorded)"]
    lines: list[str] = []
    for row in tools[:_AGENT_TOOLS_LIMIT]:
        if not isinstance(row, dict):
            continue
        preview = _clip(str(row.get("result_preview") or ""), 160)
        args = row.get("args")
        args_text = _clip(json.dumps(args, ensure_ascii=False) if args else "{}", 120)
        lines.append(
            "  - "
            f"tick={row.get('tick_index')} · {row.get('tool_name')} · "
            f"args={args_text} · result={preview or '(empty)'}"
        )
    if len(tools) > _AGENT_TOOLS_LIMIT:
        lines.append(f"  - … {len(tools) - _AGENT_TOOLS_LIMIT} more tool calls")
    return lines


def _format_quality_warnings(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return ["  - (none)"]
    warnings = payload.get("warnings")
    if not isinstance(warnings, list) or not warnings:
        return ["  - (none)"]
    lines = [
        f"  - threshold={payload.get('threshold')} · "
        f"population_agents={payload.get('population_agents')} · "
        f"count={len(warnings)}"
    ]
    for warning in warnings[:_QUALITY_WARNINGS_LIMIT]:
        if not isinstance(warning, dict):
            continue
        lines.append(
            "  - "
            f"{warning.get('kind')} · phrase={_clip(str(warning.get('phrase') or ''), 80)} · "
            f"agents={warning.get('agent_count')}/{warning.get('population_agents')}"
        )
    if len(warnings) > _QUALITY_WARNINGS_LIMIT:
        lines.append(f"  - … {len(warnings) - _QUALITY_WARNINGS_LIMIT} more warnings")
    return lines


def _read_log_tail_for_help(
    run_id: int,
    attempt_id: str,
    variant_id: str,
    *,
    log_path: str | None,
) -> list[str]:
    content = ""
    truncated = False
    resolved_path = log_path or ""

    try:
        path, content, truncated = read_run_log_tail(
            run_id=run_id,
            attempt_id=attempt_id,
            variant_id=variant_id,
            lines=_HELP_LOG_TAIL_LINES,
        )
        resolved_path = str(path)
    except FileNotFoundError:
        if log_path:
            try:
                content, truncated = tail_run_log_file(
                    Path(log_path),
                    lines=_HELP_LOG_TAIL_LINES,
                )
                resolved_path = log_path
            except (FileNotFoundError, OSError):
                return ["- log tail: (file not found)"]
        else:
            return ["- log tail: (file not found)"]
    except ValueError as exc:
        return [f"- log tail: (unavailable: {exc})"]

    lines = [
        f"- log_path: {resolved_path}",
        f"- log tail (last {_HELP_LOG_TAIL_LINES} lines, truncated={truncated}):",
    ]
    if content.strip():
        lines.extend(f"    {log_line}" for log_line in content.splitlines())
    else:
        lines.append("    (empty log file)")
    return lines


def _format_run_troubleshooting(run: Run, *, tab: str | None) -> str:
    sections: list[str] = [
        "# Open run (read-only)",
        f"- id: {run.id}",
        f"- name: {run.name}",
        f"- status: {run.status}",
        f"- active tab: {tab or 'default'}",
    ]

    pop_name = run.population.name if run.population else "?"
    sections.extend(
        [
            f"- population: {pop_name} (id={run.population_id})",
            f"- timeline days: {len(run.main_ticks or [])}",
        ]
    )

    branch = (run.branch or {}).get("mode") if run.branch else None
    if branch:
        sections.append(f"- branch mode: {branch}")

    options = OasisRunOptions.model_validate(run.oasis_options or {})
    sections.append(
        "- agent tools enabled: "
        f"duckduckgo={options.enable_search_duckduckgo}, "
        f"wiki={options.enable_search_wiki}, "
        f"sympy={options.enable_sympy_tools}"
    )

    results = run.results
    if not results:
        sections.append("- results: (none yet)")
        return "\n".join(sections)

    attempts = list_attempts(results)
    sections.append(f"- results engine: {results.get('engine') or attempts[0].get('engine') if attempts else '?'}")
    sections.append(f"- attempts: {len(attempts)} (newest first)")

    for attempt in attempts[:2]:
        attempt_id = str(attempt.get("id") or "?")
        sections.append("")
        sections.append(f"## Attempt {attempt_id}")
        sections.append(f"- finished_at: {attempt.get('finished_at') or '?'}")
        sections.append(f"- engine: {attempt.get('engine') or '?'}")
        if attempt.get("error"):
            sections.append(f"- attempt error: {_clip(str(attempt.get('error')), 800)}")
        if attempt.get("log_dir"):
            sections.append(f"- log_dir: {attempt.get('log_dir')}")

        variants = attempt.get("variants")
        if not isinstance(variants, list):
            continue

        for variant in variants:
            if not isinstance(variant, dict):
                continue
            variant_id = str(variant.get("id") or "?")
            sections.append("")
            sections.append(f"### Variant {variant_id} ({variant.get('label') or '?'})")
            sections.append(f"- ticks_run: {variant.get('ticks_run', 0)}")
            if variant.get("error"):
                sections.append(f"- error: {_clip(str(variant.get('error')), 800)}")
            sections.append("- quality_warnings:")
            sections.extend(_format_quality_warnings(variant.get("quality_warnings")))
            sections.append("- agent_tools:")
            sections.extend(_format_agent_tools(variant.get("agent_tools")))

            needs_log = bool(variant.get("error")) or attempt.get("error")
            if needs_log:
                sections.append("- troubleshooting log:")
                sections.extend(
                    _read_log_tail_for_help(
                        run.id,
                        attempt_id,
                        variant_id,
                        log_path=str(variant.get("log_path") or ""),
                    )
                )
            elif variant.get("log_path"):
                sections.append(f"- log_path: {variant.get('log_path')}")

    return "\n".join(sections)


def _format_label_list(labels: list[str]) -> str:
    if not labels:
        return "(none)"
    return ", ".join(labels)


async def _active_tone_sections(session: AsyncSession, active: Configuration | None) -> list[str]:
    """Catalog ton + SSR tone/style labels from the active configuration."""
    if active is None:
        return [
            "- Catalog ton labels: (no active configuration)",
            "- SSR tone labels: (no active configuration)",
            "- SSR style labels: (no active configuration)",
        ]

    lines: list[str] = []
    catalog = await get_catalog_list(session, active.id, "ton")
    if catalog is None:
        lines.append("- Catalog ton labels (persona voice): (not seeded)")
    else:
        labels = [item.label for item in coerce_catalog_items(catalog.items)]
        lines.append(f"- Catalog ton labels (persona voice): {_format_label_list(labels)}")

    refs = dict(active.anchor_sets or {})
    loc = active.language if active.language in {"sv", "en"} else "sv"
    block = refs.get(loc)
    if not isinstance(block, dict):
        lines.append("- SSR tone labels: (not linked on active configuration)")
        lines.append("- SSR style labels: (not linked on active configuration)")
        return lines

    for kind, title in (("tone", "SSR tone labels"), ("style", "SSR style labels")):
        anchor_id = int(block.get(kind) or 0)
        if anchor_id <= 0:
            lines.append(f"- {title}: (not linked)")
            continue
        row = await session.get(SsrAnchorSet, anchor_id)
        if row is None:
            lines.append(f"- {title}: (missing set id={anchor_id})")
            continue
        labels = [str(x) for x in (row.labels or [])]
        lines.append(
            f"- {title}: {_format_label_list(labels)} "
            f"(set id={row.id}, name={row.name}, status={row.status})"
        )
    return lines


async def _load_library_snapshot(session: AsyncSession) -> str:
    persona_count = await session.scalar(select(func.count()).select_from(Persona)) or 0
    population_count = await session.scalar(select(func.count()).select_from(Population)) or 0
    run_count = await session.scalar(select(func.count()).select_from(Run)) or 0
    message_count = await session.scalar(select(func.count()).select_from(Message)) or 0
    report_count = await session.scalar(select(func.count()).select_from(Report)) or 0
    anchor_count = await session.scalar(select(func.count()).select_from(SsrAnchorSet)) or 0
    config_count = await session.scalar(select(func.count()).select_from(Configuration)) or 0

    active = await session.scalar(
        select(Configuration)
        .where(Configuration.is_active.is_(True))
        .order_by(Configuration.id.asc())
        .limit(1)
    )

    jobs = (
        await session.execute(
            select(Job)
            .where(Job.archived_at.is_(None))
            .order_by(Job.created_at.desc())
            .limit(_RECENT_JOBS_LIMIT)
        )
    ).scalars().all()
    job_lines = [_format_job_line(job) for job in jobs] or ["  - (no jobs yet)"]

    active_line = "none"
    if active is not None:
        active_line = f"{active.name} (id={active.id}, language={active.language})"

    tone_lines = await _active_tone_sections(session, active)

    return "\n".join(
        [
            "# Live data snapshot (read-only)",
            f"- Personas: {persona_count}",
            f"- Populations: {population_count}",
            f"- Runs: {run_count}",
            f"- Messages (budskap): {message_count}",
            f"- Reports: {report_count}",
            f"- SSR anchor sets: {anchor_count}",
            f"- Configurations: {config_count}",
            f"- Active configuration: {active_line}",
            *tone_lines,
            "- Recent background jobs:",
            *job_lines,
        ]
    )


async def _load_jobs_snapshot(session: AsyncSession) -> str:
    jobs = (
        await session.execute(
            select(Job)
            .where(Job.archived_at.is_(None))
            .order_by(Job.created_at.desc())
            .limit(_RECENT_JOBS_LIMIT)
        )
    ).scalars().all()
    if not jobs:
        return "# Open jobs view\n\nNo background jobs yet."
    lines = ["# Open jobs view (read-only)", f"- Showing latest {len(jobs)} jobs:"]
    lines.extend(_format_job_line(job) for job in jobs)
    return "\n".join(lines)


async def _load_view_entity(session: AsyncSession, view: HelpViewContext) -> str | None:
    key = view.view_key
    params = view.params

    if key == "jobs.list":
        return await _load_jobs_snapshot(session)

    if key == "personas.detail" and (persona_id := params.get("id")):
        row = await session.get(Persona, persona_id)
        if row is None:
            return f"# Open persona\n\nPersona `{persona_id}` was not found."
        return "\n".join(
            [
                "# Open persona (read-only)",
                f"- id: {row.id}",
                f"- name: {row.name}",
                f"- age: {row.age}",
                f"- occupation: {row.occ}",
                f"- district: {row.district}",
                f"- origin: {row.origin}",
                f"- quote: {row.quote[:240]}",
            ]
        )

    if key in {"runs.edit", "runs.new"} and (run_id := params.get("id")):
        result = await session.execute(
            select(Run).options(selectinload(Run.population)).where(Run.id == int(run_id))
        )
        row = result.scalar_one_or_none()
        if row is None:
            return f"# Open run\n\nRun `{run_id}` was not found."
        return _format_run_troubleshooting(row, tab=view.search.get("tab"))

    if key.startswith("populations.") and (pop_id := params.get("id")):
        row = await session.get(Population, int(pop_id))
        if row is None:
            return f"# Open population\n\nPopulation `{pop_id}` was not found."
        return "\n".join(
            [
                "# Open population (read-only)",
                f"- id: {row.id}",
                f"- name: {row.name}",
                f"- size: {row.size}",
                f"- versions: {row.versions}",
            ]
        )

    if key == "messages.edit" and (message_id := params.get("id")):
        row = await session.get(Message, message_id)
        if row is None:
            return f"# Open message\n\nMessage `{message_id}` was not found."
        body_preview = row.body[:280].replace("\n", " ")
        return "\n".join(
            [
                "# Open message (read-only)",
                f"- id: {row.id}",
                f"- type: {row.type}",
                f"- title: {row.title}",
                f"- body preview: {body_preview}",
            ]
        )

    if key.startswith("tools.configurations") and (config_id := params.get("id")):
        row = await session.get(Configuration, int(config_id))
        if row is None:
            return f"# Open configuration\n\nConfiguration `{config_id}` was not found."
        return "\n".join(
            [
                "# Open configuration (read-only)",
                f"- id: {row.id}",
                f"- name: {row.name}",
                f"- language: {row.language}",
                f"- active: {row.is_active}",
                f"- ssr_temperature: {row.ssr_temperature}",
            ]
        )

    if key.startswith("tools.anchor_sets") and (anchor_id := params.get("id")):
        row = await session.get(SsrAnchorSet, int(anchor_id))
        if row is None:
            return f"# Open anchor set\n\nAnchor set `{anchor_id}` was not found."
        labels = [str(x) for x in (row.labels or [])]
        return "\n".join(
            [
                "# Open SSR anchor set (read-only)",
                f"- id: {row.id}",
                f"- name: {row.name}",
                f"- kind: {row.kind}",
                f"- locale: {row.locale}",
                f"- status: {row.status}",
                f"- version: {row.version}",
                f"- labels: {_format_label_list(labels)}",
            ]
        )

    if key == "reports.view" and (report_id := params.get("id")):
        row = await session.get(Report, report_id)
        if row is None:
            return f"# Open report\n\nReport `{report_id}` was not found."
        return "\n".join(
            [
                "# Open report (read-only)",
                f"- id: {row.id}",
                f"- title: {row.title}",
                f"- mode: {row.mode}",
                f"- locale: {row.locale}",
                f"- status: {row.status}",
            ]
        )

    return None
