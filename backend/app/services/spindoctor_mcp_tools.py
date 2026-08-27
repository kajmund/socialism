"""Spinndoktor MCP + chat tools — report-scoped data, widgets, SCB, search."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import PersonaMessage, Population, Report, Run
from app.schemas.domain import SpindoctorWidgetOut
from app.serializers import format_date, utcnow
from app.services.oasis_agent_tools import search_duckduckgo, search_wiki
from app.services.report import ARTIFACT_ROOT
from app.services.persona_chat import (
    ChatTurnError,
    _find_attempt_variant,
    complete_run_interview_turn,
    run_interview_filter,
    validate_interview_variant,
)
from app.services.report.bundles import RunBundle, build_bundles
from app.services.scb_tools import help_scb_tool_specs, run_scb_tool
from app.services.spindoctor_context import load_spindoctor_source
from app.services.spindoctor_tools import (
    SPINDOCTOR_TOOL_SPECS,
    run_spindoctor_tool,
    run_spindoctor_tool_on_bundles,
    spindoctor_tool_specs,
)

ChartType = Literal["hbar", "donut", "stat_number", "radar"]
WidgetKind = Literal["chart", "note", "report_snippet", "interview"]

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
        "get_report_dd",
    }
)
_WIDGET_TOOL_NAMES = frozenset({"render_chart", "place_note", "start_interview"})
_INTERVIEW_TOOL_NAMES = frozenset({"ask_interview_question"})
_READ_INTERVIEW_TOOL_NAMES = frozenset({"read_interview_transcript"})

SPINDOCTOR_MCP_TOOL_NAMES = (
    _DATA_TOOL_NAMES
    | _LIST_TOOL_NAMES
    | _SCB_TOOL_NAMES
    | _SEARCH_TOOL_NAMES
    | _WIDGET_TOOL_NAMES
    | _INTERVIEW_TOOL_NAMES
    | _READ_INTERVIEW_TOOL_NAMES
)


@dataclass
class SpindoctorToolContext:
    """Mutable context for one chat turn or MCP call batch."""

    report_id: str | None = None
    question_sent_at: datetime | None = None
    widgets: list[SpindoctorWidgetOut] = field(default_factory=list)
    _widgets_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


def _compact(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _latency_ms(ctx: SpindoctorToolContext) -> int | None:
    if ctx.question_sent_at is None:
        return None
    delta = utcnow() - ctx.question_sent_at
    return max(0, int(delta.total_seconds() * 1000))


async def _widget_out(
    ctx: SpindoctorToolContext,
    *,
    kind: WidgetKind,
    title: str,
    chart_type: ChartType | None = None,
    series: list[dict[str, Any]] | None = None,
    body: str | None = None,
    section_id: str | None = None,
    persona_id: str | None = None,
    persona_name: str | None = None,
    run_id: int | None = None,
    attempt_id: str | None = None,
    variant_id: str | None = None,
    through_tick_index: int | None = None,
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
        persona_id=persona_id,
        persona_name=persona_name,
        run_id=run_id,
        attempt_id=attempt_id,
        variant_id=variant_id,
        through_tick_index=through_tick_index,
    )
    async with ctx._widgets_lock:
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
                    "Load report.ssr.json aggregates (tone, style, thresholds) for an OASIS "
                    "simulation report id."
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
        {
            "type": "function",
            "function": {
                "name": "get_report_dd",
                "description": (
                    "Load report.dd.json (candidate, expert scores, dissensus, summary) for a "
                    "DD report id."
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
                    "Use hbar for style shares, donut for tone/topics, stat_number for one KPI, "
                    "radar for DD sub-question scores (0–10 per axis)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chart_type": {
                            "type": "string",
                            "enum": ["hbar", "donut", "stat_number", "radar"],
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
        {
            "type": "function",
            "function": {
                "name": "start_interview",
                "description": (
                    "Open a live persona interview widget on the Spinndoktor grid. "
                    "Match persona_name like get_citizen (substring, case-insensitive). "
                    "Defaults through_tick_index to the latest simulated tick. "
                    "Always send opening_question so the first turn goes out immediately "
                    "(doctor asks; answer returned in tool result). Do not ask the "
                    "operator what to ask the persona."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "persona_name": {"type": "string"},
                        "through_tick_index": {"type": "integer", "minimum": 0},
                        "opening_question": {"type": "string"},
                    },
                    "required": ["persona_name"],
                },
            },
        },
    ]


def _interview_turn_tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "ask_interview_question",
                "description": (
                    "Ask a follow-up question in an existing live interview widget. "
                    "Provide widget_id from start_interview, or persona_id + run_id + "
                    "attempt_id + variant_id + through_tick_index. Returns the persona's "
                    "answer text."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "widget_id": {"type": "string"},
                        "persona_id": {"type": "string"},
                        "run_id": {"type": "integer"},
                        "attempt_id": {"type": "string"},
                        "variant_id": {"type": "string"},
                        "through_tick_index": {"type": "integer", "minimum": 0},
                        "question": {"type": "string"},
                    },
                    "required": ["question"],
                },
            },
        },
    ]


def _read_interview_tool_specs() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "read_interview_transcript",
                "description": (
                    "Read the full PersonaMessage transcript for a live interview widget. "
                    "Provide widget_id from start_interview, or persona_id + run_id + "
                    "attempt_id + variant_id + through_tick_index."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "widget_id": {"type": "string"},
                        "persona_id": {"type": "string"},
                        "run_id": {"type": "integer"},
                        "attempt_id": {"type": "string"},
                        "variant_id": {"type": "string"},
                        "through_tick_index": {"type": "integer", "minimum": 0},
                    },
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
        *_interview_turn_tool_specs(),
        *_read_interview_tool_specs(),
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
            "mode": row.mode,
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


async def _get_report_dd(arguments: dict[str, Any], *, ctx: SpindoctorToolContext) -> str:
    report_id = str(arguments.get("report_id") or ctx.report_id or "").strip()
    if not report_id:
        return "report_id is required"
    path = Path(ARTIFACT_ROOT) / report_id / "report.dd.json"
    if not path.is_file():
        return f"report.dd.json not found for {report_id!r}"
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


async def _render_chart(ctx: SpindoctorToolContext, arguments: dict[str, Any]) -> str:
    chart_raw = str(arguments.get("chart_type") or "").strip()
    if chart_raw not in {"hbar", "donut", "stat_number", "radar"}:
        raise ValueError("chart_type must be hbar, donut, stat_number, or radar")
    chart_type: ChartType = chart_raw  # type: ignore[assignment]
    title = str(arguments.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    series = _normalize_series(arguments.get("series"))
    if chart_type == "radar":
        for row in series:
            value = float(row["value"])
            if value < 0 or value > 10:
                raise ValueError("radar series values must be between 0 and 10")
    widget = await _widget_out(
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


async def _place_note(ctx: SpindoctorToolContext, arguments: dict[str, Any]) -> str:
    title = str(arguments.get("title") or "").strip()
    body = str(arguments.get("body") or "").strip()
    if not title:
        raise ValueError("title is required")
    if not body:
        raise ValueError("body is required")
    widget = await _widget_out(ctx, kind="note", title=title, body=body)
    return _compact({"ok": True, "widget_id": widget.id, "title": title})


def _find_interview_matches(
    bundles: list[RunBundle],
    persona_name: str,
) -> list[dict[str, Any]]:
    needle = persona_name.casefold()
    matches: list[dict[str, Any]] = []
    for bundle in bundles:
        for agent in bundle.agents:
            if str(agent.get("role") or "") == "injector":
                continue
            name = str(agent.get("member_name") or agent.get("name") or "").strip()
            persona_id = str(agent.get("persona_id") or "").strip()
            if not name or not persona_id:
                continue
            if needle not in name.casefold():
                continue
            matches.append(
                {
                    "bundle": bundle,
                    "persona_id": persona_id,
                    "persona_name": name,
                }
            )
    return matches


def _default_through_tick_index(variant: dict[str, Any]) -> int:
    markers = variant.get("tick_markers") or []
    ticks_run = int(variant.get("ticks_run") or 0)
    if ticks_run > 0:
        return ticks_run - 1
    if markers:
        return len(markers) - 1
    raise ValueError("No simulation ticks available for interview")


def _resolve_interview_coordinates(
    ctx: SpindoctorToolContext,
    arguments: dict[str, Any],
) -> tuple[str, int, str, str, str, int]:
    widget_id = str(arguments.get("widget_id") or "").strip()
    persona_id = str(arguments.get("persona_id") or "").strip()
    attempt_id = str(arguments.get("attempt_id") or "").strip()
    variant_id = str(arguments.get("variant_id") or "").strip()
    run_raw = arguments.get("run_id")
    tick_raw = arguments.get("through_tick_index")

    if widget_id:
        widget = next((row for row in ctx.widgets if row.id == widget_id), None)
        if widget is not None and widget.kind == "interview":
            if not widget.persona_id or widget.run_id is None:
                raise ValueError(f"Interview widget {widget_id!r} is missing coordinates")
            return (
                widget.persona_id,
                int(widget.run_id),
                str(widget.attempt_id or ""),
                str(widget.variant_id or ""),
                str(widget.persona_name or ""),
                int(widget.through_tick_index or 0),
            )

    if not persona_id or run_raw is None or not attempt_id or not variant_id:
        raise ValueError(
            "Provide widget_id or persona_id + run_id + attempt_id + variant_id + through_tick_index"
        )
    if tick_raw is None:
        raise ValueError("through_tick_index is required when widget_id is omitted")
    try:
        run_id = int(run_raw)
        through_tick_index = int(tick_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("run_id and through_tick_index must be integers") from exc
    persona_name = str(arguments.get("persona_name") or persona_id).strip()
    return persona_id, run_id, attempt_id, variant_id, persona_name, through_tick_index


async def _start_interview(
    session: AsyncSession,
    ctx: SpindoctorToolContext,
    arguments: dict[str, Any],
) -> str:
    persona_name = str(arguments.get("persona_name") or "").strip()
    if not persona_name:
        raise ValueError("persona_name is required")

    bundles = await _resolve_bundles(session, ctx, arguments)
    matches = _find_interview_matches(bundles, persona_name)
    if not matches:
        raise ValueError(f"No citizen matched {persona_name!r}")

    persona_ids = {match["persona_id"] for match in matches}
    if len(persona_ids) > 1:
        labels = sorted(
            f"{match['persona_name']} ({match['bundle'].label})" for match in matches
        )
        raise ValueError(
            f"Ambiguous persona_name {persona_name!r}; matches: {', '.join(labels)}"
        )

    match = matches[0]
    bundle: RunBundle = match["bundle"]
    persona_id = str(match["persona_id"])
    display_name = str(match["persona_name"])

    run = await session.get(Run, bundle.run_id)
    if run is None:
        raise ValueError("Run not found")

    variant_id = str(bundle.variant_id or "main")
    try:
        variant = _find_attempt_variant(
            run.results if isinstance(run.results, dict) else None,
            bundle.attempt_id,
            variant_id,
        )
    except ChatTurnError as exc:
        raise ValueError(str(exc)) from exc

    tick_raw = arguments.get("through_tick_index")
    if tick_raw is None:
        through_tick_index = _default_through_tick_index(variant)
    else:
        try:
            through_tick_index = int(tick_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("through_tick_index must be an integer") from exc

    try:
        validate_interview_variant(
            run,
            variant,
            persona_id=persona_id,
            through_tick_index=through_tick_index,
        )
    except ChatTurnError as exc:
        raise ValueError(str(exc)) from exc

    markers = variant.get("tick_markers") or []
    day = markers[through_tick_index].get("day", through_tick_index + 1)
    title = f"Intervju: {display_name} · dag {day}"

    widget = await _widget_out(
        ctx,
        kind="interview",
        title=title,
        persona_id=persona_id,
        persona_name=display_name,
        run_id=bundle.run_id,
        attempt_id=bundle.attempt_id,
        variant_id=variant_id,
        through_tick_index=through_tick_index,
    )
    payload: dict[str, Any] = {
        "ok": True,
        "widget_id": widget.id,
        "persona_id": persona_id,
        "persona_name": display_name,
        "run_id": bundle.run_id,
        "attempt_id": bundle.attempt_id,
        "variant_id": variant_id,
        "through_tick_index": through_tick_index,
    }

    opening_question = str(arguments.get("opening_question") or "").strip()
    if opening_question:
        try:
            turn = await complete_run_interview_turn(
                session,
                run_id=bundle.run_id,
                attempt_id=bundle.attempt_id,
                variant_id=variant_id,
                persona_id=persona_id,
                through_tick_index=through_tick_index,
                message=opening_question,
                asked_by="doctor",
            )
        except ChatTurnError as exc:
            raise ValueError(str(exc)) from exc
        payload["opening_question"] = opening_question
        payload["answer"] = turn.reply

    return _compact(payload)


async def _ask_interview_question(
    session: AsyncSession,
    ctx: SpindoctorToolContext,
    arguments: dict[str, Any],
) -> str:
    question = str(arguments.get("question") or "").strip()
    if not question:
        raise ValueError("question is required")

    persona_id, run_id, attempt_id, variant_id, persona_name, through_tick_index = (
        _resolve_interview_coordinates(ctx, arguments)
    )
    if not attempt_id or not variant_id:
        raise ValueError("attempt_id and variant_id are required")

    run = await session.get(Run, run_id)
    if run is None:
        raise ValueError("Run not found")
    try:
        variant = _find_attempt_variant(
            run.results if isinstance(run.results, dict) else None,
            attempt_id,
            variant_id,
        )
        validate_interview_variant(
            run,
            variant,
            persona_id=persona_id,
            through_tick_index=through_tick_index,
        )
    except ChatTurnError as exc:
        raise ValueError(str(exc)) from exc

    try:
        turn = await complete_run_interview_turn(
            session,
            run_id=run_id,
            attempt_id=attempt_id,
            variant_id=variant_id,
            persona_id=persona_id,
            through_tick_index=through_tick_index,
            message=question,
            asked_by="doctor",
        )
    except ChatTurnError as exc:
        raise ValueError(str(exc)) from exc

    return _compact(
        {
            "ok": True,
            "persona_id": persona_id,
            "persona_name": persona_name,
            "run_id": run_id,
            "attempt_id": attempt_id,
            "variant_id": variant_id,
            "through_tick_index": through_tick_index,
            "question": question,
            "answer": turn.reply,
        }
    )


async def _read_interview_transcript(
    session: AsyncSession,
    ctx: SpindoctorToolContext,
    arguments: dict[str, Any],
) -> str:
    persona_id, run_id, attempt_id, variant_id, persona_name, through_tick_index = (
        _resolve_interview_coordinates(ctx, arguments)
    )
    if not attempt_id or not variant_id:
        raise ValueError("attempt_id and variant_id are required")

    run = await session.get(Run, run_id)
    if run is None:
        raise ValueError("Run not found")
    try:
        variant = _find_attempt_variant(
            run.results if isinstance(run.results, dict) else None,
            attempt_id,
            variant_id,
        )
        validate_interview_variant(
            run,
            variant,
            persona_id=persona_id,
            through_tick_index=through_tick_index,
        )
    except ChatTurnError as exc:
        raise ValueError(str(exc)) from exc

    rows = (
        await session.execute(
            select(PersonaMessage)
            .where(
                *run_interview_filter(
                    persona_id=persona_id,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    variant_id=variant_id,
                    through_tick_index=through_tick_index,
                )
            )
            .order_by(PersonaMessage.id.asc())
        )
    ).scalars().all()
    messages = [
        {
            "id": row.id,
            "role": row.role,
            "content": row.content,
            "created_at": format_date(row.created_at) if row.created_at else "",
            "asked_by": (
                row.asked_by if row.asked_by in {"doctor", "human"} else None
            ),
        }
        for row in rows
    ]
    return _compact(
        {
            "persona_id": persona_id,
            "persona_name": persona_name,
            "run_id": run_id,
            "attempt_id": attempt_id,
            "variant_id": variant_id,
            "through_tick_index": through_tick_index,
            "messages": messages,
        }
    )


async def make_report_snippet_widget(
    ctx: SpindoctorToolContext,
    *,
    section_id: str,
    title: str | None = None,
) -> SpindoctorWidgetOut:
    label = title or section_id
    return await _widget_out(
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
        report, bundles = await load_spindoctor_source(session, report_id=ctx.report_id)
        if report.mode == "dd":
            raise ValueError(
                "Interview tools require a simulation (OASIS) report, not a DD report"
            )
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
            return await _render_chart(ctx, arguments)
        if name == "start_interview":
            return await _start_interview(session, ctx, arguments)
        return await _place_note(ctx, arguments)

    if name in _READ_INTERVIEW_TOOL_NAMES:
        return await _read_interview_transcript(session, ctx, arguments)

    if name in _INTERVIEW_TOOL_NAMES:
        if name == "ask_interview_question":
            return await _ask_interview_question(session, ctx, arguments)
        raise ValueError(f"Unknown Spinndoktor tool: {name}")

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

    if name == "get_report_dd":
        return await _get_report_dd(arguments, ctx=ctx)

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
