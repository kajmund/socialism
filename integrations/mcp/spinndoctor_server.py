#!/usr/bin/env python3
"""Spinndoktor MCP server — run/report tools, SCB, search, charts (local, no auth)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
for path in (_REPO_ROOT, _BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from integrations.scb.tools import run_scb_tool
from app.database.session import SessionLocal
from app.services.spindoctor_mcp_tools import (
    SpindoctorToolContext,
    spindoctor_mcp_tool_specs,
    run_spindoctor_mcp_tool,
)

ARTIFACT_ROOT = Path(os.environ.get("ARTIFACT_ROOT", str(_BACKEND_ROOT / "data" / "reports")))

server = Server("spinndoktor")


def _openai_spec_to_mcp_tool(spec: dict) -> Tool:
    fn = spec.get("function") or {}
    return Tool(
        name=str(fn.get("name") or ""),
        description=str(fn.get("description") or ""),
        inputSchema=fn.get("parameters") or {"type": "object", "properties": {}},
    )


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [_openai_spec_to_mcp_tool(spec) for spec in spindoctor_mcp_tool_specs()]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    ctx = SpindoctorToolContext(
        report_id=str(arguments.get("report_id") or "").strip() or None
    )
    async with SessionLocal() as session:
        try:
            text = await run_spindoctor_mcp_tool(session, name, arguments, ctx=ctx)
        except Exception as exc:  # noqa: BLE001 — surface tool errors to MCP client
            text = f"Tool error ({name}): {exc}"
        payload: dict[str, object] = {"result": text}
        if ctx.widgets:
            payload["widgets"] = [w.model_dump(mode="json") for w in ctx.widgets]
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
