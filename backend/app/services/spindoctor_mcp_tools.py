"""Spinndoktor MCP + chat tools — report-scoped data, widgets, SCB, search."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Population, Report, Run
from app.schemas.domain import SpindoctorWidgetOut
from app.serializers import format_date, utcnow
from app.services.oasis_agent_tools import search_duckduckgo, search_wiki
from app.services.report import ARTIFACT_ROOT
from app.services.report.bundles import RunBundle, build_bundles
from app.services.scb_tools import help_scb_tool_specs, run_scb_tool
from app.services.spindoctor_context import load_spindoctor_source
from app.services.spindoctor_tools import (
    SPINDOCTOR_TOOL_SPECS,
    run_spindoctor_tool,
    run_spindoctor_tool_on_bundles,
    spindoctor_tool_specs,
)

ChartType = Literal["hbar", "donut", "stat_number"]
WidgetKind = Literal["chart", "note", "report_snippet"]

_SCB_TOOL_NAMES = frozenset(
    {
        "scb_search_tables",
        "scb_get_table_meta",
        "scb_query",
        "scb_population_dist",
    }
)
_SEARCH_TOOL_NAMES = frozenset({"search_wiki", "search_duckduckgo"})
_LIST_TOOL_NAMES = frozenset({"list_runs", "list_reports", "list_populations"})
_DATA_TOOL_NAMES = frozenset(
    {
        "get_test_message",
        "get_run",
        "search_reactions",
        "list_interviews",
        "list_actors",
        "get_citizen",
        "get_report_ssr",
    }
)
_WIDGET_TOOL_NAMES = frozenset({"render_chart", "place_note"})

SPINDOCTOR_MCP_TOOL_NAMES = (
    _DATA_TOOL_NAMES
    | _LIST_TOOL_NAMES
    | _SCB_TOOL_NAMES
    | _SEARCH_TOOL_NAMES
    | _WIDGET_TOOL_NAMES
)


@dataclass
class SpindoctorToolContext:
    """Mutable context for one chat turn or MCP call batch."""

    report_id: str | None = None
    question_sent_at: datetime | None = None
    widgets: list[SpindoctorWidgetOut] = field(default_factory=list)


def _compact(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _latency_ms(ctx: SpindoctorToolContext) -> int | None:
    if ctx.question_sent_at is None:
        return None
    delta = utcnow() - ctx.question_sent_at
    return max(0, int(delta.total_seconds() * 1000))


def _widget_out(
    ctx: SpindoctorToolContext,
    *,
    kind: WidgetKind,
    title: str,
    chart_type: ChartType | None = None,
    series: list[dict[str, Any]] | None = None,
    body: str | None = None,
    section_id: str | None = None,
) -> SpindoctorWidgetOut:
    now = utcnow()
    widget = SpindoctorWidgetOut(
        id=f"wdg_{uuid.uuid4().hex[:12]}",
        kind=kind,
        title=title,
        created_at=format_date(now),
        question_sent_at=(
            format_date(ctx.question_sent_at) if ctx.question_sent_at else None
        ),
        latency_ms=_latency_ms(ctx),
        chart_type=chart_type,
        series=series,
        body=body,
        section_id=section_id,
    )
    ctx.widgets.append(widget)
    return widget


def _search_tool_specs() -> list[dict[str, Any]]:
    from app.services.playground_tools import _callable_doc, _openai_params

    def _spec(fn: Any, name: str) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": _callable_doc(fn),
                "parameters": _openai_params(fn),
            },
        }

    return [
        _spec(search_duckduckgo, "search_duckduckgo"),
        _spec(search_wiki, "search_wiki"),
    ]


def _list_tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "list_runs",
                "description": "List körningar (id, name, status, population).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_reports",
                "description": "List reports (id, title, status, locale).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_populations",
                "description": "List populations (id, name, size).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_report_ssr",
                "description": (
                    "Load report.ssr.json aggregates (tone, style, thresholds) for a report id."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "report_id": {"type": "string"},
                    },
                    "required": ["report_id"],
                },
            },
        },
    ]


def _widget_tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "render_chart",
                "description": (
                    "Place a chart widget on the Spinndoktor grid. "
                    "Use hbar for style shares, donut for tone/topics, stat_number for one KPI."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chart_type": {
                            "type": "string",
                            "enum": ["hbar", "donut", "stat_number"],
                        },
                        "title": {"type": "string"},
                        "series": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string"},
                                    "value": {"type": "number"},
                                },
                                "required": ["label", "value"],
                            },
                        },
                    },
                    "required": ["chart_type", "title", "series"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "place_note",
                "description": (
                    "Place a short note card on the Spinndoktor grid summarizing a finding."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["title", "body"],
                },
            },
        },
    ]


def spindoctor_mcp_tool_specs() -> list[dict[str, Any]]:
    return [
        *spindoctor_tool_specs(),
        *_list_tool_specs(),
        *help_scb_tool_specs(),
        *_search_tool_specs(),
        *_widget_tool_specs(),
    ]


def _clamp_limit(value: Any, *, default: int = 20) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(50, number))


async def _list_runs(session: AsyncSession, arguments: dict[str, Any]) -> str:
    limit = _clamp_limit(arguments.get("limit"))
    stmt = (
        select(Run)
        .options(selectinload(Run.population))
        .order_by(Run.updated_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    payload = [
        {
            "id": run.id,
            "name": run.name,
            "status": run.status,
            "population_id": run.population_id,
            "population_name": run.population.name if run.population else None,
        }
        for run in rows
    ]
    return _compact({"runs": payload})


async def _list_reports(session: AsyncSession, arguments: dict[str, Any]) -> str:
    limit = _clamp_limit(arguments.get("limit"))
    stmt = select(Report).order_by(Report.updated_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    payload = [
        {
            "id": row.id,
            "title": row.title,
            "status": row.status,
            "locale": row.locale,
        }
        for row in rows
    ]
    return _compact({"reports": payload})


async def _list_populations(session: AsyncSession, arguments: dict[str, Any]) -> str:
    limit = _clamp_limit(arguments.get("limit"))
    stmt = select(Population).order_by(Population.updated_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    payload = [
        {"id": row.id, "name": row.name, "size": row.size} for row in rows
    ]
    return _compact({"populations": payload})


async def _get_report_ssr(arguments: dict[str, Any]) -> str:
    report_id = str(arguments.get("report_id") or "").strip()
    if not report_id:
        return "report_id is required"
    path = Path(ARTIFACT_ROOT) / report_id / "report.ssr.json"
    if not path.is_file():
        return f"report.ssr.json not found for {report_id!r}"
    return path.read_text(encoding="utf-8")


def _normalize_series(raw: object) -> list[dict[str, float | str]]:
    if not isinstance(raw, list):
        raise ValueError("series must be an array")
    out: list[dict[str, float | str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        if not label:
            continue
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        out.append({"label": label, "value": value})
    if not out:
        raise ValueError("series must contain at least one label/value pair")
    return out


def _render_chart(ctx: SpindoctorToolContext, arguments: dict[str, Any]) -> str:
    chart_raw = str(arguments.get("chart_type") or "").strip()
    if chart_raw not in {"hbar", "donut", "stat_number"}:
        raise ValueError("chart_type must be hbar, donut, or stat_number")
    chart_type: ChartType = chart_raw  # type: ignore[assignment]
    title = str(arguments.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    series = _normalize_series(arguments.get("series"))
    widget = _widget_out(
        ctx,
        kind="chart",
        title=title,
        chart_type=chart_type,
        series=series,
    )
    return _compact(
        {
            "ok": True,
            "widget_id": widget.id,
            "chart_type": chart_type,
            "title": title,
            "series": series,
        }
    )


def _place_note(ctx: SpindoctorToolContext, arguments: dict[str, Any]) -> str:
    title = str(arguments.get("title") or "").strip()
    body = str(arguments.get("body") or "").strip()
    if not title:
        raise ValueError("title is required")
    if not body:
        raise ValueError("body is required")
    widget = _widget_out(ctx, kind="note", title=title, body=body)
    return _compact({"ok": True, "widget_id": widget.id, "title": title})


def make_report_snippet_widget(
    ctx: SpindoctorToolContext,
    *,
    section_id: str,
    title: str | None = None,
) -> SpindoctorWidgetOut:
    label = title or section_id
    return _widget_out(
        ctx,
        kind="report_snippet",
        title=label,
        section_id=section_id,
    )


async def _resolve_bundles(
    session: AsyncSession,
    ctx: SpindoctorToolContext,
    arguments: dict[str, Any],
) -> list[RunBundle]:
    if ctx.report_id:
        _report, bundles = await load_spindoctor_source(session, report_id=ctx.report_id)
        return bundles
    run_id = arguments.get("run_id")
    attempt_id = str(arguments.get("attempt_id") or "").strip()
    if run_id is None or not attempt_id:
        raise ValueError("report_id context or run_id + attempt_id required")
    try:
        rid = int(run_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("run_id must be an integer") from exc
    return await build_bundles(
        session,
        [{"run_id": rid, "attempt_id": attempt_id}],
    )


async def run_spindoctor_mcp_tool(
    session: AsyncSession,
    name: str,
    arguments: dict[str, Any],
    *,
    ctx: SpindoctorToolContext,
) -> str:
    if name in _WIDGET_TOOL_NAMES:
        if name == "render_chart":
            return _render_chart(ctx, arguments)
        return _place_note(ctx, arguments)

    if name in _SCB_TOOL_NAMES:
        return await run_scb_tool(name, arguments)

    if name == "search_wiki":
        entity = str(arguments.get("entity") or "").strip()
        return search_wiki(entity)

    if name == "search_duckduckgo":
        query = str(arguments.get("query") or "").strip()
        return search_duckduckgo(query)

    if name == "list_runs":
        return await _list_runs(session, arguments)

    if name == "list_reports":
        return await _list_reports(session, arguments)

    if name == "list_populations":
        return await _list_populations(session, arguments)

    if name == "get_report_ssr":
        return await _get_report_ssr(arguments)

    if name in _DATA_TOOL_NAMES:
        if ctx.report_id:
            return await run_spindoctor_tool(
                session,
                name,
                arguments,
                report_id=ctx.report_id,
            )
        bundles = await _resolve_bundles(session, ctx, arguments)
        return run_spindoctor_tool_on_bundles(name, arguments, bundles)

    raise ValueError(f"Unknown Spinndoktor tool: {name}")
