"""Read-only app data snapshots for the help chat assistant."""

from __future__ import annotations

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
from app.schemas.domain import HelpViewContext
from app.services.okf_corpus import manual_context


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
        await session.execute(select(Job).order_by(Job.created_at.desc()).limit(5))
    ).scalars().all()
    job_lines = [
        f"  - {job.kind} · {job.status} · {job.label}" for job in jobs
    ] or ["  - (no jobs yet)"]

    active_line = "none"
    if active is not None:
        active_line = f"{active.name} (id={active.id}, language={active.language})"

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
            "- Recent background jobs:",
            *job_lines,
        ]
    )


async def _load_view_entity(session: AsyncSession, view: HelpViewContext) -> str | None:
    key = view.view_key
    params = view.params

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
        pop_name = row.population.name if row.population else "?"
        branch = (row.branch or {}).get("mode") if row.branch else None
        tab = view.search.get("tab")
        return "\n".join(
            [
                "# Open run (read-only)",
                f"- id: {row.id}",
                f"- name: {row.name}",
                f"- status: {row.status}",
                f"- population: {pop_name} (id={row.population_id})",
                f"- timeline days: {len(row.main_ticks or [])}",
                f"- branch mode: {branch or 'none'}",
                f"- active tab: {tab or 'default'}",
            ]
        )

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
        return "\n".join(
            [
                "# Open SSR anchor set (read-only)",
                f"- id: {row.id}",
                f"- name: {row.name}",
                f"- kind: {row.kind}",
                f"- locale: {row.locale}",
                f"- status: {row.status}",
                f"- version: {row.version}",
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
