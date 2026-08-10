"""SCB tool definitions + execution (shared by MCP server and in-app help chat)."""

from __future__ import annotations

import json
from typing import Any

from integrations.scb.client import ScbClient, VariableSelection
from integrations.scb.distributions import fetch_population_distribution, find_region_code

# Full code maps only for small dimensions; large ones get code_count (+ optional filter).
_META_FULL_CODES_MAX = 40

SCB_LOOKUP_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "scb_search_tables",
            "description": (
                "Search SCB Statistikdatabasen for tables by Swedish keywords "
                "(e.g. folkmängd, kön, ålder, kommun, civilstånd, utbildning)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query — Swedish terms work best.",
                    },
                    "page_size": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scb_get_table_meta",
            "description": (
                "Fetch variable codes and category labels for an SCB table "
                "(use before scb_query to pick valid valueCodes). "
                "Pass variable (e.g. Civilstand) to get full codes for one dimension; "
                "without it, large dimensions return code_count only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {
                        "type": "string",
                        "description": "Table id, e.g. TAB638.",
                    },
                    "variable": {
                        "type": "string",
                        "description": (
                            "Optional dimension id (e.g. Civilstand, Region, Alder). "
                            "When set, return full codes for that variable only."
                        ),
                    },
                },
                "required": ["table_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scb_query",
            "description": (
                "Fetch data from an SCB table. Each filter selects one variable; "
                "include every non-eliminable dimension. Returns JSON-stat2."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "string"},
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "variableCode": {"type": "string"},
                                "valueCodes": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "codelist": {"type": "string"},
                            },
                            "required": ["variableCode", "valueCodes"],
                        },
                    },
                },
                "required": ["table_id", "filters"],
            },
        },
    },
]

SCB_POPULATION_DIST_TOOL_SPEC: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "scb_population_dist",
        "description": (
            "Municipality population distribution from SCB folkmängd (age + kön weights, "
            "plus civilstånd). Prefer this for questions like how a kommun is distributed. "
            "Pass region_code (kommunkod, e.g. 0380) or region_name (e.g. Uppsala)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "region_code": {
                    "type": "string",
                    "description": "Kommunkod, e.g. 0380 for Uppsala.",
                },
                "region_name": {
                    "type": "string",
                    "description": "Kommunnamn if code is unknown, e.g. Uppsala.",
                },
                "year": {
                    "type": "string",
                    "default": "2024",
                },
            },
        },
    },
}

SCB_TOOL_SPECS: list[dict[str, Any]] = [
    *SCB_LOOKUP_TOOL_SPECS,
    SCB_POPULATION_DIST_TOOL_SPEC,
]


def help_scb_tool_specs(*, allow_population_dist: bool = True) -> list[dict[str, Any]]:
    """Tools for in-app help chat. Population dist is always available for demographic Q&A."""
    del allow_population_dist  # kept for call-site compat; toggle only affects prompts
    return list(SCB_TOOL_SPECS)


def _compact_json(payload: object, *, limit: int = 120_000) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n… (truncated)"


def _dimension_summary(dim: dict[str, Any], *, include_codes: bool) -> dict[str, Any]:
    category = dim.get("category") or {}
    labels = category.get("label") or {}
    if not isinstance(labels, dict):
        labels = {}
    out: dict[str, Any] = {
        "label": dim.get("label"),
        "code_count": len(labels),
    }
    if include_codes:
        out["codes"] = labels
    return out


def _summarize_table_meta(
    meta: dict[str, Any],
    *,
    table_id: str,
    variable: str | None,
) -> dict[str, Any] | str:
    dimensions = meta.get("dimension") or {}
    if not isinstance(dimensions, dict):
        dimensions = {}

    if variable:
        dim = dimensions.get(variable)
        if dim is None:
            available = sorted(dimensions.keys())
            return (
                f"variable {variable!r} not found on {table_id}. "
                f"Available: {', '.join(available) if available else '(none)'}"
            )
        return {
            "id": table_id,
            "label": meta.get("label"),
            "updated": meta.get("updated"),
            "variable": variable,
            "variables": {
                variable: _dimension_summary(dim, include_codes=True),
            },
        }

    variables: dict[str, Any] = {}
    for dim_id, dim in dimensions.items():
        if not isinstance(dim, dict):
            continue
        category = dim.get("category") or {}
        labels = category.get("label") or {}
        code_count = len(labels) if isinstance(labels, dict) else 0
        variables[dim_id] = _dimension_summary(
            dim,
            include_codes=code_count <= _META_FULL_CODES_MAX,
        )
    return {
        "id": table_id,
        "label": meta.get("label"),
        "updated": meta.get("updated"),
        "variables": variables,
        "hint": (
            "Large dimensions omit codes — pass variable=<id> to fetch full codes "
            "for one dimension."
        ),
    }


async def run_scb_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    client: ScbClient | None = None,
    allow_population_dist: bool = True,
) -> str:
    del allow_population_dist  # always allowed; kept for call-site compat
    scb = client or ScbClient()

    if name == "scb_search_tables":
        query = str(arguments.get("query", "")).strip()
        if not query:
            return "query is required"
        page_size = int(arguments.get("page_size") or 10)
        data = await scb.search_tables(query, page_size=max(1, min(page_size, 50)))
        tables = data.get("tables") or []
        slim = [
            {
                "id": table.get("id"),
                "label": table.get("label"),
                "variableNames": table.get("variableNames"),
                "lastPeriod": table.get("lastPeriod"),
                "updated": table.get("updated"),
            }
            for table in tables
        ]
        return _compact_json({"tables": slim, "page": data.get("page")})

    if name == "scb_get_table_meta":
        table_id = str(arguments.get("table_id", "")).strip()
        if not table_id:
            return "table_id is required"
        variable_raw = arguments.get("variable")
        variable = str(variable_raw).strip() if variable_raw else ""
        meta = await scb.get_table_meta(table_id)
        summary = _summarize_table_meta(
            meta,
            table_id=table_id,
            variable=variable or None,
        )
        if isinstance(summary, str):
            return summary
        return _compact_json(summary)

    if name == "scb_query":
        table_id = str(arguments.get("table_id", "")).strip()
        raw_filters = arguments.get("filters")
        if not table_id:
            return "table_id is required"
        if not isinstance(raw_filters, list) or not raw_filters:
            return "filters must be a non-empty array"
        filters: list[VariableSelection] = []
        for item in raw_filters:
            if not isinstance(item, dict):
                continue
            variable = str(item.get("variableCode", "")).strip()
            values = item.get("valueCodes")
            if not variable or not isinstance(values, list):
                continue
            selection: VariableSelection = {
                "variableCode": variable,
                "valueCodes": [str(code) for code in values],
            }
            codelist = item.get("codelist")
            if isinstance(codelist, str) and codelist.strip():
                selection["codelist"] = codelist.strip()
            filters.append(selection)
        if not filters:
            return "filters must include variableCode and valueCodes"
        data = await scb.query(table_id, filters)
        return _compact_json(data)

    if name == "scb_population_dist":
        region_code = str(arguments.get("region_code", "")).strip()
        region_name = str(arguments.get("region_name", "")).strip()
        year = str(arguments.get("year") or "2024").strip()
        if not region_code and region_name:
            resolved = await find_region_code(region_name, client=scb)
            if resolved is None:
                return f"Could not resolve municipality: {region_name}"
            region_code = resolved
        if not region_code:
            return "region_code or region_name is required"
        payload = await fetch_population_distribution(
            region_code,
            year=year,
            client=scb,
        )
        return _compact_json(payload)

    raise ValueError(f"Unknown SCB tool: {name}")
