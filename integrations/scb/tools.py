"""SCB tool definitions + execution (shared by MCP server and in-app help chat)."""

from __future__ import annotations

import json
from typing import Any

from integrations.scb.client import ScbClient, VariableSelection

SCB_TOOL_SPECS: list[dict[str, Any]] = [
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
                "(use before scb_query to pick valid valueCodes)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_id": {
                        "type": "string",
                        "description": "Table id, e.g. TAB638.",
                    }
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


def _compact_json(payload: object, *, limit: int = 120_000) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n… (truncated)"


async def run_scb_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    client: ScbClient | None = None,
) -> str:
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
        meta = await scb.get_table_meta(table_id)
        summary: dict[str, Any] = {
            "id": table_id,
            "label": meta.get("label"),
            "updated": meta.get("updated"),
            "variables": {},
        }
        for dim_id, dim in (meta.get("dimension") or {}).items():
            category = dim.get("category") or {}
            labels = category.get("label") or {}
            summary["variables"][dim_id] = {
                "label": dim.get("label"),
                "codes": labels,
            }
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

    raise ValueError(f"Unknown SCB tool: {name}")
